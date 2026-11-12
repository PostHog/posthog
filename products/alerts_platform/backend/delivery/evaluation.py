"""One evaluation, from the address a delivery carries to the messages it sends.

The layer that knows a transport exists. `dispatch.deliver` handles one destination, and this
is what decides which destinations there are and which transport each one takes.
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from functools import cache
from typing import Any, Final
from uuid import UUID

import structlog

from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.utils import absolute_uri

from products.alerts_platform.backend.delivery import (
    delivery_paths,
    describers,
    episode_paths,
    legacy_webhook,
    recipients,
    subscribers,
)
from products.alerts_platform.backend.delivery.destinations import list_alert_destination_groups, live_hog_function_ids
from products.alerts_platform.backend.delivery.discord import DiscordTransport
from products.alerts_platform.backend.delivery.dispatch import (
    add_late_image as add_late_image_to_target,
    deliver,
)
from products.alerts_platform.backend.delivery.email import EmailTransport
from products.alerts_platform.backend.delivery.in_app import InAppTransport
from products.alerts_platform.backend.delivery.message import INCIDENT_KINDS, AlertMessage
from products.alerts_platform.backend.delivery.pagerduty import PagerDutyTransport, source_incident_key
from products.alerts_platform.backend.delivery.slack import SlackTransport
from products.alerts_platform.backend.delivery.teams import TeamsTransport
from products.alerts_platform.backend.delivery.telemetry import record_delivery
from products.alerts_platform.backend.delivery.thread_store import DatabaseThreadStore, ThreadBusy, ThreadKey
from products.alerts_platform.backend.delivery.transport import (
    DeliveryError,
    DeliveryTransport,
    DestinationMisconfigured,
    RootImageEditor,
)
from products.alerts_platform.backend.delivery.webhook import WebhookTransport
from products.alerts_platform.backend.facade.contracts import (
    NO_LATE_IMAGE,
    AlertDeliveryRequest,
    AlertDestinationData,
    AlertDestinationGroup,
    AlertEventKind,
    AnnouncedTransition,
    DeliveryPath,
    DestinationType,
    EvaluationAnnouncement,
    IncidentAction,
    LateImageResult,
    LegacyEventEmission,
    MessageLink,
    StoredAlertDestination,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertKind, PlatformAlertOwner
from products.alerts_platform.backend.logic import delivery_holds
from products.alerts_platform.backend.logic.alert_destinations import (
    INCIDENT_DESTINATION_TYPES,
    enabled_alert_destinations,
)
from products.alerts_platform.backend.logic.platform_alert_events import announced_kinds, announcement
from products.alerts_platform.backend.models import PlatformAlertConfiguration
from products.alerts_platform.backend.temporal.metrics import DeliveryOutcomeLabel, increment_deliveries, safe_record

logger = structlog.get_logger(__name__)

# Emitted events have no conversation, so each delivery part keeps one row in the thread store
# under this provider and a fixed episode. The row only records which evaluations already emitted.
_EMISSION_PROVIDER: Final = "legacy_events"
_EMISSION_EPISODE: Final = datetime(1970, 1, 1, tzinfo=UTC)

# A destination type with no entry here has no native transport, and delivery skips it. Hand an
# alert to the platform only when its destinations use no such type. Nothing checks this in code,
# and one alert delivering natively to one destination and through a HogFunction to another would
# send two differently worded messages for one event.
_TRANSPORTS: Final[dict[DestinationType, type[DeliveryTransport]]] = {
    DestinationType.SLACK: SlackTransport,
    DestinationType.WEBHOOK: WebhookTransport,
    DestinationType.TEAMS: TeamsTransport,
    DestinationType.DISCORD: DiscordTransport,
    DestinationType.PAGERDUTY: PagerDutyTransport,
    DestinationType.EMAIL: EmailTransport,
    DestinationType.IN_APP: InAppTransport,
}


@frozen
class DeliveryOutcome:
    """What one evaluation's delivery did, for the activity to log and count."""

    live: bool
    sent: int
    skipped_without_transport: int
    # The broker took the events, which does not mean a HogFunction ran.
    emitted_transitions: int = 0
    emitted_events: int = 0


