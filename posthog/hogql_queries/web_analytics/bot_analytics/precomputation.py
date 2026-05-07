from datetime import datetime
from enum import StrEnum

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.clickhouse.preaggregation.sql import DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE
from posthog.models.team import Team

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    LazyComputationTable,
    ensure_precomputed,
)

# The Bot Analytics tab counts requests across all three telemetry events. Keep
# this in sync with `BOT_ANALYTICS_EVENTS` in
# `frontend/src/scenes/web-analytics/common.ts`.
BOT_ANALYTICS_EVENTS: tuple[str, ...] = ("$pageview", "$screen", "$http_log")


class BotTrendsBreakdown(StrEnum):
    CRAWLER = "$virt_bot_name"
    CATEGORY = "$virt_traffic_category"
    HOST = "$host"
    PATHNAME = "$pathname"


# Map breakdown enum to the HogQL field chain used in the events table.
# `$virt_bot_name` and `$virt_traffic_category` are virtual top-level fields
# resolved by HogQL; `$host` and `$pathname` live under `properties`.
BOT_TRENDS_BREAKDOWN_FIELDS: dict[BotTrendsBreakdown, list[str]] = {
    BotTrendsBreakdown.CRAWLER: ["$virt_bot_name"],
    BotTrendsBreakdown.CATEGORY: ["$virt_traffic_category"],
    BotTrendsBreakdown.HOST: ["properties", "$host"],
    BotTrendsBreakdown.PATHNAME: ["properties", "$pathname"],
}


# Variable TTL for the bot trends precomputation.
# Today's bucket changes as new events arrive, so refresh frequently.
# Older buckets are effectively frozen: the only changes come from
# late-arriving events, which are negligible for bot traffic analytics.
BOT_TRENDS_TTL_SECONDS: dict[str, int] = {
    "0d": 15 * 60,
    "1d": 60 * 60,
    "7d": 24 * 60 * 60,
    "default": 7 * 24 * 60 * 60,
}


def _bot_filter_expr() -> ast.Expr:
    return ast.And(
        exprs=[
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["$virt_is_bot"]),
                right=ast.Constant(value=True),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.NotEq,
                left=ast.Field(chain=["$virt_bot_name"]),
                right=ast.Constant(value=""),
            ),
        ]
    )


def _bot_events_tuple() -> ast.Tuple:
    return ast.Tuple(exprs=[ast.Constant(value=event) for event in BOT_ANALYTICS_EVENTS])


_INSERT_QUERY = """
SELECT
    toStartOfHour(timestamp) AS time_window_start,
    [coalesce(toString({breakdown_field}), '')] AS breakdown_value,
    uniqExactState(uuid) AS uniq_exact_state
FROM events
WHERE
    {bot_filter}
    AND event IN {bot_events}
    AND timestamp >= {time_window_min}
    AND timestamp < {time_window_max}
GROUP BY time_window_start, breakdown_value
"""


def ensure_bot_analytics_precomputed(
    team: Team,
    breakdown: BotTrendsBreakdown,
    date_from: datetime,
    date_to: datetime,
) -> LazyComputationResult:
    """Ensure bot-trends rows exist in `preaggregation_results` for [date_from, date_to).

    Creates one job per missing daily window and returns the job IDs to read
    from. Idempotent: concurrent calls coordinate via the lazy-computation
    executor (single PENDING job per range).
    """
    breakdown_chain: list[str | int] = list(BOT_TRENDS_BREAKDOWN_FIELDS[breakdown])
    placeholders: dict[str, ast.Expr] = {
        "breakdown_field": ast.Field(chain=breakdown_chain),
        "bot_events": _bot_events_tuple(),
        "bot_filter": _bot_filter_expr(),
    }

    return ensure_precomputed(
        team=team,
        insert_query=_INSERT_QUERY,
        time_range_start=date_from,
        time_range_end=date_to,
        ttl_seconds=BOT_TRENDS_TTL_SECONDS,
        table=LazyComputationTable.PREAGGREGATION_RESULTS,
        placeholders=placeholders,
    )


def _interval_bucket_expr(interval: str) -> ast.Expr:
    bucket_field = ast.Field(chain=["time_window_start"])
    if interval == "hour":
        return bucket_field
    if interval == "day":
        return ast.Call(name="toStartOfDay", args=[bucket_field])
    if interval == "week":
        return ast.Call(name="toStartOfWeek", args=[bucket_field])
    if interval == "month":
        return ast.Call(name="toStartOfMonth", args=[bucket_field])
    raise ValueError(f"Unsupported interval for bot trends precomputation: {interval}")


def bot_trends_select_query(
    job_ids: list[str],
    date_from: datetime,
    date_to: datetime,
    interval: str,
    limit_breakdowns: int | None = 10,
) -> ast.SelectQuery:
    """Build a HogQL SELECT that reads precomputed bot trends for one breakdown.

    Returns rows shaped (bucket, breakdown_value, requests). The caller is
    responsible for filtering by job IDs from the matching breakdown — mixing
    job IDs across breakdowns produces nonsensical results.

    `limit_breakdowns` keeps the response bounded: only the top N breakdown
    values by total request count are returned. Pass `None` to disable.
    """
    if not job_ids:
        # Empty IN-list is invalid; return a query that produces zero rows.
        # Caller can short-circuit, but staying explicit keeps the type stable.
        select = parse_select("SELECT NULL AS bucket, '' AS breakdown_value, toUInt64(0) AS requests WHERE 1 = 0")
        assert isinstance(select, ast.SelectQuery)
        return select

    job_ids_tuple = ast.Tuple(exprs=[ast.Constant(value=job_id) for job_id in job_ids])

    base = parse_select(
        f"""
        SELECT
            {{bucket_expr}} AS bucket,
            breakdown_value[1] AS breakdown_value,
            uniqExactMerge(uniq_exact_state) AS requests
        FROM {DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE()}
        WHERE
            job_id IN {{job_ids}}
            AND time_window_start >= {{date_from}}
            AND time_window_start < {{date_to}}
        GROUP BY bucket, breakdown_value
        """,
        placeholders={
            "bucket_expr": _interval_bucket_expr(interval),
            "job_ids": job_ids_tuple,
            "date_from": ast.Constant(value=date_from),
            "date_to": ast.Constant(value=date_to),
        },
    )
    assert isinstance(base, ast.SelectQuery)

    if limit_breakdowns is None:
        base.order_by = [
            ast.OrderExpr(expr=ast.Field(chain=["bucket"]), order="ASC"),
            ast.OrderExpr(expr=ast.Field(chain=["requests"]), order="DESC"),
        ]
        return base

    # Top-N: rank breakdown values by their total request count across the
    # full window, then keep only rows whose breakdown is in the top-N. This
    # mirrors the trends-query "Top N breakdowns" UX.
    wrapped = parse_select(
        """
        SELECT bucket, breakdown_value, requests
        FROM {inner}
        WHERE breakdown_value IN (
            SELECT breakdown_value
            FROM {inner}
            GROUP BY breakdown_value
            ORDER BY sum(requests) DESC
            LIMIT {limit}
        )
        ORDER BY bucket ASC, requests DESC
        """,
        placeholders={
            "inner": base,
            "limit": ast.Constant(value=limit_breakdowns),
        },
    )
    assert isinstance(wrapped, ast.SelectQuery)
    return wrapped
