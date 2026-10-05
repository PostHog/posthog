"""The shared alert tables, as a source adapter and this product's own API see them.

A source reads a batch of checks, reports what it decided, and can copy its own configurations
in. A reader asks for configurations and gets contracts. Neither ever holds one of these rows,
so every write and every scheduling rule has one home.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from products.alerts_platform.backend.facade.contracts import (
    PlatformAlertCheckInput,
    PlatformAlertConfigurationPage,
    PlatformAlertConfigurationView,
    PlatformAlertOutcome,
    PlatformAlertUpsert,
)
from products.alerts_platform.backend.logic import platform_lifecycle, platform_reads


def due_checks(team_id: int, source_kind: str, slot: str, cutoff: datetime) -> tuple[PlatformAlertCheckInput, ...]:
    """Every check one batch key owes, flattened as a source reads them."""
    return platform_lifecycle.due_checks(team_id, source_kind, slot, cutoff)


def record_outcomes(team_id: int, outcomes: Sequence[PlatformAlertOutcome], now: datetime) -> int:
    """The platform's only write of state and schedule. Returns how many rows it wrote."""
    return platform_lifecycle.record_outcomes(team_id, outcomes, now)


def slot_of(next_check_at: datetime | None, cutoff: datetime) -> str:
    """The minute a configuration is due for."""
    return platform_lifecycle.slot_of(next_check_at, cutoff)


def upsert_configuration(upsert: PlatformAlertUpsert) -> bool:
    """Copy one of a source's own configurations in. True when the row changed."""
    return platform_lifecycle.upsert_configuration(upsert)


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