class _WebhookTransports:
    """The webhook transport for one evaluation, with the legacy body when the team keeps it.

    The flag is read once, and only when a webhook destination is about to be sent to. A failed read
    is a failed delivery: a guess either way sends a body some receiver cannot parse, and a retry
    costs only time.
    """

    def __init__(self, team: Team, request: AlertDeliveryRequest, announced: EvaluationAnnouncement) -> None:
        self._team = team
        self._request = request
        self._announced = announced
        self._transport: WebhookTransport | None = None
        self._failure: DeliveryError | None = None

    def get(self) -> WebhookTransport:
        # A failed read is kept too, so a flags outage costs one lookup per evaluation rather than
        # one per webhook, inside an activity whose time is shared by every destination.
        if self._failure is not None:
            raise self._failure
        if self._transport is None:
            try:
                self._transport = WebhookTransport(legacy_body=self._legacy_body())
            except DeliveryError as error:
                self._failure = error
                raise
        return self._transport

    def _legacy_body(self) -> Callable[[AlertMessage], dict[str, Any]] | None:
        body = legacy_webhook.body_for(self._request.source)
        if body is None or self._request.alert_kind != PlatformAlertKind.THRESHOLD:
            return None
        try:
            keeps_legacy_body = legacy_webhook.keeps_legacy_webhook_body(self._team)
        except Exception as error:
            raise DeliveryError("Could not read which webhook body this team receives.") from error
        if keeps_legacy_body is None:
            raise DeliveryError("Could not read which webhook body this team receives.")
        if not keeps_legacy_body:
            return None
        team_id = self._team.id
        alert_id = self._request.destination_alert_id
        consecutive_failures = self._announced.consecutive_failures
        return lambda message: body(
            project_id=team_id,
            alert_id=alert_id,
            alert_name=message.alert_name,
            consecutive_failures=consecutive_failures,
            transition=message.transition,
        )


