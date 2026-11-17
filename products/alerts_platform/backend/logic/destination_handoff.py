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
from products.alerts_platform.backend.logic.alert_destinations import (
    INCIDENT_DESTINATION_TYPES,
    enabled_alert_destinations,
)
from products.alerts_platform.backend.logic.alert_routes import (
    routed_receivers_for_label_sets,
    routing_labels,
    stored_group_labels,
)
from products.alerts_platform.backend.models import PlatformAlert, PlatformAlertConfiguration

logger = structlog.get_logger(__name__)

# Sends run one after another in a delivery activity, which has `DELIVERY_START_TO_CLOSE` for all of them.
MAX_SENDS_PER_HANDOFF: Final = 10

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
    configurations = PlatformAlertConfiguration.objects.for_team(team_id).filter(
        id__in=firing, owner=PlatformAlertOwner.PLATFORM
    )
    return Snapshot(
        team_id=team_id,
        routing=routing,
        watched=tuple(
            _Watched(
                configuration_id=configuration.id,
                firing={key: group.started_at for key, group in firing[configuration.id].items()},
                endpoints=_endpoints(
                    configuration,
                    {key: group.labels for key, group in firing[configuration.id].items()},
                    routing=routing,
                ),
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
    for watched in before.watched:
        configuration = configurations.get(watched.configuration_id)
        if configuration is None:
            continue
        # Only a firing that runs on through the edit. One the edit ended was closed by the edit.
        firing = {
            key: group
            for key, group in now_firing[watched.configuration_id].items()
            if watched.firing.get(key) == group.started_at
        }
        if firing:
            _schedule(
                configuration,
                firing,
                watched.endpoints,
                _endpoints(configuration, {key: group.labels for key, group in firing.items()}, routing=before.routing),
            )


def _schedule(
    configuration: PlatformAlertConfiguration,
    firing: Mapping[str, _Group],
    before: Mapping[str, Mapping[str, _Endpoint]],
    after: Mapping[str, Mapping[str, _Endpoint]],
) -> None:
    queued: list[HandoffSend] = []
    # Resolves go from this process with the settings read before the edit. A later edit can delete or
    # repoint the row before a workflow would read it by id, and nothing else knows the incident is open.
    # The settings carry a credential, so they never go on a workflow's payload.
    inline: list[tuple[HandoffSend, AlertDestinationData]] = []
    for key, group in firing.items():
        was, now = before.get(key, {}), after.get(key, {})
        for where, endpoint in now.items():
            if where not in was:
                queued.append(_send_for(endpoint, key, group.started_at, gained=True))
        for where, endpoint in was.items():
            if where not in now:
                inline.append((_send_for(endpoint, key, group.started_at, gained=False), endpoint.data))
    if not queued and not inline:
        return
    request = _request(configuration, queued or [send for send, _ in inline])
    gained = sum(send.gained for send in queued)
    logger.info(
        "alerts_platform_handoff_scheduled",
        configuration_id=str(configuration.id),
        gained=gained,
        lost=len(queued) + len(inline) - gained,
    )
    transaction.on_commit(lambda: _send(request, queued, inline), robust=True)


def _send(
    request: AlertDeliveryRequest,
    queued: list[HandoffSend],
    inline: list[tuple[HandoffSend, AlertDestinationData]],
) -> None:
    # Imported here because this module loads in processes that never send, and the sender loads the
    # Temporal client and every transport.
    from products.alerts_platform.backend.delivery.handoff import (  # noqa: PLC0415 - keeps Temporal and the transports off the import path
        HandoffTarget,
        send_handoff,
    )
    from products.alerts_platform.backend.temporal.web_start import (  # noqa: PLC0415 - keeps Temporal and the transports off the import path
        hand_over,
    )

    if inline:
        try:
            send_handoff(
                _with_sends(request, [send for send, _ in inline]),
                [HandoffTarget(send=send, data=data) for send, data in inline],
            )
        except Exception as error:
            # The edit stands. A resolve that failed leaves the incident open, which error tracking shows.
            capture_exception(error, {"configuration_id": request.configuration_id})
    # In parts, so each fits one delivery attempt's deadline and the payload stays small however many
    # groups and receivers an edit moves.
    for start in range(0, len(queued), MAX_SENDS_PER_HANDOFF):
        part = replace(request, evaluation_key=f"{request.evaluation_key}:{start // MAX_SENDS_PER_HANDOFF}")
        hand_over(_with_sends(part, queued[start : start + MAX_SENDS_PER_HANDOFF]))


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
    """The incident managers each group's firing is sent to. Each hears every trigger and resolve,
    whatever kinds it lists. The alert's own destinations hear every group, and a routed receiver
    hears the groups whose labels, with the rule's on top, its routes match."""
    own: dict[str, _Endpoint] = {}
    if configuration.destinations_owner == PlatformAlertOwner.PLATFORM:
        for destination in enabled_alert_destinations(team_id=configuration.team_id, configuration_id=configuration.id):
            if destination.data.get("type") in INCIDENT_DESTINATION_TYPES:
                own.setdefault(
                    address(destination.data),
                    _Endpoint(destination_id=str(destination.id), routed=False, data=destination.data),
                )
    keys = list(group_labels)
    routed = (
        routed_receivers_for_label_sets(
            team_id=configuration.team_id,
            label_sets=[
                routing_labels(group_labels=group_labels[key], rule_labels=configuration.labels or {}) for key in keys
            ],
        )
        if routing and keys
        else [() for _ in keys]
    )
    found: dict[str, dict[str, _Endpoint]] = {}
    for key, receivers in zip(keys, routed):
        endpoints = dict(own)
        for receiver in receivers:
            if receiver.data.get("type") in INCIDENT_DESTINATION_TYPES:
                endpoints.setdefault(
                    address(receiver.data), _Endpoint(destination_id=str(receiver.id), routed=True, data=receiver.data)
                )
        found[key] = endpoints
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
