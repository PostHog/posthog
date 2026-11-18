"""Hands firing groups over when an edit changes which destinations hear them.

Deliveries follow the current routes and destinations, so an edit made while a group fires moves it.
Only incident managers take part, since they hold state a firing opens and a resolve closes. One that
gains the firing hears the trigger now, so its later resolve has an incident to close. One that loses it
hears the resolve, so its incident does not stay open. A message destination hears nothing either way.

An edit takes a `snapshot` before it writes and calls `hand_over_after_commit` after, in the same
transaction. Destinations are compared by where they send, so a firing that moves from an alert's own
PagerDuty destination to a routed receiver with the same integration key moves nowhere.
"""

import json
import uuid
from collections.abc import Collection, Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from typing import Final, cast
from uuid import UUID

from django.db import transaction

import structlog

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models import Team

from products.alerts_platform.backend.delivery.destinations import copies_of_live_hog_functions
from products.alerts_platform.backend.delivery.team_flags import team_flag_enabled
from products.alerts_platform.backend.facade.contracts import (
    ROUTING_FLAG,
    AlertDeliveryRequest,
    AlertDestinationData,
    DestinationType,
    HandoffSend,
    NewAlertDestination,
    SourceKind,
    StoredAlertDestination,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner, PlatformAlertState
from products.alerts_platform.backend.logic import alert_destinations, source_configs
from products.alerts_platform.backend.logic.alert_destinations import INCIDENT_DESTINATION_TYPES
from products.alerts_platform.backend.logic.alert_routes import (
    routed_receivers_for_label_sets,
    routing_labels,
    stored_group_labels,
)
from products.alerts_platform.backend.models import (
    AlertDestination,
    AlertReceiver,
    PlatformAlert,
    PlatformAlertConfiguration,
)

logger = structlog.get_logger(__name__)

# Sends run one after another in a delivery activity, which has `DELIVERY_START_TO_CLOSE` for all of them.
MAX_SENDS_PER_HANDOFF: Final = 10
# Sends one edit makes from its own web request, so a large edit cannot hold a web worker for minutes.
# Resolves take them first. A handoff whose workflow cannot start takes what is left.
MAX_INLINE_SENDS_PER_EDIT: Final = 20


@frozen
class _InlineResolve:
    send: HandoffSend
    data: AlertDestinationData
    # Whether the destination's row still holds this address, so a workflow can read it by id.
    readable_by_id: bool


class _InlineBudget:
    """The inline sends an edit has left, shared by every configuration the edit touches."""

    def __init__(self) -> None:
        self.remaining = MAX_INLINE_SENDS_PER_EDIT


@frozen
class _Handoff:
    """What one configuration's firings are owed after an edit."""

    request: AlertDeliveryRequest
    queued: tuple[HandoffSend, ...]
    inline: tuple[_InlineResolve, ...]


# The fields that say which incident a send reaches. Two destinations that agree on them hold the same
# incident, whatever else differs, such as a PagerDuty severity or an incident.io secret.
_ADDRESS_FIELDS: Final[dict[DestinationType, tuple[str, ...]]] = {
    DestinationType.PAGERDUTY: ("pagerduty_routing_key",),
    DestinationType.INCIDENT_IO: ("incident_io_alert_source_config_id",),
}


@frozen
class _Endpoint:
    """One place a configuration's firings are sent, through the first destination that reaches it."""

    destination_id: str
    routed: bool
    data: AlertDestinationData


@frozen
class _Group:
    started_at: datetime
    # The group's own labels, which routing reads with the rule's labels on top.
    labels: dict[str, str]


@frozen
class _Watched:
    configuration_id: UUID
    # Grouping key to firing start, for every group firing when the snapshot was taken.
    firing: dict[str, datetime]
    # Grouping key to where that group's firing goes, by `address`. Each group routes on its own labels.
    endpoints: dict[str, dict[str, _Endpoint]]


@frozen
class Snapshot:
    team_id: int
    # Read once, so a flag that flips between the two reads cannot move every firing at once.
    routing: bool
    watched: tuple[_Watched, ...]


def snapshot(team_id: int, *, configuration_ids: Collection[UUID] | None = None, routes_only: bool = False) -> Snapshot:
    """Where the firing groups of these configurations are sent now, or of every configuration on the
    team when None. With `routes_only`, an edit that can move firings only between routed receivers
    skips the work when the team does not route."""
    team = Team.objects.filter(id=team_id).first()
    routing = team is not None and _routing_on(team)
    if team is None or (routes_only and not routing):
        return Snapshot(team_id=team_id, routing=routing, watched=())
    firing = _firing_groups(team_id, configuration_ids)
    if not firing:
        return Snapshot(team_id=team_id, routing=routing, watched=())
    configurations = list(
        PlatformAlertConfiguration.objects.for_team(team_id).filter(id__in=firing, owner=PlatformAlertOwner.PLATFORM)
    )
    endpoints = _endpoints_by_configuration(
        team_id,
        {
            configuration.id: (configuration, {key: group.labels for key, group in firing[configuration.id].items()})
            for configuration in configurations
        },
        routing=routing,
    )
    return Snapshot(
        team_id=team_id,
        routing=routing,
        watched=tuple(
            _Watched(
                configuration_id=configuration.id,
                firing={key: group.started_at for key, group in firing[configuration.id].items()},
                endpoints=endpoints[configuration.id],
            )
            for configuration in configurations
        ),
    )


def create_alert_destinations(
    *, team_id: int, configuration_id: UUID, destinations: Sequence[NewAlertDestination]
) -> tuple[StoredAlertDestination, ...]:
    """`alert_destinations.create_alert_destinations`, with a destination added while the alert fires
    hearing the firing. Kept apart from that module, which `alert_routes` imports."""
    with transaction.atomic():
        before = snapshot(team_id, configuration_ids=[configuration_id])
        created = alert_destinations.create_alert_destinations(
            team_id=team_id, configuration_id=configuration_id, destinations=destinations
        )
        hand_over_after_commit(before)
    return created


def delete_alert_destinations(
    *, team_id: int, configuration_id: UUID, destination_ids: Collection[UUID]
) -> dict[UUID, str]:
    """`alert_destinations.delete_alert_destinations`, with an incident manager deleted while the alert
    fires hearing the resolve."""
    with transaction.atomic():
        before = snapshot(team_id, configuration_ids=[configuration_id])
        deleted = alert_destinations.delete_alert_destinations(
            team_id=team_id, configuration_id=configuration_id, destination_ids=destination_ids
        )
        hand_over_after_commit(before)
    return deleted


def hand_over_after_commit(before: Snapshot) -> None:
    """Compares where the snapshot's firing groups are sent now with where they were, and sends what
    each destination is owed once the edit commits. Call it in the edit's transaction, after its write."""
    if not before.watched:
        return
    now_firing = _firing_groups(before.team_id, [watched.configuration_id for watched in before.watched])
    configurations = {
        configuration.id: configuration
        for configuration in PlatformAlertConfiguration.objects.for_team(before.team_id).filter(
            id__in=now_firing, owner=PlatformAlertOwner.PLATFORM
        )
    }
    # Only a firing that runs on through the edit. One the edit ended was closed by the edit.
    running: dict[UUID, dict[str, _Group]] = {}
    for watched in before.watched:
        if watched.configuration_id not in configurations:
            continue
        firing = {
            key: group
            for key, group in now_firing[watched.configuration_id].items()
            if watched.firing.get(key) == group.started_at
        }
        if firing:
            running[watched.configuration_id] = firing
    after = _endpoints_by_configuration(
        before.team_id,
        {
            configuration_id: (configurations[configuration_id], {key: group.labels for key, group in firing.items()})
            for configuration_id, firing in running.items()
        },
        routing=before.routing,
    )
    budget = _InlineBudget()
    endpoints_before = {watched.configuration_id: watched.endpoints for watched in before.watched}
    handoffs = [
        handoff
        for configuration_id, still_firing in running.items()
        if (
            handoff := _schedule(
                configurations[configuration_id],
                still_firing,
                endpoints_before[configuration_id],
                after[configuration_id],
                budget,
            )
        )
        is not None
    ]
    if handoffs:
        left = budget.remaining
        transaction.on_commit(lambda: _send(handoffs, inline_left=left), robust=True)


def _schedule(
    configuration: PlatformAlertConfiguration,
    firing: Mapping[str, _Group],
    before: Mapping[str, Mapping[str, _Endpoint]],
    after: Mapping[str, Mapping[str, _Endpoint]],
    budget: _InlineBudget,
) -> _Handoff | None:
    queued: list[HandoffSend] = []
    # Resolves go from this process with the settings read before the edit, up to the edit's budget. A
    # later edit can delete or repoint the row before a workflow would read it by id, and the settings
    # carry a credential, so they never go on a workflow's payload. Past the budget, a resolve goes
    # through the workflow by id, which a row deleted in that window loses.
    inline: list[_InlineResolve] = []
    stranded = 0
    lost: list[tuple[HandoffSend, _Endpoint, str]] = []
    for key, group in firing.items():
        was, now = before.get(key, {}), after.get(key, {})
        for where, endpoint in now.items():
            if where not in was:
                queued.append(_send_for(endpoint, key, group.started_at, gained=True))
        for where, endpoint in was.items():
            if where not in now:
                lost.append((_send_for(endpoint, key, group.started_at, gained=False), endpoint, where))
    held = _addresses_held(configuration, [endpoint for _, endpoint, _ in lost])
    # A destination this edit deleted or repointed has no other path, so it takes the inline sends first.
    for send, endpoint, still_there in sorted(
        (
            (send, endpoint, held.get((endpoint.routed, endpoint.destination_id)) == where)
            for send, endpoint, where in lost
        ),
        key=lambda item: item[2],
    ):
        if budget.remaining > 0:
            budget.remaining -= 1
            inline.append(_InlineResolve(send=send, data=endpoint.data, readable_by_id=still_there))
        elif still_there:
            queued.append(send)
        else:
            stranded += 1
    if stranded:
        logger.warning(
            "alerts_platform_handoff_resolves_dropped", configuration_id=str(configuration.id), dropped=stranded
        )
    if not queued and not inline:
        return None
    request = _request(configuration, queued or [resolve.send for resolve in inline])
    gained = sum(send.gained for send in queued)
    logger.info(
        "alerts_platform_handoff_scheduled",
        configuration_id=str(configuration.id),
        gained=gained,
        lost=len(queued) + len(inline) - gained,
    )
    return _Handoff(request=request, queued=tuple(queued), inline=tuple(inline))


def _send(handoffs: list[_Handoff], *, inline_left: int) -> None:
    # Imported here because this module loads in processes that never send, and the sender loads the
    # Temporal client and every transport.
    from products.alerts_platform.backend.delivery.handoff import (  # noqa: PLC0415 - keeps Temporal and the transports off the import path
        HandoffTarget,
        send_handoff,
    )
    from products.alerts_platform.backend.temporal.web_start import (  # noqa: PLC0415 - keeps Temporal and the transports off the import path
        hand_over_inline,
        start_hand_overs,
    )

    # Started first, so the inline sends below never hold back a new destination's page.
    unstarted = start_hand_overs([part for handoff in handoffs for part in _parts(handoff.request, handoff.queued)])
    for request in unstarted:
        sends = request.handoff[: max(inline_left, 0)]
        inline_left -= len(sends)
        if sends:
            hand_over_inline(_with_sends(request, list(sends)))
        _log_dropped(request, len(request.handoff) - len(sends))
    retries: list[AlertDeliveryRequest] = []
    for handoff in handoffs:
        if not handoff.inline:
            continue
        inline_request = _with_sends(handoff.request, [resolve.send for resolve in handoff.inline])
        try:
            send_handoff(
                inline_request, [HandoffTarget(send=resolve.send, data=resolve.data) for resolve in handoff.inline]
            )
        except Exception as error:
            capture_exception(error, {"configuration_id": inline_request.configuration_id})
            # A held thread or a provider error gets the workflow's retries where the row still holds this
            # destination. Under the same evaluation key, the thread claims skip the resolves that did land.
            retry = [resolve.send for resolve in handoff.inline if resolve.readable_by_id]
            if retry:
                retries.append(_with_sends(inline_request, retry))
    # Not sent inline again: this edit already tried them, and its budget is spent.
    for request in start_hand_overs(retries):
        _log_dropped(request, len(request.handoff))


def _log_dropped(request: AlertDeliveryRequest, dropped: int) -> None:
    if dropped:
        logger.warning(
            "alerts_platform_handoff_sends_dropped", configuration_id=request.configuration_id, dropped=dropped
        )


def _parts(request: AlertDeliveryRequest, sends: Sequence[HandoffSend]) -> list[AlertDeliveryRequest]:
    # In parts, so each fits one delivery attempt's deadline and the payload stays small however many
    # groups and receivers an edit moves. Each part has its own key, so each gets its own workflow.
    return [
        _with_sends(
            replace(request, evaluation_key=f"{request.evaluation_key}:{start // MAX_SENDS_PER_HANDOFF}"),
            list(sends[start : start + MAX_SENDS_PER_HANDOFF]),
        )
        for start in range(0, len(sends), MAX_SENDS_PER_HANDOFF)
    ]


def _with_sends(request: AlertDeliveryRequest, sends: list[HandoffSend]) -> AlertDeliveryRequest:
    return replace(request, handoff=tuple(sends))


def _request(configuration: PlatformAlertConfiguration, sends: list[HandoffSend]) -> AlertDeliveryRequest:
    source = SourceKind(configuration.source_kind)
    spec = source_configs.spec(source)
    return AlertDeliveryRequest(
        source=source,
        team_id=configuration.team_id,
        configuration_id=str(configuration.id),
        # Unique per edit: the delivery workflow's id and every thread claim are keyed on it.
        evaluation_key=f"handoff:{uuid.uuid4().hex}",
        destination_alert_id=str(configuration.destination_alert_id),
        event_ids_by_kind={},
        source_alert_url=spec.alert_url(configuration.team_id, configuration.destination_alert_id)
        if spec is not None and spec.alert_url
        else None,
        owned_by_platform=True,
        handoff=tuple(sends),
    )


def current_addresses(
    team_id: int, configuration_id: str, grouping_keys: Collection[str]
) -> dict[str, frozenset[str]] | None:
    """Where each of these groups' firings go now, by `address`, for a send to check it is still owed.
    None when the routing flag cannot be read, which would otherwise read as no routed receivers."""
    team = Team.objects.filter(id=team_id).first()
    configuration = (
        PlatformAlertConfiguration.objects.for_team(team_id)
        .filter(id=configuration_id, owner=PlatformAlertOwner.PLATFORM)
        .first()
    )
    if team is None or configuration is None:
        return {}
    try:
        routing = team_flag_enabled(ROUTING_FLAG, team)
    except Exception:
        logger.warning("alerts_platform_handoff_routing_flag_unreadable", team_id=team_id, exc_info=True)
        return None
    if routing is None:
        return None
    labels = stored_group_labels(team_id=team_id, configuration_id=configuration_id, grouping_keys=grouping_keys)
    group_labels = {key: labels.get(key, {}) for key in grouping_keys}
    return {key: frozenset(found) for key, found in _endpoints(configuration, group_labels, routing=routing).items()}


def _send_for(endpoint: _Endpoint, grouping_key: str, started_at: datetime, *, gained: bool) -> HandoffSend:
    return HandoffSend(
        grouping_key=grouping_key,
        episode_started_at=started_at,
        destination_id=endpoint.destination_id,
        routed=endpoint.routed,
        gained=gained,
    )


def _endpoints(
    configuration: PlatformAlertConfiguration, group_labels: Mapping[str, Mapping[str, str]], *, routing: bool
) -> dict[str, dict[str, _Endpoint]]:
    return _endpoints_by_configuration(
        configuration.team_id, {configuration.id: (configuration, group_labels)}, routing=routing
    )[configuration.id]


def _endpoints_by_configuration(
    team_id: int,
    groups: Mapping[UUID, tuple[PlatformAlertConfiguration, Mapping[str, Mapping[str, str]]]],
    *,
    routing: bool,
) -> dict[UUID, dict[str, dict[str, _Endpoint]]]:
    """The incident managers each group's firing is sent to, by configuration and grouping key. Each
    hears every trigger and resolve, whatever kinds it lists. An alert's own destinations hear every
    group, and a routed receiver hears the groups whose labels, with the rule's on top, its routes match.

    Reads the configurations' own destinations in one query and the team's routes once, however many
    configurations an edit touches."""
    own: dict[UUID, dict[str, _Endpoint]] = {configuration_id: {} for configuration_id in groups}
    rows = list(
        AlertDestination.objects.for_team(team_id)
        .filter(configuration_id__in=list(groups), enabled=True, type__in=INCIDENT_DESTINATION_TYPES)
        .order_by("created_at", "id")
        .values_list("id", "configuration_id", "config", "legacy_hog_function_ids")
    )
    # A row that copies a live HogFunction does not send, as in delivery, so the HogFunction keeps the firing.
    copies = copies_of_live_hog_functions(
        team_id=team_id, copied_by_row={destination_id: copied for destination_id, *_, copied in rows}
    )
    for destination_id, configuration_id, config, _ in rows:
        if destination_id not in copies:
            data = cast(AlertDestinationData, config)
            own[configuration_id].setdefault(
                address(data), _Endpoint(destination_id=str(destination_id), routed=False, data=data)
            )
    keys = [(configuration_id, key) for configuration_id, (_, group_labels) in groups.items() for key in group_labels]
    routed = (
        routed_receivers_for_label_sets(
            team_id=team_id,
            label_sets=[
                routing_labels(
                    group_labels=groups[configuration_id][1][key],
                    rule_labels=groups[configuration_id][0].labels or {},
                )
                for configuration_id, key in keys
            ],
        )
        if routing and keys
        else [() for _ in keys]
    )
    found: dict[UUID, dict[str, dict[str, _Endpoint]]] = {configuration_id: {} for configuration_id in groups}
    for (configuration_id, key), receivers in zip(keys, routed):
        endpoints = dict(own[configuration_id])
        for receiver in receivers:
            if receiver.data.get("type") in INCIDENT_DESTINATION_TYPES:
                endpoints.setdefault(
                    address(receiver.data), _Endpoint(destination_id=str(receiver.id), routed=True, data=receiver.data)
                )
        found[configuration_id][key] = endpoints
    return found


def _routing_on(team: Team) -> bool:
    """Fails closed. The snapshot and the comparison after the edit share this one read."""
    try:
        return bool(team_flag_enabled(ROUTING_FLAG, team))
    except Exception:
        logger.warning("alerts_platform_handoff_routing_flag_unreadable", team_id=team.id, exc_info=True)
        return False


def address(data: AlertDestinationData) -> str:
    fields = _ADDRESS_FIELDS.get(cast(DestinationType, data.get("type")), ())
    kept = {key: value for key, value in data.items() if key in fields}
    return json.dumps({**kept, "type": data.get("type")}, sort_keys=True, default=str)


def _firing_groups(team_id: int, configuration_ids: Collection[UUID] | None) -> dict[UUID, dict[str, _Group]]:
    rows = PlatformAlert.objects.for_team(team_id).filter(
        state=PlatformAlertState.FIRING, firing_started_at__isnull=False
    )
    if configuration_ids is not None:
        rows = rows.filter(configuration_id__in=configuration_ids)
    firing: dict[UUID, dict[str, _Group]] = {}
    for configuration_id, grouping_key, started_at, labels in rows.values_list(
        "configuration_id", "grouping_key", "firing_started_at", "labels"
    ):
        # Never None: the filter above leaves those rows out.
        if started_at is not None:
            firing.setdefault(configuration_id, {})[grouping_key] = _Group(
                started_at=started_at, labels=dict(labels or {})
            )
    return firing


def _addresses_held(
    configuration: PlatformAlertConfiguration, endpoints: Collection[_Endpoint]
) -> dict[tuple[bool, str], str]:
    """Where each destination's row sends now, by (routed, id), for a workflow to read it by id. One read
    per kind, however many groups an edit moves."""
    routed = {endpoint.destination_id for endpoint in endpoints if endpoint.routed}
    own = {endpoint.destination_id for endpoint in endpoints if not endpoint.routed}
    held: dict[tuple[bool, str], str] = {}
    if routed:
        for destination_id, config in (
            AlertReceiver.objects.for_team(configuration.team_id).filter(id__in=routed).values_list("id", "config")
        ):
            held[(True, str(destination_id))] = address(cast(AlertDestinationData, config))
    if own:
        for destination_id, config in (
            AlertDestination.objects.for_team(configuration.team_id)
            .filter(id__in=own, configuration_id=configuration.id)
            .values_list("id", "config")
        ):
            held[(False, str(destination_id))] = address(cast(AlertDestinationData, config))
    return held