def deliver_evaluation(request: AlertDeliveryRequest) -> DeliveryOutcome:
    """Sends what one evaluation decided, to every destination configured for it."""
    # A source that still owns its alert sends its own message, so the platform sends nothing for it.
    if not request.owned_by_platform:
        return DeliveryOutcome(live=False, sent=0, skipped_without_transport=0)
    team = Team.objects.filter(id=request.team_id).first()
    if team is None:
        return DeliveryOutcome(live=False, sent=0, skipped_without_transport=0)
    if delivery_holds.blocks_delivery(request.team_id, request.configuration_id, request.evaluation_key):
        logger.info(
            "alerts_platform_delivery_held",
            configuration_id=request.configuration_id,
            evaluation_key=request.evaluation_key,
        )
        return DeliveryOutcome(live=True, sent=0, skipped_without_transport=0)

    announced = announcement(
        request.team_id,
        request.configuration_id,
        request.evaluation_key,
        source=request.source,
        incident_grouping_keys=request.incident_actions.keys(),
        part=request.part,
        parts=request.parts,
    )
    if announced is None:
        return DeliveryOutcome(live=True, sent=0, skipped_without_transport=0)
    if stale := delivery_holds.stale_held_triggers(request, announced.transitions):
        logger.info(
            "alerts_platform_delivery_stale_trigger_dropped",
            configuration_id=request.configuration_id,
            evaluation_key=request.evaluation_key,
            groups=len(stale),
        )
        request = replace(
            request,
            incident_actions={key: action for key, action in request.incident_actions.items() if key not in stale},
        )
    platform_destinations = _platform_destinations(request)
    native_announced, emissions = _split_by_path(request, announced, platform_destinations)
    emitter = delivery_paths.emitter_for(request.source) if emissions else None
    notice_keys: dict[str, str] = {}
    if request.parts > 1 and request.overflowed:
        notice_keys = _overflow_notice_keys(
            request,
            platform_destinations,
            announced_kinds(
                request.team_id,
                request.configuration_id,
                request.evaluation_key,
                incident_grouping_keys=request.incident_actions.keys(),
            ),
        )

    thread_store = DatabaseThreadStore(request.team_id)
    project = MessageLink(label=team.name, url=absolute_uri(f"/project/{team.id}"))
    sent = 0
    skipped = 0
    busy: list[str] = []
    failures: list[str] = []
    first_refusal: DeliveryError | None = None
    # Per subscription rather than per destination. A destination subscribes to some of the
    # kinds an alert can announce, so one that asked for firings must not be handed the resolve
    # that another group produced in the same evaluation.
    action_by_event_id = {
        event_id: IncidentAction(action) for action, event_id in request.event_ids_by_incident_action.items()
    }
    webhook_transports = _WebhookTransports(team, request, announced)
    message_event_ids = set(request.event_ids_by_kind.values())
    # Destinations already told about the overflow, so each hears it once, on its first message.
    noticed: set[str] = set()
    native_by_event = _by_subscription(request, native_announced)
    for event_id, all_transitions in _by_subscription(request, announced).items():
        for subscribed_destination in _destinations(request, event_id, platform_destinations):
            transitions = (
                native_by_event.get(event_id, ()) if subscribed_destination.receives_emitted_events else all_transitions
            )
            if not transitions:
                continue
            target = subscribed_destination.data
            overflowed = 0
            destination = json.dumps(target, sort_keys=True)
            owns_notice = request.parts <= 1 or any(
                transition.grouping_key == notice_keys.get(destination) for transition in transitions
            )
            if request.overflowed and event_id in message_event_ids and destination not in noticed and owns_notice:
                overflowed = request.overflowed
                noticed.add(destination)
            transport_class = _TRANSPORTS.get(target["type"])
            if transport_class is None:
                skipped += 1
                safe_record(
                    increment_deliveries,
                    request.source.value,
                    target["type"],
                    DeliveryPath.NATIVE.value,
                    "no_transport",
                    len(transitions),
                )
                continue
            try:
                transport = webhook_transports.get() if transport_class is WebhookTransport else transport_class()
            except DeliveryError as error:
                # Fails before a send starts, where `deliver` counts its failures, so it is counted here.
                for _ in transitions:
                    record_delivery(
                        team_id=request.team_id,
                        configuration_id=request.configuration_id,
                        provider=WebhookTransport.provider,
                        destination_id=subscribed_destination.id,
                        succeeded=False,
                        error=str(error),
                    )
                safe_record(
                    increment_deliveries,
                    request.source.value,
                    WebhookTransport.provider,
                    DeliveryPath.NATIVE.value,
                    "failed",
                    len(transitions),
                )
                failures.append(str(error))
                first_refusal = first_refusal or error
                continue
            try:
                deliver(
                    transport=transport,
                    thread_store=thread_store,
                    team_id=request.team_id,
                    configuration_id=request.configuration_id,
                    evaluation_key=request.evaluation_key,
                    target=target,
                    destination_id=subscribed_destination.id,
                    announcement=replace(
                        announced,
                        transitions=transitions,
                        overflowed=overflowed,
                        overflow_is_lower_bound=request.overflow_is_lower_bound,
                    ),
                    incident_action=action_by_event_id.get(event_id),
                    source_alert_url=request.source_alert_url,
                    source_incident_key=source_incident_key(request.destination_alert_id),
                    project=project,
                )
            except ThreadBusy as error:
                busy.append(str(error))
            # A destination that refuses every send, such as a deleted channel, must not cost the
            # destinations after it their message on every attempt. Temporal records the message
            # and the cause chain, and a transport words its own refusals safely. Any other
            # exception's text can carry a credential URL, so it is named by class and not chained.
            except DeliveryError as error:
                failures.append(str(error))
                first_refusal = first_refusal or error
            except Exception as error:
                failures.append(type(error).__name__)
            else:
                sent += 1
    # Emitted last and only without a held thread, because the workflow runs a held delivery again
    # in full. A native send that fails also reruns the whole delivery, so the store records the
    # emission, and a rerun does not send every HogFunction message a second time.
    emitted: tuple[LegacyEventEmission, ...] = ()
    if emitter is not None and not busy:
        try:
            emission = thread_store.claim(
                ThreadKey(
                    configuration_id=request.configuration_id,
                    grouping_key="",
                    provider=_EMISSION_PROVIDER,
                    channel_target=str(request.part),
                    episode_started_at=_EMISSION_EPISODE,
                ),
                request.evaluation_key,
            )
        except ThreadBusy as error:
            busy.append(str(error))
            emission = None
            _count_emissions(request, "busy", len(emissions))
        else:
            if emission is None:
                _count_emissions(request, "already_delivered", len(emissions))
        if emission is not None:
            try:
                emitter(request=request, announcement=announced, emissions=emissions)
            except Exception as error:
                thread_store.release(emission)
                logger.warning(
                    "alerts_platform_legacy_event_emission_failed",
                    team_id=request.team_id,
                    configuration_id=request.configuration_id,
                    exc_info=True,
                )
                failures.append(f"legacy events: {type(error).__name__}")
                _count_emissions(request, "failed", len(emissions))
            else:
                thread_store.delivered(emission, None)
                emitted = emissions
                _count_emissions(request, "sent", len(emissions))
    # A held thread wins over a failure. The workflow waits a held thread out and then runs the
    # whole delivery again, which retries the failed destinations too. A failure raised instead
    # spends the activity's retries inside the claim's TTL, and the held message is lost.
    if busy:
        # The failures ride along, so a wait that ends still says which destinations refused.
        raise ThreadBusy("; ".join([*busy, *failures]))
    if failures:
        raise DeliveryError(f"{len(failures)} destination(s) failed: " + "; ".join(failures)) from first_refusal
    return DeliveryOutcome(
        live=True,
        sent=sent,
        skipped_without_transport=skipped,
        emitted_transitions=len(emitted),
        emitted_events=sum(emission.event_count for emission in emitted),
    )


