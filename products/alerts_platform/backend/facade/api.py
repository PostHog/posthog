"""The shared alert tables, as a source adapter and this product's own API see them.

A source reads a batch of checks, reports what it decided, and can copy its own configurations
in. A reader asks for configurations and gets contracts. Neither ever holds one of these rows,
so every write and every scheduling rule has one home.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from datetime import datetime
from uuid import UUID

from products.alerts_platform.backend.facade.contracts import (
    HandbackRefusal,
    NewAlertDestination,
    PlatformAlertCheckInput,
    PlatformAlertConfigurationEdit,
    PlatformAlertConfigurationPage,
    PlatformAlertConfigurationView,
    PlatformAlertHistory,
    PlatformAlertOutcome,
    PlatformAlertRuntime,
    PlatformAlertUpsert,
    PlatformHandback,
    PlatformOwnershipHandover,
    SourceKind,
    StoredAlertDestination,
)
from products.alerts_platform.backend.logic import (
    alert_destinations,
    platform_lifecycle,
    platform_reads,
    platform_writes,
)


def due_checks(
    team_id: int, source_kind: str, slot: str, cutoff: datetime, *, configuration_ids: Collection[str] | None = None
) -> tuple[PlatformAlertCheckInput, ...]:
    """Every check one batch key owes, flattened as a source reads them, or only the named ones."""
    return platform_lifecycle.due_checks(team_id, source_kind, slot, cutoff, configuration_ids=configuration_ids)


def due_check_ids(
    team_id: int, source_kind: str, slot: str, cutoff: datetime, *, exclude: Collection[str] = (), limit: int
) -> tuple[str, ...]:
    """The first `limit` due ids of one batch key, skipping `exclude`, without their runtime state."""
    return platform_lifecycle.due_check_ids(team_id, source_kind, slot, cutoff, exclude=exclude, limit=limit)


def record_outcomes(team_id: int, outcomes: Sequence[PlatformAlertOutcome], now: datetime) -> int:
    """The platform's only write of state and schedule. Returns how many rows it wrote."""
    return platform_lifecycle.record_outcomes(team_id, outcomes, now)


def slot_of(next_check_at: datetime | None, cutoff: datetime) -> str:
    """The minute a configuration is due for."""
    return platform_lifecycle.slot_of(next_check_at, cutoff)


def upsert_configuration(upsert: PlatformAlertUpsert, *, revive: bool = False) -> bool:
    """Copy one of a source's own configurations in. True when it created the row."""
    return platform_lifecycle.upsert_configuration(upsert, revive=revive)


def upsert_if_running(upsert: PlatformAlertUpsert, *, revive: bool = False) -> None:
    """Copy one configuration in only when its team already runs that source here.

    `revive` says the source alert was just created or turned back on, so the copy starts clean.
    """
    platform_lifecycle.upsert_if_running(upsert, revive=revive)


def refresh_settings(team_id: int, configuration_id: UUID, upsert: PlatformAlertUpsert) -> None:
    """Write a source's current settings onto its copy, leaving the schedule and state alone."""
    platform_lifecycle.refresh_settings(team_id, configuration_id, upsert)


def take_ownership(handover: PlatformOwnershipHandover) -> bool:
    """Makes the platform the owner of a copied alert, carrying on from the source's state."""
    return platform_lifecycle.take_ownership(handover)


def give_back_ownership(
    *, team_id: int, legacy_configuration_id: UUID, at: datetime
) -> PlatformHandback | HandbackRefusal:
    """Hands a copied alert back to its source, or says why the platform keeps it."""
    return platform_lifecycle.give_back_ownership(
        team_id=team_id, legacy_configuration_id=legacy_configuration_id, at=at
    )


def reset_broken(*, team_id: int, legacy_configuration_id: UUID, at: datetime) -> int | None:
    """Clears a broken alert the platform owns. Returns the failure count it cleared, or None when not broken."""
    return platform_lifecycle.reset_broken(team_id=team_id, legacy_configuration_id=legacy_configuration_id, at=at)


def disable_configurations(
    source_kind: SourceKind, *, team_id: int | None = None, legacy_configuration_ids: Collection[UUID] | None = None
) -> int:
    """Switch off a source's copies, or one team's, or the copies of named source alerts. Returns how many it switched off."""
    return platform_lifecycle.disable_configurations(
        source_kind.value, team_id=team_id, legacy_configuration_ids=legacy_configuration_ids
    )


