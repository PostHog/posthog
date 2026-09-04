"""Resume point for the cleanup crawler, stored as an asset materialization.

Discovery walks team_id ranges from the bottom every run, and inside each project it walks event
names. Without a resume point an interruption -- a pod eviction, an operator cancel, or
`max_runtime_minutes` firing by design -- costs a full re-walk before the run reaches new work.

The point has two parts because one project can be larger than a whole range. prod-US project
128477 owns so many event names that counting them does not finish in 280 seconds, so a project has
to be resumable from the middle, not just skipped or repeated.

Only a mode whose units are all-or-nothing may record a point -- see `_chunk_recorder` in `ops.py`.
Reads never fail the run: an unreadable point falls back to the start, which is the behaviour the
job had before it existed.
"""

import dagster
import structlog

from posthog.dataclasses import frozen

logger = structlog.get_logger(__name__)

TEAM_KEY = "last_completed_team_id"
PROJECT_KEY = "in_progress_project_id"
EVENT_KEY = "in_progress_after_event"


@frozen
class ResumePoint:
    """Where discovery should pick up.

    `last_completed_team_id` is the top of the last team_id range that finished entirely. The
    in-progress pair covers the one project that was mid-flight when the run stopped: it always
    sits above `last_completed_team_id`, because a range's watermark only advances once every
    project in it is done.
    """

    last_completed_team_id: int = 0
    in_progress_project_id: int = 0
    in_progress_after_event: str = ""

    def event_start_for(self, project_id: int) -> str:
        """Where to begin this project's event walk: mid-project only for the one that was cut off."""
        if project_id and project_id == self.in_progress_project_id:
            return self.in_progress_after_event
        return ""


START = ResumePoint()


def cursor_asset_key(mode: str) -> dagster.AssetKey:
    """Keyed by mode so the modes never share a point. Only pollution records one today."""
    return dagster.AssetKey(["eventproperty_cleanup", "discovery_cursor", mode])


def _metadata_value(materialization: dagster.AssetMaterialization, key: str) -> object | None:
    entry = materialization.metadata.get(key)
    return entry.value if entry is not None else None


def _as_int(value: object) -> int:
    """Coerce a stored metadata value, which Dagster hands back as an opaque object."""
    if value is None:
        return 0
    if isinstance(value, bool):
        raise ValueError(f"expected a number, got {value!r}")
    if isinstance(value, int | float | str):
        return int(value)
    raise ValueError(f"expected a number, got {type(value).__name__}")


def read_resume_point(instance: dagster.DagsterInstance, mode: str) -> ResumePoint:
    """The recorded point, or the start when there is nothing to resume from."""
    try:
        event = instance.get_latest_materialization_event(cursor_asset_key(mode))
    except Exception:
        logger.warning("eventproperty_cleanup.cursor_read_failed", mode=mode, exc_info=True)
        return START
    materialization = event.asset_materialization if event else None
    if materialization is None:
        return START
    try:
        team = _as_int(_metadata_value(materialization, TEAM_KEY))
        project = _as_int(_metadata_value(materialization, PROJECT_KEY))
        after = str(_metadata_value(materialization, EVENT_KEY) or "")
    except (TypeError, ValueError):
        logger.warning("eventproperty_cleanup.cursor_unreadable", mode=mode)
        return START
    return ResumePoint(
        last_completed_team_id=max(team, 0),
        in_progress_project_id=max(project, 0),
        in_progress_after_event=after,
    )


def record_resume_point(context: dagster.OpExecutionContext, mode: str, point: ResumePoint) -> None:
    """Publish the point. Never fails the run: losing it only costs a re-walk."""
    try:
        context.log_event(
            dagster.AssetMaterialization(
                asset_key=cursor_asset_key(mode),
                metadata={
                    TEAM_KEY: point.last_completed_team_id,
                    PROJECT_KEY: point.in_progress_project_id,
                    EVENT_KEY: point.in_progress_after_event,
                },
                description=(
                    f"{mode}: ranges up to team_id {point.last_completed_team_id} are exhausted"
                    + (
                        f"; project {point.in_progress_project_id} is done through event"
                        f" {point.in_progress_after_event!r}"
                        if point.in_progress_project_id
                        else ""
                    )
                ),
            )
        )
    except Exception:
        context.log.warning("could not record the %s resume point (%s)", mode, point)


def reset_resume_point(context: dagster.OpExecutionContext, mode: str) -> None:
    """Send the point back to the start, so the next run re-walks everything."""
    record_resume_point(context, mode, START)