def add_late_image(request: AlertDeliveryRequest, late_detail: dict[str, Any]) -> LateImageResult:
    """Puts the image the source draws from `late_detail` into the messages this evaluation's firings
    opened, after they went out without it.

    `late_detail` is what the check would have recorded in `source_detail` had it been ready, so the
    source's own image resolver mints the image, as it does for a message that carries it on time.

    Only a transport that can edit what it sent takes part, which is Slack. Each destination subscribed
    to firings is read now, as a delivery reads it, and one with no message for the evaluation yet
    counts as waiting, because its delivery may still be on the way.
    """
    firing_event = request.event_ids_by_kind.get(AlertEventKind.FIRING.value)
    if not request.owned_by_platform or not request.sends_messages or firing_event is None:
        return NO_LATE_IMAGE
    announced = announcement(
        request.team_id,
        request.configuration_id,
        request.evaluation_key,
        source=request.source,
        incident_grouping_keys=request.incident_actions.keys(),
        part=request.part,
        parts=request.parts,
    )
    firings = tuple(
        transition
        for transition in (announced.transitions if announced else ())
        if transition.kind == AlertEventKind.FIRING
    )
    if not firings:
        return NO_LATE_IMAGE
    # One image for every firing, because a source's late detail describes the check, not a group.
    first = firings[0]
    image = describers.resolve_image(
        request.source,
        team_id=request.team_id,
        transition=replace(first, source_detail={**first.source_detail, **late_detail}),
    )
    if image is None:
        return NO_LATE_IMAGE

    # A firing already sent through HogFunctions has no native message for an emitted-events destination.
    @cache
    def natively_sent() -> tuple[AnnouncedTransition, ...]:
        return tuple(transition for transition in firings if not _sent_through_hog_functions(request, transition))

    thread_store = DatabaseThreadStore(request.team_id)
    result = NO_LATE_IMAGE
    for subscribed_destination in _destinations(request, firing_event, _platform_destinations(request)):
        transport_class = _TRANSPORTS.get(subscribed_destination.data["type"])
        if transport_class is None or not issubclass(transport_class, RootImageEditor):
            continue
        transitions = natively_sent() if subscribed_destination.receives_emitted_events else firings
        if not transitions:
            continue
        try:
            result += add_late_image_to_target(
                transport=transport_class(),
                thread_store=thread_store,
                team_id=request.team_id,
                configuration_id=request.configuration_id,
                evaluation_key=request.evaluation_key,
                target=subscribed_destination.data,
                transitions=transitions,
                image=image,
            )
        # One channel that refuses the edit must not cost the others theirs. A refusal that only the
        # destination's owner can fix gets no retry. Any other, such as a rate limit, waits for one.
        except DeliveryError as error:
            logger.warning(
                "alerts_platform_late_image_refused", destination_id=subscribed_destination.id, error=str(error)
            )
            if not isinstance(error, DestinationMisconfigured):
                result += LateImageResult(edited=0, waiting=1)
    return result


