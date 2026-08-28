"""Dormant-tenant scorecard: independent signals from the cloud DB, the persons DB and ClickHouse.

A tenant is eligible only when every signal is older than the window. `None` means the signal could not
be read (probe timeout, missing row); it is reported and treated as not eligible.
"""

import io
import csv
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from posthog.clickhouse.cluster import NodeRole
from posthog.dataclasses import frozen

from . import sql
from .units import WorkUnit


@frozen
class PersonsProbeResult:
    # None when the probe timed out or errored; the tenant is then not eligible.
    has_rows: bool | None
    created_recently: bool | None


@frozen
class TenantEstimate:
    team_id: int
    est_rows: int


PersonsProbe = Callable[[int, int], PersonsProbeResult]
ClickHouseProbe = Callable[[int, int], int | None]
PROBE_UNAVAILABLE = PersonsProbeResult(has_rows=None, created_recently=None)


@frozen
class DormancySignals:
    team_id: int
    project_id: int | None
    organization_id: str | None
    est_rows: int
    event_defs: int
    null_last_seen: int
    max_last_seen: datetime | None
    team_created_at: datetime | None
    has_active_subscription: bool | None
    has_customer_id: bool | None
    is_pending_deletion: bool | None
    events_usage: int | None
    last_login: datetime | None
    last_personal_key_use: datetime | None
    last_insight_view: datetime | None
    last_activity_log: datetime | None
    active_batch_exports: int | None
    live_surveys: int | None
    active_flags: int | None
    # None when the persons probe timed out or was unavailable.
    persons_has_rows: bool | None
    persons_created_recently: bool | None
    # None when ClickHouse could not be queried.
    clickhouse_recent_events: int | None


@frozen
class DormancyVerdict:
    signals: DormancySignals
    failures: tuple[str, ...]

    @property
    def eligible(self) -> bool:
        return not self.failures


def _older_than(value: datetime | None, cutoff: datetime) -> bool:
    return value is None or value < cutoff


def evaluate(signals: DormancySignals, days: int, now: datetime) -> DormancyVerdict:
    cutoff = now - timedelta(days=days)
    failures: list[str] = []
    if signals.team_created_at is None:
        failures.append("team not found")
    elif signals.team_created_at >= cutoff:
        failures.append("team younger than window")
    if signals.event_defs == 0:
        failures.append("no event definitions")
    if signals.null_last_seen:
        failures.append(f"{signals.null_last_seen} event definitions with NULL last_seen_at")
    if signals.max_last_seen is not None and signals.max_last_seen >= cutoff:
        failures.append("event seen inside window")
    if signals.has_active_subscription:
        failures.append("organization has active subscription")
    if signals.has_customer_id:
        failures.append("organization has billing customer")
    if signals.is_pending_deletion:
        failures.append("organization pending deletion")
    if signals.events_usage is None or signals.events_usage > 0:
        failures.append("organization event usage not zero")
    if not _older_than(signals.last_login, cutoff):
        failures.append("member logged in inside window")
    if not _older_than(signals.last_personal_key_use, cutoff):
        failures.append("personal API key used inside window")
    if not _older_than(signals.last_insight_view, cutoff):
        failures.append("insight viewed inside window")
    if not _older_than(signals.last_activity_log, cutoff):
        failures.append("activity log inside window")
    if signals.active_batch_exports:
        failures.append("active batch exports")
    if signals.live_surveys:
        failures.append("live surveys")
    if signals.active_flags:
        failures.append("active feature flags")
    if signals.persons_created_recently is None:
        failures.append("persons probe unavailable")
    elif signals.persons_created_recently:
        failures.append("persons created inside window")
    if signals.clickhouse_recent_events is None:
        failures.append("clickhouse probe unavailable")
    elif signals.clickhouse_recent_events > 0:
        failures.append("events ingested inside window")
    return DormancyVerdict(signals=signals, failures=tuple(failures))


def top_teams(cursor, top_n: int) -> list[TenantEstimate]:
    """Largest owners of posthog_eventproperty from planner statistics."""
    cursor.execute(sql.DORMANT_TOP_TEAMS, {"top_n": top_n})
    return [TenantEstimate(team_id=int(row[0]), est_rows=int(row[1])) for row in cursor.fetchall()]


