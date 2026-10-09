"""Decide whether one materialization run rebuilds its table or updates it.

Each engine keeps its own watermark, so the same decision runs once per engine with that engine's
``scope``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

import structlog

from posthog.models import Team
from posthog.ph_client import feature_enabled_or_false

from products.data_modeling.backend.logic.incremental import (
    IncrementalConfig,
    definition_fingerprint,
    get_incremental_config,
    get_incremental_state,
    window_start,
)
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

LOGGER = structlog.get_logger(__name__)

# The only gate. Incremental is also the only path that writes through deltalite, so turning this
# off falls back to full refresh on delta-rs and takes the engine with it.
INCREMENTAL_FLAG = "data-modeling-incremental-views"


def incremental_enabled(team_id: int) -> bool:
    """Fails closed: a flag-service outage produces a full refresh, which costs money but is
    never wrong."""
    try:
        team = Team.objects.only("organization_id").get(id=team_id)
        return feature_enabled_or_false(
            INCREMENTAL_FLAG,
            str(team_id),
            groups={"organization": str(team.organization_id), "project": str(team_id)},
            group_properties={
                "organization": {"id": str(team.organization_id)},
                "project": {"id": str(team_id)},
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception:
        LOGGER.warning("Failed to evaluate incremental flag; falling back to full refresh", team_id=team_id)
        return False


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

    if not incremental_enabled(team_id):
        return WritePlan(incremental=False, reason="incremental materialization is not enabled")

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