def _sent_through_hog_functions(request: AlertDeliveryRequest, transition: AnnouncedTransition) -> bool:
    if transition.episode_started_at is None or delivery_paths.emitter_for(request.source) is None:
        return False
    path = episode_paths.stored_path(
        team_id=request.team_id,
        configuration_id=request.configuration_id,
        grouping_key=transition.grouping_key,
        episode_started_at=transition.episode_started_at,
    )
    return path == DeliveryPath.HOG_FUNCTION


def _count_emissions(request: AlertDeliveryRequest, outcome: DeliveryOutcomeLabel, transitions: int) -> None:
    # The alert's own HogFunctions send these, so the provider is the path itself.
    safe_record(
        increment_deliveries,
        request.source.value,
        DeliveryPath.HOG_FUNCTION.value,
        DeliveryPath.HOG_FUNCTION.value,
        outcome,
        transitions,
    )


def _split_by_path(
    request: AlertDeliveryRequest,
    announced: EvaluationAnnouncement,
    platform_destinations: "_PlatformDestinations",
) -> tuple[EvaluationAnnouncement, tuple[LegacyEventEmission, ...]]:
    """The transitions HogFunction destinations receive natively, and the ones the source emits for them.

    A transition inside a firing takes the path its firing took first, so a firing and its resolve
    never split across paths. Any other transition takes the path its destinations allow now.

    An alert whose destinations the platform keeps sends every transition to them natively. Its
    stock destinations are `AlertDestination` rows, so any HogFunction listening on the alert is one
    a person built, and the source also emits every transition for it. That includes a function
    from a custom template or one with no `alert_id` filter, which no destination lookup lists, so
    the source emits without asking who listens, as its own stack did. No destination is on both
    paths, so nothing is sent twice. Moving an existing alert's destinations onto the platform must
    therefore disable the HogFunctions it copies, or each of them hears every transition as well.
    """
    if request.alert_kind != PlatformAlertKind.THRESHOLD or delivery_paths.emitter_for(request.source) is None:
        return announced, ()
    if platform_destinations.owns_destinations:
        return announced, _emissions(request, announced.transitions)

    # Read once per delivery, because the chooser reads every destination of the alert.
    @cache
    def choose() -> DeliveryPath:
        return delivery_paths.choose_path(
            source=request.source,
            team_id=request.team_id,
            alert_id=request.destination_alert_id,
            allowed_event_ids=_all_event_ids(request),
        )

    native: list[AnnouncedTransition] = []
    emitted: list[AnnouncedTransition] = []
    for transition in announced.transitions:
        path = (
            episode_paths.episode_path(
                team_id=request.team_id,
                configuration_id=request.configuration_id,
                grouping_key=transition.grouping_key,
                episode_started_at=transition.episode_started_at,
                choose=choose,
            )
            if transition.episode_started_at is not None
            else choose()
        )
        (native if path == DeliveryPath.NATIVE else emitted).append(transition)
    return replace(announced, transitions=tuple(native)), _emissions(request, emitted)


