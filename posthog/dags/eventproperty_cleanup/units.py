"""Work units for the cleanup crawler and the discovery of pollution and retention units."""

import json
from collections.abc import Iterator, Sequence
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


def discover_pollution_units(cursor, config: EventPropertyCleanupConfig) -> Iterator[WorkUnit]:
    """One unit per (team, property) whose property has no EVENT-type definition in the project."""
    cursor.execute(sql.POLLUTION_TEAM_UNIVERSE)
    team_ids = [int(row[0]) for row in cursor.fetchall()]
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


def discover_retention_units(cursor, config: EventPropertyCleanupConfig) -> Iterator[WorkUnit]:
    """One unit per batch of event names not seen for `retention_days` in a project."""
    if config.retention_days is None:
        return
    if config.team_ids is not None:
        team_ids = list(config.team_ids)
    else:
        cursor.execute(sql.RETENTION_TEAM_UNIVERSE, {"days": config.retention_days})
        team_ids = [int(row[0]) for row in cursor.fetchall()]
    for scope in eligible_team_scopes(cursor, config, team_ids):
        cursor.execute(
            sql.RETENTION_CANDIDATE_EVENTS,
            {"project_id": scope.project_id, "days": config.retention_days},
        )
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
