"""Materialise the per-person retention curve (page-view + all-events scope).

Fills `retention_curve` for a (team, kind) by scanning the team's full event history and
computing, per person, their first qualifying day (`first_seen_day`) and the day-offsets
from it on which they were active (`active_offsets`).

v1 strategy: **full re-derivation**. Each run recomputes a (team, kind)'s whole curve and
writes fresh rows; `ReplacingMergeTree(computed_at)` keeps the newest on read. An on-read
freshness guard (`ensure_retention_curve`) skips the scan when a recent materialisation
exists, and a Redis lock stops concurrent readers from stampeding the same scan. Incremental
refresh (only new events, recent cohorts) is a follow-up — see the architecture note.

The INSERT is built in HogQL so team scoping and the team timezone match the read path
exactly: `toStartOfDay(timestamp)` truncates in the team's timezone, the same as the read
path's interval truncation, so offsets line up.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import prepare_and_print_ast

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.preaggregation.retention_curve_sql import ALL_EVENTS_KIND, DISTRIBUTED_RETENTION_CURVE_TABLE
from posthog.models import Team
from posthog.redis import get_client

logger = structlog.get_logger(__name__)

PAGEVIEW_KIND = "$pageview"
SUPPORTED_KINDS = (PAGEVIEW_KIND, ALL_EVENTS_KIND)

# Max day-offset stored. Bounds row size and caps the lookahead the curve can serve;
# queries needing a longer lookahead fall through to raw events at the gate. ~26 months
# comfortably covers monthly retention over large interval counts, well under the UInt16
# ceiling (65535).
HORIZON_DAYS = 800

# How long a materialised (team, kind) curve is treated as fresh. New activity within this
# window isn't reflected until the next run; older cohorts are immutable, so this only
# bounds recent-cohort staleness.
STALENESS_SECONDS = 15 * 60

# Lock TTL must exceed a worst-case full-history scan so it isn't released mid-INSERT.
_LOCK_TIMEOUT_SECONDS = 10 * 60
_LOCK_BLOCKING_TIMEOUT_SECONDS = 5 * 60

# Headroom over the freshness window for the full-history scan.
_INSERT_MAX_EXECUTION_TIME_SECONDS = 5 * 60

# Single-level aggregate over events, grouped by person. `min(day)` is the all-history
# cohort anchor; `groupUniqArray(day)` collects distinct active days; offsets are days from
# the anchor, capped at the horizon. Kept flat on purpose — nested subqueries get flattened
# by the HogQL optimizer, which breaks the GROUP BY.
# Aliases are deliberately non-reserved (curve_*): the INSERT column list maps positionally,
# and HogQL rejects reserved identifiers (team_id, kind, …) as aliases.
_SELECT_TEMPLATE = """
SELECT
    {team_id} AS curve_team_id,
    {kind} AS curve_kind,
    person_id AS curve_person_id,
    min(toStartOfDay(timestamp)) AS curve_first_seen_day,
    arraySort(arrayFilter(
        o -> o <= {horizon},
        arrayMap(
            d -> dateDiff('day', min(toStartOfDay(timestamp)), d),
            arraySort(groupUniqArray(toStartOfDay(timestamp)))
        )
    )) AS curve_active_offsets,
    now() AS curve_computed_at