def _emissions(
    request: AlertDeliveryRequest, transitions: Sequence[AnnouncedTransition]
) -> tuple[LegacyEventEmission, ...]:
    """The events the source emits for its HogFunctions, one per transition a destination subscribes to."""
    emissions: list[LegacyEventEmission] = []
    for transition in transitions:
        subscribed = _subscribed_events(request, transition)
        if subscribed.message_event or subscribed.incident_event:
            emissions.append(
                LegacyEventEmission(
                    transition=transition,
                    sends_message=subscribed.message_event is not None,
                    incident_action=subscribed.incident_action if subscribed.incident_event else None,
                )
            )
    return tuple(emissions)


def _all_event_ids(request: AlertDeliveryRequest) -> list[str]:
    """Every event the alert's HogFunctions can listen to: its message events and its incident events."""
    return [*request.event_ids_by_kind.values(), *request.event_ids_by_incident_action.values()]


def _overflow_notice_keys(
    request: AlertDeliveryRequest,
    platform_destinations: "_PlatformDestinations",
    kinds: dict[str, AlertEventKind],
) -> dict[str, str]:
    """For each destination, the grouping key whose part tells it about the overflow.

    Read from the kinds of the whole announcement, so every part agrees, and a destination whose
    messages all land in a later part still hears the notice once.
    """
    if not request.sends_messages:
        return {}
    first_by_event_id: dict[str, str] = {}
    for grouping_key, kind in kinds.items():
        event_id = request.event_ids_by_kind.get(kind.value)
        if event_id is not None:
            first_by_event_id[event_id] = min(first_by_event_id.get(event_id, grouping_key), grouping_key)
    keys: dict[str, str] = {}
    for event_id, first in first_by_event_id.items():
        for subscribed_destination in _destinations(request, event_id, platform_destinations):
            destination = json.dumps(subscribed_destination.data, sort_keys=True)
            keys[destination] = min(keys.get(destination, first), first)
    return keys


def _by_subscription(
    request: AlertDeliveryRequest, announced: EvaluationAnnouncement
) -> dict[str, tuple[AnnouncedTransition, ...]]:
    """The transitions this evaluation announced or moved an incident with, grouped by the event a
    destination subscribes to.

    A kind the source does not map to an event id reaches nobody: no destination can have asked
    for it. Nor does a message on a delivery the source did not announce, which exists only for
    its incident actions. An incident event is set apart from every message event, so a chat
    destination never hears about an incident and an incident manager never gets a message.
    """
    grouped: dict[str, list[AnnouncedTransition]] = {}
    for transition in announced.transitions:
        subscribed = _subscribed_events(request, transition)
        for event_id in (subscribed.message_event, subscribed.incident_event):
            if event_id is not None:
                grouped.setdefault(event_id, []).append(transition)
    return {event_id: tuple(transitions) for event_id, transitions in grouped.items()}


@frozen
class _SubscribedEvents:
    message_event: str | None
    incident_action: IncidentAction | None
    incident_event: str | None


def _subscribed_events(request: AlertDeliveryRequest, transition: AnnouncedTransition) -> _SubscribedEvents:
    """The message event and the incident event one transition reaches, on either delivery path."""
    action = request.incident_actions.get(transition.grouping_key)
    return _SubscribedEvents(
        message_event=request.event_ids_by_kind.get(transition.kind.value) if request.sends_messages else None,
        incident_action=action,
        incident_event=request.event_ids_by_incident_action.get(action.value) if action else None,
    )


