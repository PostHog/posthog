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

from products.alerts_platform.backend.facade.contracts import (
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
from products.alerts_platform.backend.logic.alert_routes import routed_receivers, routing_is_enabled
from products.alerts_platform.backend.models import (
    AlertDestination,
    AlertReceiver,
    PlatformAlert,
    PlatformAlertConfiguration,
)

logger = structlog.get_logger(__name__)

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
class _Watched:
    configuration_id: UUID
    # Grouping key to firing start, for every group firing when the snapshot was taken.
    firing: dict[str, datetime]
    endpoints: dict[str, _Endpoint]


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
    routing = team is not None and routing_is_enabled(team)
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
                firing=firing[configuration.id],
                endpoints=_endpoints(configuration, routing=routing),
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
            key: started
            for key, started in now_firing[watched.configuration_id].items()
            if watched.firing.get(key) == started
        }
        if firing:
            _schedule(configuration, firing, watched.endpoints, _endpoints(configuration, routing=before.routing))


def _schedule(
    configuration: PlatformAlertConfiguration,
    firing: Mapping[str, datetime],
    before: Mapping[str, _Endpoint],
    after: Mapping[str, _Endpoint],
) -> None:
    queued: list[HandoffSend] = []
    # Resolves for an incident manager whose row is gone or now sends elsewhere. Its old settings exist only
    # here, so they are sent from this process rather than put on a workflow's payload.
    inline: list[tuple[HandoffSend, AlertDestinationData]] = []
    for address, endpoint in after.items():
        if address not in before:
            queued.extend(_sends(endpoint, firing, gained=True))
    for address, endpoint in before.items():
        if address in after:
            continue
        sends = _sends(endpoint, firing, gained=False)
        if _still_sends_there(configuration, endpoint, address):
            queued.extend(sends)
        else:
            inline.extend((send, endpoint.data) for send in sends)
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
        deliver,
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
    if queued:
        deliver(_with_sends(request, queued))


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


def _sends(endpoint: _Endpoint, firing: Mapping[str, datetime], *, gained: bool) -> list[HandoffSend]:
    return [
        HandoffSend(
            grouping_key=grouping_key,
            episode_started_at=started_at,
            destination_id=endpoint.destination_id,
            routed=endpoint.routed,
            gained=gained,
        )
        for grouping_key, started_at in firing.items()
    ]


def _endpoints(configuration: PlatformAlertConfiguration, *, routing: bool) -> dict[str, _Endpoint]:
    """The incident managers a firing of this configuration is sent to. Each hears every trigger and
    resolve, whatever kinds it lists."""
    found: dict[str, _Endpoint] = {}
    if configuration.destinations_owner == PlatformAlertOwner.PLATFORM:
        for destination in enabled_alert_destinations(team_id=configuration.team_id, configuration_id=configuration.id):
            if destination.data.get("type") in INCIDENT_DESTINATION_TYPES:
                found.setdefault(
                    _address(destination.data),
                    _Endpoint(destination_id=str(destination.id), routed=False, data=destination.data),
                )
    if routing:
        for receiver in routed_receivers(team_id=configuration.team_id, labels=configuration.labels or {}):
            if receiver.data.get("type") in INCIDENT_DESTINATION_TYPES:
                found.setdefault(
                    _address(receiver.data), _Endpoint(destination_id=str(receiver.id), routed=True, data=receiver.data)
                )
    return found


def _address(data: AlertDestinationData) -> str:
    fields = _ADDRESS_FIELDS.get(cast(DestinationType, data.get("type")), ())
    kept = {key: value for key, value in data.items() if key in fields}
    return json.dumps({**kept, "type": data.get("type")}, sort_keys=True, default=str)


def _still_sends_there(configuration: PlatformAlertConfiguration, endpoint: _Endpoint, address: str) -> bool:
    """Whether the destination's row will still hold this address when the delivery reads it by id."""
    rows = (
        AlertReceiver.objects.for_team(configuration.team_id).filter(id=endpoint.destination_id)
        if endpoint.routed
        else AlertDestination.objects.for_team(configuration.team_id).filter(
            id=endpoint.destination_id, configuration_id=configuration.id
        )
    )
    config = rows.values_list("config", flat=True).first()
    return config is not None and _address(cast(AlertDestinationData, config)) == address


def _firing_groups(team_id: int, configuration_ids: Collection[UUID] | None) -> dict[UUID, dict[str, datetime]]:
    rows = PlatformAlert.objects.for_team(team_id).filter(
        state=PlatformAlertState.FIRING, firing_started_at__isnull=False
    )
    if configuration_ids is not None:
        rows = rows.filter(configuration_id__in=configuration_ids)
    firing: dict[UUID, dict[str, datetime]] = {}
    for configuration_id, grouping_key, started_at in rows.values_list(
        "configuration_id", "grouping_key", "firing_started_at"
    ):
        firing.setdefault(configuration_id, {})[grouping_key] = started_at
    return firing
