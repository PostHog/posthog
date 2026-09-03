"""Resume point for the cleanup crawler, stored as an asset materialization.

Discovery walks team_id ranges from the bottom every run. Without a resume point an
interruption -- a pod eviction, an operator cancel, or `max_runtime_minutes` firing by design --
costs a full re-walk of every already-clean unit before the run reaches new work, and prod-US
holds roughly 18 million of them.

The cursor is the highest team_id range this mode has exhausted. Only a mode whose units are
all-or-nothing may record one -- see `_chunk_recorder` in `ops.py`. Reads never fail the run: an
unreadable cursor falls back to the start, which is the behaviour the job had before it existed.
"""

import dagster
import structlog

logger = structlog.get_logger(__name__)

METADATA_KEY = "last_completed_team_id"


def cursor_asset_key(mode: str) -> dagster.AssetKey:
    """Keyed by mode so the modes never share a point. Only pollution records one today."""
    return dagster.AssetKey(["eventproperty_cleanup", "discovery_cursor", mode])


def read_cursor(instance: dagster.DagsterInstance, mode: str) -> int:
    """The highest team_id this mode finished, or 0 when there is nothing to resume from."""
    try:
        event = instance.get_latest_materialization_event(cursor_asset_key(mode))
    except Exception:
        logger.warning("eventproperty_cleanup.cursor_read_failed", mode=mode, exc_info=True)
        return 0
    materialization = event.asset_materialization if event else None
    if materialization is None:
        return 0
    entry = materialization.metadata.get(METADATA_KEY)
    if entry is None:
        return 0
    try:
        return max(int(entry.value), 0)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        logger.warning("eventproperty_cleanup.cursor_unreadable", mode=mode, value=entry.value)
        return 0


def record_cursor(context: dagster.OpExecutionContext, mode: str, team_id: int) -> None:
    """Publish the resume point. Never fails the run: losing it only costs a re-walk."""
    try:
        context.log_event(
            dagster.AssetMaterialization(
                asset_key=cursor_asset_key(mode),
                metadata={METADATA_KEY: team_id},
                description=f"{mode}: team_id ranges up to {team_id} are exhausted",
            )
        )
    except Exception:
        context.log.warning("could not record the %s resume point at team_id %s", mode, team_id)


def reset_cursor(context: dagster.OpExecutionContext, mode: str) -> None:
    """Send the resume point back to the start, so the next run re-walks every range."""
    record_cursor(context, mode, 0)
