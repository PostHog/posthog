"""The destinations of an alert whose `destinations_owner` is the platform.

The one write path for `AlertDestination`. Each source's alert page and the central page call it
through the facade, so a destination is valid or refused the same way wherever it is edited.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from typing import Final, cast
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
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.alerts_platform.backend.models import AlertDestination, PlatformAlertConfiguration

# The destination types that open and close incidents rather than post messages.
INCIDENT_DESTINATION_TYPES: Final = frozenset({DestinationType.PAGERDUTY})

_REQUIRED_FIELDS: Final[dict[DestinationType, tuple[str, ...]]] = {
    DestinationType.SLACK: ("slack_workspace_id", "slack_channel_id"),
    DestinationType.WEBHOOK: ("webhook_url",),
    DestinationType.TEAMS: ("webhook_url",),
    DestinationType.DISCORD: ("webhook_url",),
    DestinationType.PAGERDUTY: ("pagerduty_routing_key",),
    DestinationType.EMAIL: ("email_addresses",),
    DestinationType.IN_APP: ("in_app_user_ids",),
}


def _is_text(value: object) -> bool:
    return isinstance(value, str)


def _is_id(value: object) -> bool:
    # A bool is an int in Python, but never a valid id.
    return isinstance(value, int) and not isinstance(value, bool)


def _is_list_of(check: Callable[[object], bool]) -> Callable[[object], bool]:
    return lambda value: isinstance(value, list) and all(check(item) for item in value)


_FIELD_CHECKS: Final[dict[str, Callable[[object], bool]]] = {
    "slack_workspace_id": _is_id,
    "slack_channel_id": _is_text,
    "webhook_url": _is_text,
    "pagerduty_routing_key": _is_text,
    "email_addresses": _is_list_of(_is_text),
    "in_app_user_ids": _is_list_of(_is_id),
}

# A label a person sees. Two destinations that differ only here send to the same place.
_DISPLAY_ONLY_FIELDS: Final = frozenset({"slack_channel_name"})


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
        # Delivery reads these rows only for such an alert. On any other, they would never send.
        if configuration.destinations_owner != PlatformAlertOwner.PLATFORM:
            raise AlertDestinationValidationError("This alert's destinations are managed by its product.")
        _refuse_duplicates(team_id, configuration_id, destinations)
        rows = [
            AlertDestination.objects.for_team(team_id).create(
                team_id=team_id,
                configuration=configuration,
                type=destination.data["type"],
                config=dict(destination.data),
                event_kinds=[kind.value for kind in destination.event_kinds],
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


def enabled_alert_destinations(*, team_id: int, configuration_id: UUID) -> tuple[StoredAlertDestination, ...]:
    """The destinations delivery sends to. A disabled one is left out before its address is decrypted."""
    return tuple(
        _stored(row)
        for row in AlertDestination.objects.for_team(team_id)
        .filter(configuration_id=configuration_id, enabled=True)
        .order_by("created_at", "id")
    )


def has_incident_destination(*, team_id: int, configuration_id: UUID) -> bool:
    """Whether the alert has an enabled incident manager, so that a firing that opens or closes needs a delivery."""
    return (
        AlertDestination.objects.for_team(team_id)
        .filter(configuration_id=configuration_id, type__in=INCIDENT_DESTINATION_TYPES, enabled=True)
        .exists()
    )


def _refuse_duplicates(team_id: int, configuration_id: UUID, destinations: Sequence[NewAlertDestination]) -> None:
    """A second destination with the same address would send every message twice."""
    seen = [
        _receiver(stored.data) for stored in list_alert_destinations(team_id=team_id, configuration_id=configuration_id)
    ]
    for destination in destinations:
        receiver = _receiver(destination.data)
        if receiver in seen:
            raise AlertDestinationValidationError("This alert already sends to this destination.", field="config")
        seen.append(receiver)


def _receiver(data: AlertDestinationData) -> dict[str, object]:
    """What decides where and how a destination sends, without the fields that only label it."""
    return {key: value for key, value in data.items() if key not in _DISPLAY_ONLY_FIELDS}


def _validate(destination: NewAlertDestination) -> None:
    destination_type = destination.data.get("type")
    if destination_type not in DestinationType.values:
        raise AlertDestinationValidationError("This destination type is not supported.", field="type")
    required = _REQUIRED_FIELDS[DestinationType(destination_type)]
    missing = [key for key in required if not destination.data.get(key)]
    if missing:
        raise AlertDestinationValidationError(f"This destination needs {', '.join(missing)}.", field="config")
    malformed = [key for key in required if not _FIELD_CHECKS[key](destination.data.get(key))]
    if malformed:
        raise AlertDestinationValidationError(
            f"This destination has an invalid {', '.join(malformed)}.", field="config"
        )
    if not destination.event_kinds:
        raise AlertDestinationValidationError("Choose at least one event to send.", field="event_kinds")
    if not set(destination.event_kinds) <= DESTINATION_EVENT_KINDS:
        raise AlertDestinationValidationError("A destination cannot send about this event.", field="event_kinds")
    refusal = refused_destination(destination.data)
    if refusal is not None:
        raise AlertDestinationValidationError(refusal, field="config")


def _stored(row: AlertDestination) -> StoredAlertDestination:
    return StoredAlertDestination(
        id=row.id,
        configuration_id=row.configuration_id,
        data=cast(AlertDestinationData, row.config),
        event_kinds=tuple(AlertEventKind(kind) for kind in row.event_kinds),
        enabled=row.enabled,
        consecutive_failures=row.consecutive_failures,
        legacy_hog_function_ids=tuple(row.legacy_hog_function_ids),
    )
