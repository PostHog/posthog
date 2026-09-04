"""Work units for the cleanup crawler and the streamed discovery of pollution and retention units.

Discovery is lazy on purpose: units are yielded team by team so the caller can delete as it goes,
and every discovery statement is a bounded team_id range scan.
"""

import json
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Literal

from posthog.dataclasses import frozen

from . import sql
from .config import EventPropertyCleanupConfig
from .cursor import START, ResumePoint

Mode = Literal["pollution", "retention", "dormant"]


@frozen
class WorkUnit:
    """One self-limiting deletion target. Re-running a unit only removes what is left of it."""

    mode: Mode
    team_id: int
    project_id: int
    # Event names (pollution and retention) or "*" (dormant tenant).
    key: str | tuple[str, ...]
    est_rows: int
    reason: str
    # Pollution only: the polluted property names to remove from this unit's events.
    properties: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        key = self.key if isinstance(self.key, str) else f"{len(self.key)} events"
        suffix = f" x {len(self.properties)} properties" if self.properties else ""
        return f"{self.mode}:team={self.team_id}:{key}{suffix}"


@frozen
class TeamScope:
    team_id: int
    project_id: int
    has_active_subscription: bool | None


def planner_estimate(explain_json: object) -> int:
    """Read `Plan Rows` from an `EXPLAIN (FORMAT JSON)` result row."""
    if isinstance(explain_json, str):
        explain_json = json.loads(explain_json)
    if isinstance(explain_json, list) and explain_json:
        plan = explain_json[0].get("Plan", {})
        return int(plan.get("Plan Rows", 0))
    return 0


def load_team_scopes(cursor, team_ids: Sequence[int]) -> list[TeamScope]:
    if not team_ids:
        return []
    cursor.execute(sql.TEAM_ORG_STATE, {"team_ids": list(team_ids)})
    return [
        TeamScope(team_id=int(row[0]), project_id=int(row[1]), has_active_subscription=row[2])
        for row in cursor.fetchall()
    ]


def eligible_team_scopes(
    cursor, config: EventPropertyCleanupConfig, team_ids: Sequence[int], *, apply_paying_org_filter: bool
) -> list[TeamScope]:
    """Apply the team-level config filters shared by the pollution and retention modes.

    `skip_paying_orgs` guards the modes that remove real data. Pollution rows are not real data --
    they assert a property appeared on an event when it never did -- so pollution passes False and
    cleans paying and non-paying tenants alike.
    """
    excluded = set(config.never_delete_team_ids)
    allowed = set(config.team_ids) if config.team_ids is not None else None
    wanted = [t for t in team_ids if t not in excluded and (allowed is None or t in allowed)]
    scopes = load_team_scopes(cursor, wanted)
    if apply_paying_org_filter and config.skip_paying_orgs:
        scopes = [s for s in scopes if not s.has_active_subscription]
    return scopes


def iter_team_chunks(
    cursor,
    config: EventPropertyCleanupConfig,
    universe_sql: str,
    params: Mapping[str, object],
    sleep: Callable[[float], None] = time.sleep,
    *,
    start_after: int = 0,
) -> Iterator[tuple[list[int], int]]:
    """Yield `(team ids, top of the range)` per team_id range, so no statement covers a whole table.

    Starts above `start_after`, so a resumed run skips the ranges an earlier run exhausted. The
    caller only sees a range's top once it has consumed everything the range yielded, because this
    generator is lazy -- which is what makes it safe to treat as a resume point.

    With an explicit `team_ids` config the ranges are skipped and the list is yielded once.
    """
    if config.team_ids is not None:
        yield sorted(config.team_ids), 0
        return
    cursor.execute(sql.MAX_TEAM_ID)
    max_team_id = int(cursor.fetchone()[0])
    lo = max(start_after, 0)
    while lo < max_team_id:
        hi = min(lo + config.discovery_team_chunk, max_team_id)
        cursor.execute(universe_sql, {**params, "lo": lo, "hi": hi})
        team_ids = [int(row[0]) for row in cursor.fetchall()]
        yield team_ids, hi
        lo = hi
        if config.discovery_sleep_seconds:
            sleep(config.discovery_sleep_seconds)