def list_configurations(
    *, team_id: int, source_kinds: Sequence[str], limit: int, offset: int
) -> PlatformAlertConfigurationPage:
    """One page of configurations a caller may read, with the total behind it."""
    return platform_reads.list_configurations(team_id=team_id, source_kinds=source_kinds, limit=limit, offset=offset)


def get_configuration(
    *, team_id: int, source_kinds: Sequence[str], configuration_id: UUID
) -> PlatformAlertConfigurationView | None:
    """One configuration, or None when it does not exist or the caller may not read its kind."""
    return platform_reads.get_configuration(
        team_id=team_id, source_kinds=source_kinds, configuration_id=configuration_id
    )


def runtime_by_legacy_id(
    *, team_id: int, legacy_configuration_ids: Collection[UUID]
) -> dict[UUID, PlatformAlertRuntime]:
    """The runtime state of each named alert the platform owns, keyed by the source's id."""
    return platform_reads.runtime_by_legacy_id(team_id=team_id, legacy_configuration_ids=legacy_configuration_ids)


def history_by_legacy_id(
    *, team_id: int, legacy_configuration_ids: Collection[UUID], since: datetime, until: datetime
) -> dict[UUID, PlatformAlertHistory]:
    """The check history in a window of each named alert the platform owns, keyed by the source's id.

    Raises when ClickHouse fails, so a caller can fall back to what it shows without the platform.
    """
    return platform_reads.history_by_legacy_id(
        team_id=team_id, legacy_configuration_ids=legacy_configuration_ids, since=since, until=until
    )


def update_configuration(
    *,
    team_id: int,
    source_kinds: Sequence[str],
    configuration_id: UUID,
    change: Callable[[PlatformAlertConfigurationEdit], PlatformAlertConfigurationEdit],
) -> PlatformAlertConfigurationView | None:
    """Applies an edit to a configuration the platform owns, or None when the caller cannot read it.

    Raises `PlatformAlertNotEditable` for a configuration its source owns, and
    `InvalidPlatformAlertEdit` for an edit its source kind rejects.
    """
    return platform_writes.update_configuration(
        team_id=team_id, source_kinds=source_kinds, configuration_id=configuration_id, change=change
    )


def update_owned_copy(
    *,
    team_id: int,
    legacy_configuration_id: UUID,
    change: Callable[[PlatformAlertConfigurationEdit], PlatformAlertConfigurationEdit],
    snooze_until: datetime | None = None,
    snooze_changed: bool = False,
) -> None:
    """Applies an edit a source made to its own row onto the copy the platform owns.

    Raises `InvalidPlatformAlertEdit` for an edit the source kind's schema rejects.
    """
    platform_writes.update_owned_copy(
        team_id=team_id,
        legacy_configuration_id=legacy_configuration_id,
        change=change,
        snooze_until=snooze_until,
        snooze_changed=snooze_changed,
    )


def delete_owned_copy(*, team_id: int, legacy_configuration_id: UUID) -> None:
    platform_writes.delete_owned_copy(team_id=team_id, legacy_configuration_id=legacy_configuration_id)


def close_owned_firings_now(*, team_id: int, legacy_configuration_id: UUID) -> None:
    """Ends the firings of a copy the platform owns and sends their incident resolves before returning,
    for a delete that is about to remove the destinations."""
    platform_writes.close_owned_firings_now(team_id=team_id, legacy_configuration_id=legacy_configuration_id)


def create_alert_destinations(
    *, team_id: int, configuration_id: UUID, destinations: Sequence[NewAlertDestination]
) -> tuple[StoredAlertDestination, ...]:
    """Adds destinations to one alert, all or none. Raises `AlertDestinationValidationError` on a refused one."""
    return alert_destinations.create_alert_destinations(
        team_id=team_id, configuration_id=configuration_id, destinations=destinations
    )


def list_alert_destinations(*, team_id: int, configuration_id: UUID) -> tuple[StoredAlertDestination, ...]:
    return alert_destinations.list_alert_destinations(team_id=team_id, configuration_id=configuration_id)


def delete_alert_destinations(*, team_id: int, configuration_id: UUID, destination_ids: Collection[UUID]) -> int:
    """Deletes the named destinations of one alert. An id of another alert is left alone."""
    return alert_destinations.delete_alert_destinations(
        team_id=team_id, configuration_id=configuration_id, destination_ids=destination_ids
    )