@frozen
class _SubscribedDestination:
    # The HogFunction or `AlertDestination` row its sends are recorded under. None for a source's own recipients.
    id: str | None
    data: AlertDestinationData
    # Whether the destination hears the events the source emits for its HogFunctions.
    receives_emitted_events: bool


@frozen
class _PlatformDestinations:
    """An alert's enabled `AlertDestination` rows, with the kind each of its event ids announces."""

    destinations: tuple[StoredAlertDestination, ...]
    owns_destinations: bool
    # Rows that copy a HogFunction that still exists. The HogFunction sends for them.
    copies: frozenset[str]
    # Whether the rows name the alert's subscribers, so the source's own subscriber groups are not sent too.
    holds_subscribers: bool
    # The addresses the source's own settings name, read once per delivery.
    recipients: tuple[str, ...]
    kind_by_event_id: dict[str, AlertEventKind]
    incident_event_ids: frozenset[str]


def _platform_destinations(request: AlertDeliveryRequest) -> _PlatformDestinations:
    """The alert's `AlertDestination` rows, and whether they are all of its destinations. Read once per
    delivery, and after the check, so a destination removed in between is not sent to."""
    owner = (
        PlatformAlertConfiguration.objects.for_team(request.team_id)
        .filter(id=request.configuration_id)
        .values_list("destinations_owner", flat=True)
        .first()
    )
    owns_destinations = owner == PlatformAlertOwner.PLATFORM
    incident_kinds = {
        event_id: INCIDENT_KINDS[IncidentAction(action)]
        for action, event_id in request.event_ids_by_incident_action.items()
    }
    destinations = enabled_alert_destinations(team_id=request.team_id, configuration_id=UUID(request.configuration_id))
    return _PlatformDestinations(
        destinations=_with_subscribers_resolved(request, destinations),
        owns_destinations=owns_destinations,
        copies=frozenset() if owns_destinations else _copies_of_live_hog_functions(request.team_id, destinations),
        holds_subscribers=any(_names_users(destination.data) for destination in destinations),
        # Recipients read messages only, so a delivery that only moves an incident skips the lookup.
        recipients=recipients.addresses(
            request.source, team_id=request.team_id, configuration_id=UUID(request.configuration_id)
        )
        if owns_destinations and request.sends_messages
        else (),
        kind_by_event_id={
            **{event_id: AlertEventKind(kind) for kind, event_id in request.event_ids_by_kind.items()},
            **incident_kinds,
        },
        incident_event_ids=frozenset(incident_kinds),
    )


_SUBSCRIBER_TYPES: Final = frozenset({DestinationType.EMAIL, DestinationType.IN_APP})


def _with_subscribers_resolved(
    request: AlertDeliveryRequest, destinations: tuple[StoredAlertDestination, ...]
) -> tuple[StoredAlertDestination, ...]:
    """The rows, with the users an email or in-app row names resolved now, so one who lost access is
    skipped. A row left with nobody to tell is dropped."""
    if not any(destination.data["type"] in _SUBSCRIBER_TYPES for destination in destinations):
        return destinations
    team = Team.objects.filter(id=request.team_id).first() if request.sends_messages else None
    resolved: list[StoredAlertDestination] = []
    for destination in destinations:
        if destination.data["type"] not in _SUBSCRIBER_TYPES:
            resolved.append(destination)
            continue
        # Email and in-app hear messages only, so a delivery that only moves an incident skips the lookup.
        if team is None:
            continue
        data = subscribers.resolve(
            request.source, team=team, configuration_id=UUID(request.configuration_id), data=destination.data
        )
        if data is not None:
            resolved.append(replace(destination, data=data))
    return tuple(resolved)


