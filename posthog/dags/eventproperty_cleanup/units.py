"""Work units for the cleanup crawler and the streamed discovery of pollution and retention units.

Discovery is lazy on purpose: units are yielded team by team so the caller can delete as it goes,
and every discovery statement is a bounded team_id range scan.
"""

import json
import time
from collections.abc import Callable, Iterator, Sequence
from typing import Literal

from posthog.dataclasses import frozen

from . import sql
from .config import EventPropertyCleanupConfig

Mode = Literal["pollution", "retention", "dormant"]


@frozen
class WorkUnit:
    """One self-limiting deletion target. Re-running a unit only removes what is left of it."""

    mode: Mode
    team_id: int
    project_id: int
    # Property name (pollution), event names (retention) or "*" (dormant tenant).
    key: str | tuple[str, ...]
    est_rows: int
    reason: str

    @property
    def label(self) -> str:
        key = self.key if isinstance(self.key, str) else f"{len(self.key)} events"
        return f"{self.mode}:team={self.team_id}:{key}"


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


def eligible_team_scopes(cursor, config: EventPropertyCleanupConfig, team_ids: Sequence[int]) -> list[TeamScope]:
    """Apply the team-level config filters shared by the pollution and retention modes."""
    excluded = set(config.never_delete_team_ids)
    allowed = set(config.team_ids) if config.team_ids is not None else None
    wanted = [t for t in team_ids if t not in excluded and (allowed is None or t in allowed)]
    scopes = load_team_scopes(cursor, wanted)
    if config.skip_paying_orgs:
        scopes = [s for s in scopes if not s.has_active_subscription]
    return scopes


def iter_team_chunks(
    cursor,
    config: EventPropertyCleanupConfig,
    universe_sql: str,
    params: dict[str, object],
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[list[int]]:
    """Yield team ids per team_id range, so no discovery statement covers a whole table.

    With an explicit `team_ids` config the ranges are skipped and the list is yielded once.
    """
    if config.team_ids is not None:
        yield sorted(config.team_ids)
        return
    cursor.execute(sql.MAX_TEAM_ID)
    max_team_id = int(cursor.fetchone()[0])
    lo = 0
    while lo < max_team_id:
        hi = min(lo + config.discovery_team_chunk, max_team_id)
        cursor.execute(universe_sql, {**params, "lo": lo, "hi": hi})
        team_ids = [int(row[0]) for row in cursor.fetchall()]
        if team_ids:
            yield team_ids
        lo = hi
        if config.discovery_sleep_seconds:
            sleep(config.discovery_sleep_seconds)


def discover_pollution_units(
    cursor, config: EventPropertyCleanupConfig, sleep: Callable[[float], None] = time.sleep
) -> Iterator[WorkUnit]:
    """One unit per (team, property) whose property has no EVENT-type definition in the project."""
    for team_ids in iter_team_chunks(cursor, config, sql.POLLUTION_TEAM_UNIVERSE, {}, sleep):
        for scope in eligible_team_scopes(cursor, config, team_ids):
            cursor.execute(sql.POLLUTION_CANDIDATE_NAMES, {"project_id": scope.project_id})
            names = [row[0] for row in cursor.fetchall()]
            for name in names:
                cursor.execute(sql.POLLUTION_ESTIMATE, {"team_id": scope.team_id, "property": name})
                est = planner_estimate(cursor.fetchone()[0])
                yield WorkUnit(
                    mode="pollution",
                    team_id=scope.team_id,
                    project_id=scope.project_id,
                    key=name,
                    est_rows=est,
                    reason="property has only non-event definitions",
                )


def discover_retention_units(
    cursor, config: EventPropertyCleanupConfig, sleep: Callable[[float], None] = time.sleep
) -> Iterator[WorkUnit]:
    """One unit per batch of event names not seen for `retention_days` in a project."""
    if config.retention_days is None:
        return
    params = {"days": config.retention_days}
    for team_ids in iter_team_chunks(cursor, config, sql.RETENTION_TEAM_UNIVERSE, params, sleep):
        for scope in eligible_team_scopes(cursor, config, team_ids):
            cursor.execute(sql.RETENTION_CANDIDATE_EVENTS, {"project_id": scope.project_id, **params})
            names = [row[0] for row in cursor.fetchall()]
            for start in range(0, len(names), config.retention_event_batch):
                batch = tuple(names[start : start + config.retention_event_batch])
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