def score_team(
    cursor,
    team_id: int,
    est_rows: int,
    days: int,
    persons_probe: PersonsProbe,
    clickhouse_probe: ClickHouseProbe,
) -> DormancySignals:
    cursor.execute(sql.DORMANT_EVENTDEFS, {"team_id": team_id})
    event_defs, null_last_seen, max_last_seen = cursor.fetchone()

    cursor.execute(sql.DORMANT_TEAM_ORG, {"team_id": team_id})
    team_row = cursor.fetchone()
    if team_row is None:
        team_created_at = project_id = organization_id = None
        has_active_subscription = has_customer_id = is_pending_deletion = events_usage = None
        activity: tuple[Any, ...] = (None, None, None, None, None, None, None)
    else:
        (
            team_created_at,
            project_id,
            organization_id,
            has_active_subscription,
            has_customer_id,
            is_pending_deletion,
            events_usage,
        ) = team_row
        cursor.execute(sql.DORMANT_HUMAN_ACTIVITY, {"team_id": team_id, "organization_id": organization_id})
        activity = cursor.fetchone()

    persons = persons_probe(team_id, days)
    clickhouse_recent_events = clickhouse_probe(team_id, days)

    return DormancySignals(
        team_id=team_id,
        project_id=int(project_id) if project_id is not None else None,
        organization_id=str(organization_id) if organization_id is not None else None,
        est_rows=est_rows,
        event_defs=int(event_defs or 0),
        null_last_seen=int(null_last_seen or 0),
        max_last_seen=max_last_seen,
        team_created_at=team_created_at,
        has_active_subscription=has_active_subscription,
        has_customer_id=has_customer_id,
        is_pending_deletion=is_pending_deletion,
        events_usage=int(events_usage) if events_usage is not None else None,
        last_login=activity[0],
        last_personal_key_use=activity[1],
        last_insight_view=activity[2],
        last_activity_log=activity[3],
        active_batch_exports=activity[4],
        live_surveys=activity[5],
        active_flags=activity[6],
        persons_has_rows=persons.has_rows,
        persons_created_recently=persons.created_recently,
        clickhouse_recent_events=clickhouse_recent_events,
    )


def persons_probe_for(connection, statement_timeout: str) -> PersonsProbe:
    """Probe the persons DB reader under a short statement_timeout. Any error reads as unknown."""

    def probe(team_id: int, days: int) -> PersonsProbeResult:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET statement_timeout = %s", (statement_timeout,))
                cursor.execute(sql.PERSONS_HAS_ROWS, {"team_id": team_id})
                has_rows = bool(_scalar(cursor.fetchone()))
                cursor.execute(sql.PERSONS_CREATED_RECENTLY, {"team_id": team_id, "days": days})
                created_recently = bool(_scalar(cursor.fetchone()))
            connection.rollback()
            return PersonsProbeResult(has_rows=has_rows, created_recently=created_recently)
        except Exception:
            connection.rollback()
            return PROBE_UNAVAILABLE

    return probe


def clickhouse_probe_for(cluster) -> ClickHouseProbe:
    """Count recent events for a team on a data node. Any error reads as unknown."""

    def probe(team_id: int, days: int) -> int | None:
        try:
            rows = cluster.any_host_by_role(
                lambda client: client.execute(sql.CLICKHOUSE_RECENT_EVENTS, {"team_id": team_id, "days": days}),
                NodeRole.DATA,
            ).result()
            return int(rows[0][0])
        except Exception:
            return None

    return probe


def _scalar(row: Any) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


def dormant_unit(verdict: DormancyVerdict) -> WorkUnit:
    signals = verdict.signals
    return WorkUnit(
        mode="dormant",
        team_id=signals.team_id,
        project_id=signals.project_id if signals.project_id is not None else signals.team_id,
        key="*",
        est_rows=signals.est_rows,
        reason="tenant dormant on every signal",
    )


SCORECARD_COLUMNS = (
    "team_id",
    "est_rows",
    "eligible",
    "failures",
    "max_last_seen",
    "null_last_seen",
    "event_defs",
    "team_created_at",
    "has_active_subscription",
    "has_customer_id",
    "events_usage",
    "last_login",
    "last_personal_key_use",
    "last_insight_view",
    "last_activity_log",
    "active_batch_exports",
    "live_surveys",
    "active_flags",
    "persons_has_rows",
    "persons_created_recently",
    "clickhouse_recent_events",
)


def scorecard_csv(verdicts: list[DormancyVerdict]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(SCORECARD_COLUMNS)
    for verdict in verdicts:
        s = verdict.signals
        writer.writerow(
            [
                s.team_id,
                s.est_rows,
                verdict.eligible,
                "; ".join(verdict.failures),
                s.max_last_seen,
                s.null_last_seen,
                s.event_defs,
                s.team_created_at,
                s.has_active_subscription,
                s.has_customer_id,
                s.events_usage,
                s.last_login,
                s.last_personal_key_use,
                s.last_insight_view,
                s.last_activity_log,
                s.active_batch_exports,
                s.live_surveys,
                s.active_flags,
                s.persons_has_rows,
                s.persons_created_recently,
                s.clickhouse_recent_events,
            ]
        )
    return out.getvalue()