FROM events
WHERE {event_filter}
GROUP BY person_id
"""


@dataclass
class RetentionCurveMaterialisation:
    ready: bool


def kind_for_entity_id(entity_id: str | int | None) -> str:
    """Map a retention entity id to the `kind` stored in the curve: `None` (the "all events"
    entity) → the marker, otherwise the raw event name."""
    return ALL_EVENTS_KIND if entity_id is None else str(entity_id)


def _event_filter_expr(kind: str) -> ast.Expr:
    if kind == PAGEVIEW_KIND:
        return parse_expr("equals(events.event, '$pageview')")
    return ast.Constant(value=True)


def _build_insert_sql(team: Team, kind: str) -> tuple[str, dict]:
    query = parse_select(
        _SELECT_TEMPLATE,
        placeholders={
            "team_id": ast.Constant(value=team.pk),
            "kind": ast.Constant(value=kind),
            "horizon": ast.Constant(value=HORIZON_DAYS),
            "event_filter": _event_filter_expr(kind),
        },
    )
    assert isinstance(query, ast.SelectQuery)

    context = HogQLContext(
        team_id=team.pk,
        team=team,
        enable_select_queries=True,
        limit_top_select=False,
        modifiers=create_default_modifiers_for_team(team),
    )
    select_sql, _ = prepare_and_print_ast(query, context=context, dialect="clickhouse")

    sql = (
        f"INSERT INTO {DISTRIBUTED_RETENTION_CURVE_TABLE()} "
        "(team_id, kind, person_id, first_seen_day, active_offsets, computed_at)\n"
        f"{select_sql}"
    )
    return sql, context.values


def materialize_retention_curve(team: Team, kind: str) -> None:
    """Re-derive a (team, kind)'s whole curve from full event history. Idempotent —
    ReplacingMergeTree keeps the newest computed_at."""
    if kind not in SUPPORTED_KINDS:
        raise ValueError(f"Unsupported retention curve kind: {kind!r} (expected one of {SUPPORTED_KINDS})")

    sql, values = _build_insert_sql(team, kind)
    sync_execute(sql, values, settings={"max_execution_time": _INSERT_MAX_EXECUTION_TIME_SECONDS})


def _is_fresh(team: Team, kind: str) -> bool:
    rows = sync_execute(
        f"""
        SELECT count(), max(computed_at)
        FROM {DISTRIBUTED_RETENTION_CURVE_TABLE()}
        WHERE team_id = %(team_id)s AND kind = %(kind)s
        """,
        {"team_id": team.pk, "kind": kind},
    )
    count, max_computed_at = rows[0]
    if not count or max_computed_at is None:
        return False
    # clickhouse-driver returns naive UTC datetimes for DateTime64 columns.
    age = datetime.now(UTC) - max_computed_at.replace(tzinfo=UTC)
    return age < timedelta(seconds=STALENESS_SECONDS)


def ensure_retention_curve(team: Team, kind: str) -> RetentionCurveMaterialisation:
    """Ensure a fresh curve exists for (team, kind), materialising it if stale.

    Returns `ready=False` when the kind is unsupported or materialisation failed — the read
    path treats this as a hint and falls through to raw events.
    """
    if kind not in SUPPORTED_KINDS:
        return RetentionCurveMaterialisation(ready=False)

    if _is_fresh(team, kind):
        return RetentionCurveMaterialisation(ready=True)

    lock = get_client().lock(
        f"retention_curve:materialize:{team.pk}:{kind}",
        timeout=_LOCK_TIMEOUT_SECONDS,
        blocking_timeout=_LOCK_BLOCKING_TIMEOUT_SECONDS,
    )
    if not lock.acquire():
        # Another worker is materialising; serve whatever is there if it finished in time.
        return RetentionCurveMaterialisation(ready=_is_fresh(team, kind))

    try:
        # Re-check under the lock: another worker may have just finished.
        if _is_fresh(team, kind):
            return RetentionCurveMaterialisation(ready=True)
        materialize_retention_curve(team, kind)
        return RetentionCurveMaterialisation(ready=True)
    except Exception as e:
        logger.exception("retention_curve.materialise_failed", team_id=team.pk, kind=kind, error=str(e))
        return RetentionCurveMaterialisation(ready=False)
    finally:
        try:
            lock.release()
        except Exception:
            pass


__all__ = [
    "ALL_EVENTS_KIND",
    "HORIZON_DAYS",
    "PAGEVIEW_KIND",
    "SUPPORTED_KINDS",
    "RetentionCurveMaterialisation",
    "ensure_retention_curve",
    "kind_for_entity_id",
    "materialize_retention_curve",
]
