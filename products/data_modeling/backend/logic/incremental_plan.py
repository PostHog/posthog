"""Decide whether one materialization run rebuilds its table or updates it.

Each engine keeps its own watermark, so the same decision runs once per engine with that engine's
``scope``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from products.data_modeling.backend.logic.incremental import (
    IncrementalConfig,
    definition_fingerprint,
    get_incremental_config,
    get_incremental_state,
    window_start,
)
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery


@dataclass(frozen=True, kw_only=True, slots=True)
class WritePlan:
    """Whether this run rebuilds the table or updates it, and why. The reason is surfaced on the
    job so an unexpectedly expensive run explains itself."""

    incremental: bool
    reason: str
    since: Any = None
    fingerprint: str | None = None
    config: IncrementalConfig | None = None


def resolve_write_plan(team_id: int, saved_query_id: UUID | str, *, scope: str | None = None) -> WritePlan:
    saved_query = DataWarehouseSavedQuery.objects.get(team_id=team_id, id=saved_query_id)
    config = get_incremental_config(saved_query)
    if config is None:
        return WritePlan(incremental=False, reason="not configured for incremental materialization")

    fingerprint = definition_fingerprint(cast(dict, saved_query.query), config)
    state = get_incremental_state(saved_query, scope=scope)

    if state.watermark is None:
        return WritePlan(incremental=False, reason="first run", fingerprint=fingerprint, config=config)

    if fingerprint is None or fingerprint != state.definition_fingerprint:
        # The query or its config changed, so existing rows were computed by a definition that no
        # longer applies. Rebuilding is the only way the table still matches the SQL the user sees.
        return WritePlan(incremental=False, reason="definition changed", fingerprint=fingerprint, config=config)

    since = window_start(state, config)
    if since is None:
        return WritePlan(incremental=False, reason="no usable watermark", fingerprint=fingerprint, config=config)

    return WritePlan(
        incremental=True,
        reason="incremental",
        since=since,
        fingerprint=fingerprint,
        config=config,
    )
