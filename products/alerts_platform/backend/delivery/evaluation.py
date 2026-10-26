"""One evaluation, from the address a delivery carries to the messages it sends.

The layer that knows a transport exists. `dispatch.deliver` handles one destination, and this
is what decides which destinations there are and which transport each one takes.
"""

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from functools import cache
from typing import Any, Final

import structlog

from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.utils import absolute_uri

from products.alerts_platform.backend.delivery import delivery_paths, episode_paths, legacy_webhook
from products.alerts_platform.backend.delivery.destinations import list_alert_destination_groups
from products.alerts_platform.backend.delivery.discord import DiscordTransport
from products.alerts_platform.backend.delivery.dispatch import deliver
from products.alerts_platform.backend.delivery.email import EmailTransport
from products.alerts_platform.backend.delivery.in_app import InAppTransport
from products.alerts_platform.backend.delivery.message import AlertMessage
from products.alerts_platform.backend.delivery.pagerduty import PagerDutyTransport, source_incident_key
from products.alerts_platform.backend.delivery.slack import SlackTransport
from products.alerts_platform.backend.delivery.team_flags import team_flag_enabled
from products.alerts_platform.backend.delivery.teams import TeamsTransport
from products.alerts_platform.backend.delivery.telemetry import record_delivery
from products.alerts_platform.backend.delivery.thread_store import DatabaseThreadStore, ThreadBusy, ThreadKey
from products.alerts_platform.backend.delivery.transport import DeliveryError, DeliveryTransport
from products.alerts_platform.backend.delivery.webhook import WebhookTransport
from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    AlertDestinationData,
    AlertEventKind,
    AnnouncedTransition,
    DeliveryPath,
    DestinationType,
    EvaluationAnnouncement,
    IncidentAction,
    LegacyEventEmission,
    MessageLink,
)
from products.alerts_platform.backend.logic.platform_alert_events import announced_kinds, announcement
from products.alerts_platform.backend.temporal.metrics import DeliveryOutcomeLabel, increment_deliveries, safe_record

logger = structlog.get_logger(__name__)

# Emitted events have no conversation, so each delivery part keeps one row in the thread store
# under this provider and a fixed episode. The row only records which evaluations already emitted.
_EMISSION_PROVIDER: Final = "legacy_events"
_EMISSION_EPISODE: Final = datetime(1970, 1, 1, tzinfo=UTC)

# Whether the platform may contact a team's destinations for an alert its source still owns. Only
# the platform reads it: the source keeps delivering regardless, so a team with this on receives
# the legacy message and the native one. An alert the platform owns never reads it, because the
# source sends nothing for that alert and a flag-eval failure would silence it.
LIVE_DELIVERY_FLAG: Final = "alert-platform-live-delivery"

# A destination type with no entry here has no native transport, and delivery skips it. Make a
# team live only when its alerts use no such type. Nothing checks this in code, and one alert
# delivering natively to one destination and through a HogFunction to another would send two
# differently worded messages for one event.
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


def destinations_are_live(team: Team) -> bool:
    """Whether this team's destinations are the platform's to contact.

    Fail closed. A flag-eval blip leaves the production logs path as the only deliverer, which
    is where everything was before this existed. Reading a blip the other way starts sending.
    """
    try:
        return bool(team_flag_enabled(LIVE_DELIVERY_FLAG, team))
    except Exception:
        logger.warning(
            "alerts_platform_live_delivery_flag_check_failed_defaulting_off",
            team_id=team.id,
            exc_info=True,
        )
        return False


class _WebhookTransports:
    """The webhook transport for one evaluation, with the legacy body when the team keeps it.

    The flag is read once, and only when a webhook destination is about to be sent to. Unlike the
    live-delivery flag, a failed read is a failed delivery: a guess either way sends a body some
    receiver cannot parse, and a retry costs only time.
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
        if body is None:
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
    team = Team.objects.filter(id=request.team_id).first()
    if team is None or not (request.owned_by_platform or destinations_are_live(team)):
        return DeliveryOutcome(live=False, sent=0, skipped_without_transport=0)

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
    native_announced, emissions = _split_by_path(request, announced)
    emitter = delivery_paths.emitter_for(request.source) if emissions else None
    notice_keys: dict[str, str] = {}
    if request.parts > 1 and request.overflowed:
        notice_keys = _overflow_notice_keys(
            request,
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
        for subscribed_destination in _destinations(request, event_id):
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
                    source_incident_key=source_incident_key(request.destination_alert_id)
                    if request.owned_by_platform
                    else None,
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
    request: AlertDeliveryRequest, announced: EvaluationAnnouncement
) -> tuple[EvaluationAnnouncement, tuple[LegacyEventEmission, ...]]:
    """The transitions HogFunction destinations receive natively, and the ones the source emits for them.

    Only an alert the platform owns can take the HogFunction path. While the source owns it, its
    own stack emits those events, and emitting them here too would send every message twice.

    A transition inside a firing takes the path its firing took first, so a firing and its resolve
    never split across paths. Any other transition takes the path its destinations allow now.
    """
    if not request.owned_by_platform or delivery_paths.emitter_for(request.source) is None:
        return announced, ()

    # Read once per delivery, because the chooser reads every destination of the alert.
    @cache
    def choose() -> DeliveryPath:
        return delivery_paths.choose_path(
            source=request.source,
            team_id=request.team_id,
            alert_id=request.destination_alert_id,
            allowed_event_ids=[*request.event_ids_by_kind.values(), *request.event_ids_by_incident_action.values()],
        )

    native: list[AnnouncedTransition] = []
    emissions: list[LegacyEventEmission] = []
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
        if path == DeliveryPath.NATIVE:
            native.append(transition)
            continue
        subscribed = _subscribed_events(request, transition)
        if subscribed.message_event or subscribed.incident_event:
            emissions.append(
                LegacyEventEmission(
                    transition=transition,
                    sends_message=subscribed.message_event is not None,
                    incident_action=subscribed.incident_action if subscribed.incident_event else None,
                )
            )
    return replace(announced, transitions=tuple(native)), tuple(emissions)


def _overflow_notice_keys(request: AlertDeliveryRequest, kinds: dict[str, AlertEventKind]) -> dict[str, str]:
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
        for subscribed_destination in _destinations(request, event_id):
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
    # The HogFunction that subscribed this destination to the event, which its sends are recorded under.
    id: str | None
    data: AlertDestinationData
    # Whether the destination hears the events the source emits for its HogFunctions.
    receives_emitted_events: bool


def _destinations(request: AlertDeliveryRequest, event_id: str) -> list[_SubscribedDestination]:
    """Who subscribed to this event, resolved now rather than pinned when the check ran.

    A destination removed between the check and the send is not sent to, which a pinned set
    would get wrong.
    """
    groups = list_alert_destination_groups(
        team_id=request.team_id,
        alert_id=request.destination_alert_id,
        allowed_event_ids=[event_id],
    )
    return [
        _SubscribedDestination(
            id=str(min(group.hog_function_ids)) if group.hog_function_ids else None,
            data=group.data,
            receives_emitted_events=group.receives_emitted_events,
        )
        for group in groups
        if group.fully_enabled
    ]