def _names_users(data: AlertDestinationData) -> bool:
    return data["type"] == DestinationType.IN_APP or (
        data["type"] == DestinationType.EMAIL and "email_user_ids" in data
    )


def _is_subscriber_group(group: AlertDestinationGroup) -> bool:
    """A group the source adds for its own subscribers rather than a HogFunction a person configured."""
    return not group.hog_function_ids and group.data["type"] in _SUBSCRIBER_TYPES


def _copies_of_live_hog_functions(team_id: int, destinations: tuple[StoredAlertDestination, ...]) -> frozenset[str]:
    """Read apart from the alert's destination lookup, which misses a HogFunction whose alert filter a
    person removed, while that function still hears every emitted event. A disabled HogFunction
    counts too: a person who disabled it did not ask its copy to send instead."""
    copied = {
        hog_function_id for destination in destinations for hog_function_id in destination.legacy_hog_function_ids
    }
    live = live_hog_function_ids(team_id=team_id, hog_function_ids=copied)
    return frozenset(
        str(destination.id) for destination in destinations if live.intersection(destination.legacy_hog_function_ids)
    )


def _destinations(
    request: AlertDeliveryRequest,
    event_id: str,
    platform_destinations: "_PlatformDestinations",
) -> list[_SubscribedDestination]:
    """Who subscribed to this event, resolved now rather than pinned when the check ran.

    A destination removed between the check and the send is not sent to, which a pinned set
    would get wrong.

    Beside its HogFunctions, an alert can have `AlertDestination` rows. While a stock destination
    is moving from one to the other, it is both: a row whose `legacy_hog_function_ids` name the
    HogFunctions it copies. The HogFunctions send until they are deleted, and the row is skipped.
    Native delivery already sends a stock HogFunction group, and a HogFunction that runs its own
    code hears every event the source emits, which no row can stop.

    Subscribers move the other way: once the rows name them, the source's own subscriber groups
    are left out. Both are decided from the rows this delivery read, so a backfill that lands in
    between cannot leave a subscriber out of both.
    """
    rows = _platform_subscribers(event_id, platform_destinations)
    if platform_destinations.owns_destinations:
        return rows
    groups = list_alert_destination_groups(
        team_id=request.team_id,
        alert_id=request.destination_alert_id,
        allowed_event_ids=[event_id],
    )
    return [
        *(
            _SubscribedDestination(
                id=str(min(group.hog_function_ids)) if group.hog_function_ids else None,
                data=group.data,
                receives_emitted_events=group.receives_emitted_events,
            )
            for group in groups
            if group.fully_enabled and not (platform_destinations.holds_subscribers and _is_subscriber_group(group))
        ),
        *(row for row in rows if row.id not in platform_destinations.copies),
    ]


def _platform_subscribers(event_id: str, platform: _PlatformDestinations) -> list[_SubscribedDestination]:
    """The `AlertDestination` rows that hear this event.

    A message event reaches every destination but an incident manager that asked for its kind. An
    incident event reaches every incident manager, whatever kinds it lists: one that heard a
    trigger and not its resolve would keep the incident open.
    """
    kind = platform.kind_by_event_id.get(event_id)
    if kind is None:
        return []
    incident = event_id in platform.incident_event_ids
    subscribers = [
        _SubscribedDestination(id=str(destination.id), data=destination.data, receives_emitted_events=False)
        for destination in platform.destinations
        if (destination.data["type"] in INCIDENT_DESTINATION_TYPES) == incident
        and (incident or kind.delivered_as in destination.event_kinds)
    ]
    # The source's recipients read messages. An incident edge is for an incident manager only.
    if platform.recipients and not incident:
        email: AlertDestinationData = {"type": DestinationType.EMAIL, "email_addresses": list(platform.recipients)}
        subscribers.append(_SubscribedDestination(id=None, data=email, receives_emitted_events=False))
    return subscribers
