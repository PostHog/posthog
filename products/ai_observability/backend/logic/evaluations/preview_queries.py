from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.clickhouse.client.connection import Workload
from posthog.dataclasses import frozen
from posthog.hogql_queries.ai.ai_table_resolver import query_ai_events
from posthog.hogql_queries.ai.utils import HEAVY_COLUMN_NAMES, merge_heavy_properties, with_global_in_subqueries
from posthog.models import Team, User

from products.ai_observability.backend.logic.evaluations.event_io import extract_event_io
from products.ai_observability.backend.logic.message_utils import last_message_text
from products.ai_observability.backend.text_repr.formatters.media_blocks import MediaBlock

from ...backfill_candidates import ai_events_unit_key
from ...models.evaluation_configs import EVALUATION_TEST_LOOKBACK_DAYS
from ...models.evaluations import EvaluationTarget

PREVIEW_CHARACTERS = 200

GenerationEvent = dict[str, Any]


@frozen
class IOPreview:
    input: str
    output: str


@frozen
class UnitPreview:
    unit_id: str
    trace_id: str | None
    timestamp: datetime
    io: IOPreview


def _media_marker(media: MediaBlock) -> str:
    # The block's own marker adds the link, which fills a one-line title without saying what the media shows.
    return f"[{media.modality}]"


def generation_io_preview(event: Mapping[str, Any]) -> IOPreview:
    io = extract_event_io(event["event"], event["properties"])
    return IOPreview(
        input=last_message_text(io.input_raw, "user", _media_marker)[:PREVIEW_CHARACTERS],
        output=last_message_text(io.output_raw, "assistant", _media_marker)[:PREVIEW_CHARACTERS],
    )


def _recent_generations() -> list[ast.Expr]:
    return [
        ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=ast.Field(chain=["event"]),
            right=ast.Constant(value=["$ai_generation"]),
        ),
        ast.CompareOperation(
            op=ast.CompareOperationOp.Gt,
            left=ast.Field(chain=["timestamp"]),
            right=ast.ArithmeticOperation(
                op=ast.ArithmeticOperationOp.Sub,
                left=ast.Call(name="now", args=[]),
                right=ast.Call(name="toIntervalDay", args=[ast.Constant(value=EVALUATION_TEST_LOOKBACK_DAYS)]),
            ),
        ),
    ]


def _one_row_per_generation() -> ast.LimitByExpr:
    # Ingestion is at least once, so `ai_events` can hold a generation twice. A copy would be judged twice, and
    # would push another generation past the limit.
    return ast.LimitByExpr(n=ast.Constant(value=1), exprs=[ast.Field(chain=["uuid"])])


def load_generation_ids(team: Team, user: User, condition_filter: ast.Expr | None, count: int) -> list[str]:
    """Uuids of the latest generations matching `condition_filter`, newest first."""
    where_exprs = _recent_generations()
    if condition_filter is not None:
        where_exprs.append(condition_filter)
    query = ast.SelectQuery(
        select=[ai_events_unit_key(EvaluationTarget.GENERATION.value)],
        select_from=ast.JoinExpr(table=ast.Field(chain=["posthog", "ai_events"]), alias="ai_events"),
        where=ast.Placeholder(expr=ast.Field(chain=["where_clause"])),
        order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")],
        limit_by=_one_row_per_generation(),
        limit=ast.Constant(value=count),
    )
    response = query_ai_events(
        query=query,
        placeholders={"where_clause": ast.And(exprs=where_exprs)},
        team=team,
        user=user,
        query_type="EvaluationSampleTrafficGenerations",
        fall_back_to_events=False,
        workload=Workload.ONLINE,
    )
    return [str(row[0]) for row in response.results or []]


