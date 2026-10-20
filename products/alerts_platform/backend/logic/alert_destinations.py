"""The destinations of an alert whose `destinations_owner` is the platform.

The one write path for `AlertDestination`. Each source's alert page and the central page call it
through the facade, so a destination is valid or refused the same way wherever it is edited.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import cast
from uuid import UUID

from django.db import transaction

from products.alerts_platform.backend.delivery.addresses import refused_destination
from products.alerts_platform.backend.facade.contracts import (
    DESTINATION_EVENT_KINDS,
    AlertDestinationData,
    AlertDestinationValidationError,
    AlertEventKind,
    DestinationType,
    NewAlertDestination,
    StoredAlertDestination,
)
from products.alerts_platform.backend.facade.enums import AlertDestinationDelivery
from products.alerts_platform.backend.models import AlertDestination, PlatformAlertConfiguration


def create_alert_destinations(
    *, team_id: int, configuration_id: UUID, destinations: Sequence[NewAlertDestination]
) -> tuple[StoredAlertDestination, ...]:
    """Adds the destinations to one configuration, all or none."""
    for destination in destinations:
        _validate(destination)
    with transaction.atomic():
        # Locked, so two adds of the same destination cannot both pass the duplicate check.
        configuration = (
            PlatformAlertConfiguration.objects.for_team(team_id).select_for_update().get(id=configuration_id)
        )
        _refuse_duplicates(team_id, configuration_id, destinations)
        rows = [
            AlertDestination.objects.for_team(team_id).create(
                team_id=team_id,
                configuration=configuration,
                type=destination.data["type"],
                delivery=destination.delivery,
                config=dict(destination.data),
                event_kinds=[kind.value for kind in destination.event_kinds],
                hog_flow_id=destination.hog_flow_id,
                enabled=destination.enabled,
                legacy_hog_function_ids=list(destination.legacy_hog_function_ids),
            )
            for destination in destinations
        ]
    return tuple(_stored(row) for row in rows)


def list_alert_destinations(*, team_id: int, configuration_id: UUID) -> tuple[StoredAlertDestination, ...]:
    return tuple(
        _stored(row)
        for row in AlertDestination.objects.for_team(team_id)
        .filter(configuration_id=configuration_id)
        .order_by("created_at", "id")
    )


def delete_alert_destinations(*, team_id: int, configuration_id: UUID, destination_ids: Collection[UUID]) -> int:
    """Deletes the named destinations of one configuration, and returns how many it deleted.

    An id of another configuration is left alone, so a caller cannot reach past the alert it checked access to.
    """
    deleted, _ = (
        AlertDestination.objects.for_team(team_id)
        .filter(configuration_id=configuration_id, id__in=destination_ids)
        .delete()
    )
    return deleted


def _refuse_duplicates(team_id: int, configuration_id: UUID, destinations: Sequence[NewAlertDestination]) -> None:
    """A second destination with the same address would send every message twice."""
    seen = [stored.data for stored in list_alert_destinations(team_id=team_id, configuration_id=configuration_id)]
    for destination in destinations:
        if destination.data in seen:
            raise AlertDestinationValidationError("This alert already sends to this destination.", field="config")
        seen.append(destination.data)


def _validate(destination: NewAlertDestination) -> None:
    if destination.data.get("type") not in DestinationType.values:
        raise AlertDestinationValidationError("This destination type is not supported.", field="type")
    if not destination.event_kinds:
        raise AlertDestinationValidationError("Choose at least one event to send.", field="event_kinds")
    if not set(destination.event_kinds) <= DESTINATION_EVENT_KINDS:
        raise AlertDestinationValidationError("A destination cannot send about this event.", field="event_kinds")
    if destination.delivery == AlertDestinationDelivery.WORKFLOW:
        if destination.hog_flow_id is None:
            raise AlertDestinationValidationError("A workflow destination needs its workflow.", field="hog_flow_id")
        return
    if destination.hog_flow_id is not None:
        raise AlertDestinationValidationError("Only a workflow destination has a workflow.", field="hog_flow_id")
    refusal = refused_destination(destination.data)
    if refusal is not None:
        raise AlertDestinationValidationError(refusal, field="config")


def _stored(row: AlertDestination) -> StoredAlertDestination:
    return StoredAlertDestination(
        id=row.id,
        configuration_id=row.configuration_id,
        data=cast(AlertDestinationData, row.config),
        event_kinds=tuple(AlertEventKind(kind) for kind in row.event_kinds),
        delivery=AlertDestinationDelivery(row.delivery),
        hog_flow_id=row.hog_flow_id,
        enabled=row.enabled,
        consecutive_failures=row.consecutive_failures,
        legacy_hog_function_ids=tuple(row.legacy_hog_function_ids),
    )
