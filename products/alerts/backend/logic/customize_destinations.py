"""Customize and reset a source alert's stock destination.

A destination sends exactly once at any moment: from its `AlertDestination` row with the standard
message, or from its HogFunctions with the message someone can edit. Each move swaps one for the
other in one transaction.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import replace
from typing import cast
from uuid import UUID

from django.db import transaction

from products.alerts.backend.facade.contracts import CustomizableDestination, ResetDestination
from products.alerts.backend.logic.destinations import (
    create_alert_destination_hog_functions,
    list_alert_destination_groups,
    soft_delete_alert_destinations,
)
from products.alerts_platform.backend.facade.api import (
    list_source_destinations,
    restore_source_destination,
    take_source_destination_row,
)
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationConfig,
    AlertDestinationData,
    AlertDestinationValidationError,
    AlertEventKind,
    DestinationType,
    SourceDestination,
)

_GONE = "This destination has changed since the page loaded. Refresh the alert and try again."


def customize_source_destination(
    *,
    team_id: int,
    alert_id: UUID,
    allowed_event_ids: Collection[str],
    allowed_destination_types: Collection[DestinationType],
    destination_id: UUID | None,
    hog_function_ids: Collection[UUID],
    build_configs: Callable[[AlertDestinationData], Sequence[AlertDestinationConfig]],
    created_by_id: int,
) -> CustomizableDestination:
    """Gives the destination HogFunctions to edit and removes its row.

    A row that copies HogFunctions which still exist was skipped by delivery, so they keep sending and
    nothing new is written. A row with none gets them built by `build_configs` from its stored settings."""
    with transaction.atomic():
        listed = _listed(
            team_id=team_id,
            alert_id=alert_id,
            allowed_event_ids=allowed_event_ids,
            destination_id=destination_id,
            hog_function_ids=hog_function_ids,
        )
        destination_type = DestinationType(listed.data["type"])
        if destination_type not in allowed_destination_types:
            raise AlertDestinationValidationError("This destination's message can't be customized.", field="type")
        taken = None
        if listed.destination_id is not None:
            taken = take_source_destination_row(
                team_id=team_id, public_id=alert_id, destination_id=listed.destination_id
            )
            if taken is None:
                raise AlertDestinationValidationError(_GONE)
        if listed.hog_function_ids:
            return CustomizableDestination(
                hog_function_ids=listed.hog_function_ids, destination_type=destination_type, created=False
            )
        assert taken is not None
        data = cast(AlertDestinationData, {**taken.data, "type": destination_type})
        configs = [
            replace(config, payload={**config.payload, "enabled": taken.enabled}) for config in build_configs(data)
        ]
        created = create_alert_destination_hog_functions(
            configs,
            team_id=team_id,
            created_by_id=created_by_id,
            alert_id=str(alert_id),
            allowed_event_ids=allowed_event_ids,
        )
    return CustomizableDestination(hog_function_ids=created, destination_type=destination_type, created=True)


def reset_source_destination(
    *,
    team_id: int,
    alert_id: UUID,
    allowed_event_ids: Collection[str],
    allowed_destination_types: Collection[DestinationType],
    hog_function_ids: Collection[UUID],
    row_event_kinds: Callable[[DestinationType], Collection[AlertEventKind]],
) -> ResetDestination:
    """Retires the destination's HogFunctions and adds a row that sends the standard message instead.

    The HogFunctions are retired with a queryset update, which the receiver that deletes copying rows
    never hears, and the new row copies none of them, so it outlives them either way."""
    with transaction.atomic():
        groups = list_alert_destination_groups(
            team_id=team_id, alert_id=str(alert_id), allowed_event_ids=allowed_event_ids
        )
        named = set(hog_function_ids)
        group = next((group for group in groups if set(group.hog_function_ids) == named), None)
        if not named or group is None:
            raise AlertDestinationValidationError(_GONE, field="hog_function_ids")
        destination_type = DestinationType(group.data["type"])
        if destination_type not in allowed_destination_types:
            raise AlertDestinationValidationError(
                "This destination has no standard message to go back to.", field="type"
            )
        soft_delete_alert_destinations(
            team_id=team_id,
            alert_id=str(alert_id),
            allowed_event_ids=allowed_event_ids,
            hog_function_ids=list(group.hog_function_ids),
        )
        row = restore_source_destination(
            team_id=team_id,
            public_id=alert_id,
            data=group.data,
            event_kinds=row_event_kinds(destination_type),
            enabled=group.fully_enabled,
            retired_hog_function_ids=group.hog_function_ids,
            hog_function_groups=groups,
        )
    return ResetDestination(
        destination_id=row.id, destination_type=destination_type, retired_hog_function_ids=group.hog_function_ids
    )


def _listed(
    *,
    team_id: int,
    alert_id: UUID,
    allowed_event_ids: Collection[str],
    destination_id: UUID | None,
    hog_function_ids: Collection[UUID],
) -> SourceDestination:
    listed = list_source_destinations(
        team_id=team_id,
        public_id=alert_id,
        hog_function_groups=list_alert_destination_groups(
            team_id=team_id, alert_id=str(alert_id), allowed_event_ids=allowed_event_ids
        ),
    )
    named = set(hog_function_ids)
    found = next(
        (
            destination
            for destination in listed
            if (destination_id is not None and destination.destination_id == destination_id)
            or (named and set(destination.hog_function_ids) == named)
        ),
        None,
    )
    if found is None:
        raise AlertDestinationValidationError(_GONE)
    return found