def discover_pollution_units(
    cursor,
    config: EventPropertyCleanupConfig,
    sleep: Callable[[float], None] = time.sleep,
    *,
    resume: ResumePoint = START,
    on_progress: Callable[[ResumePoint], None] | None = None,
) -> Iterator[WorkUnit]:
    """One unit per (project, page of events), carrying that project's polluted property names.

    Events come from posthog_eventproperty itself, not from posthog_eventdefinition: 0.1% of rows
    have no definition row, and driving from there would leave them unreachable. Each page is a
    keyset step over the unique index, so a project with millions of event names costs one bounded
    statement at a time and is never counted.
    """
    for team_ids, chunk_hi in iter_team_chunks(
        cursor,
        config,
        sql.POLLUTION_TEAM_UNIVERSE,
        {},
        sleep,
        start_after=resume.last_completed_team_id,
    ):
        for scope in eligible_team_scopes(cursor, config, team_ids, apply_paying_org_filter=False):
            cursor.execute(sql.POLLUTION_CANDIDATE_NAMES, {"project_id": scope.project_id})
            properties = tuple(row[0] for row in cursor.fetchall())
            if not properties:
                continue
            after = resume.event_start_for(scope.project_id)
            while True:
                cursor.execute(
                    sql.POLLUTION_EVENT_PAGE,
                    {
                        "project_id": scope.project_id,
                        "after": after,
                        "limit": config.pollution_event_batch,
                    },
                )
                events = tuple(row[0] for row in cursor.fetchall())
                if not events:
                    break
                yield WorkUnit(
                    mode="pollution",
                    team_id=scope.team_id,
                    project_id=scope.project_id,
                    key=events,
                    est_rows=0,
                    reason=f"{len(properties)} properties with only non-event definitions",
                    properties=properties,
                )
                after = events[-1]
                # Reached only after the unit above was deleted, so this page really is finished.
                if on_progress is not None:
                    on_progress(
                        ResumePoint(
                            last_completed_team_id=resume.last_completed_team_id,
                            in_progress_project_id=scope.project_id,
                            in_progress_after_event=after,
                        )
                    )
                if len(events) < config.pollution_event_batch:
                    break
        if on_progress is not None:
            on_progress(ResumePoint(last_completed_team_id=chunk_hi))


def discover_retention_units(
    cursor, config: EventPropertyCleanupConfig, sleep: Callable[[float], None] = time.sleep
) -> Iterator[WorkUnit]:
    """One unit per batch of event names not seen for `retention_days` in a project."""
    if config.retention_days is None:
        return
    params = {"days": config.retention_days}
    for team_ids, _chunk_hi in iter_team_chunks(cursor, config, sql.RETENTION_TEAM_UNIVERSE, params, sleep):
        for scope in eligible_team_scopes(cursor, config, team_ids, apply_paying_org_filter=True):
            after = ""
            while True:
                cursor.execute(
                    sql.RETENTION_CANDIDATE_EVENTS,
                    {
                        "project_id": scope.project_id,
                        "after": after,
                        "limit": config.retention_event_batch,
                        **params,
                    },
                )
                batch = tuple(row[0] for row in cursor.fetchall())
                if not batch:
                    break
                cursor.execute(sql.RETENTION_ESTIMATE, {"project_id": scope.project_id, "names": list(batch)})
                est = planner_estimate(cursor.fetchone()[0])
                yield WorkUnit(
                    mode="retention",
                    team_id=scope.team_id,
                    project_id=scope.project_id,
                    key=batch,
                    est_rows=est,
                    reason=f"events not seen for {config.retention_days} days",
                )
                if len(batch) < config.retention_event_batch:
                    break
                after = batch[-1]