def load_generation_events(
    team: Team,
    user: User,
    *,
    condition_filter: ast.Expr | None,
    sample_count: int,
    sample_ids: Sequence[str] | None = None,
) -> list[GenerationEvent]:
    """Recent `$ai_generation` events with their heavy columns merged back, newest first, or exactly
    `sample_ids`. Raises `AIEventsUnavailableError` when `ai_events` has nothing to return."""
    where_exprs = _recent_generations()
    if sample_ids:
        where_exprs.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=ai_events_unit_key(EvaluationTarget.GENERATION.value),
                right=ast.Constant(value=list(sample_ids)),
            )
        )
        sample_count = len(sample_ids)
    elif condition_filter is not None:
        where_exprs.append(condition_filter)

    query = ast.SelectQuery(
        select=[
            ast.Field(chain=["uuid"]),
            ast.Field(chain=["event"]),
            ast.Field(chain=["properties"]),
            ast.Field(chain=["distinct_id"]),
            ast.Field(chain=["timestamp"]),
            *[ast.Field(chain=[column_name]) for column_name in HEAVY_COLUMN_NAMES],
        ],
        select_from=ast.JoinExpr(table=ast.Field(chain=["posthog", "ai_events"]), alias="ai_events"),
        where=ast.Placeholder(expr=ast.Field(chain=["where_clause"])),
        order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")],
        limit_by=_one_row_per_generation(),
        limit=ast.Constant(value=sample_count),
    )
    response = query_ai_events(
        query=query,
        placeholders={"where_clause": ast.And(exprs=where_exprs)},
        team=team,
        user=user,
        query_type="EvaluationTestHog",
        fall_back_to_events=False,
        limit_context=None,
        # Pinned ids replace the filters, so nothing can reference a warehouse table, and the auto-test on
        # every edit skips building the team's full table catalog.
        posthog_tables_only=bool(sample_ids),
    )
    events: list[GenerationEvent] = []
    for row in response.results or []:
        heavy_values = row[5 : 5 + len(HEAVY_COLUMN_NAMES)]
        events.append(
            {
                "uuid": str(row[0]),
                "event": row[1],
                "properties": merge_heavy_properties(row[2], dict(zip(HEAVY_COLUMN_NAMES, heavy_values, strict=True))),
                "distinct_id": row[3] or "",
                "timestamp": row[4],
            }
        )
    return events


# The inner query finds each unit's latest generation without reading payloads, so the outer one reads
# the heavy columns of one generation per unit rather than of every generation in a long trace or session.
# `ai_events` can hold that generation twice, so the outer query keeps one row per unit.
# The outer query names the units again, because the table has no index on uuid to find the rows by.
_UNIT_PREVIEW_SQL = f"""
SELECT
    {{unit_key}} AS unit_id,
    trace_id,
    timestamp,
    {", ".join(HEAVY_COLUMN_NAMES)}
FROM posthog.ai_events AS ai_events
WHERE event = '$ai_generation'
  AND timestamp > now() - toIntervalDay({EVALUATION_TEST_LOOKBACK_DAYS})
  AND {{unit_key}} IN {{unit_ids}}
  AND uuid IN (
    SELECT argMax(uuid, timestamp)
    FROM posthog.ai_events AS ai_events
    WHERE event = '$ai_generation'
      AND {{unit_key}} IN {{unit_ids}}
      AND timestamp > now() - toIntervalDay({EVALUATION_TEST_LOOKBACK_DAYS})
    GROUP BY {{unit_key}}
  )
ORDER BY timestamp DESC
LIMIT 1 BY unit_id
LIMIT {{limit}}
"""


def load_unit_previews(team: Team, user: User, target: str, unit_ids: Sequence[str]) -> list[UnitPreview]:
    """One preview per unit, newest first, taken from the unit's latest generation. Raises
    `AIEventsUnavailableError` when none of the units are in `ai_events`."""
    if not unit_ids:
        return []
    response = query_ai_events(
        query=with_global_in_subqueries(parse_select(_UNIT_PREVIEW_SQL)),
        placeholders={
            "unit_key": ai_events_unit_key(target),
            "unit_ids": ast.Constant(value=list(unit_ids)),
            "limit": ast.Constant(value=len(unit_ids)),
        },
        team=team,
        user=user,
        query_type="EvaluationSampleTrafficPreview",
        fall_back_to_events=False,
        workload=Workload.ONLINE,
        posthog_tables_only=True,
    )
    previews = []
    for row in response.results or []:
        unit_id, trace_id, latest = row[:3]
        properties = merge_heavy_properties({}, dict(zip(HEAVY_COLUMN_NAMES, row[3:], strict=True)))
        previews.append(
            UnitPreview(
                unit_id=str(unit_id),
                trace_id=trace_id or None,
                timestamp=latest,
                io=generation_io_preview({"event": "$ai_generation", "properties": properties}),
            )
        )
    return previews
