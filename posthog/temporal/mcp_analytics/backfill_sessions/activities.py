from datetime import UTC, datetime
from typing import Any

from temporalio import activity

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.sync import database_sync_to_async
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.logger import get_write_only_logger
from posthog.temporal.mcp_analytics.backfill_sessions.types import BackfillMCPSessionsInput

from products.mcp_analytics.backend.models import MCPSession

LOGGER = get_write_only_logger()


# Two-pass aggregate:
#   1. Inner subquery (cheap) — list conversation ids that received any mcp_tool_call event
#      in the last lookback_hours. These are the only sessions whose Postgres row could be
#      stale.
#   2. Outer query — re-aggregate the FULL history of each active conversation id (bounded
#      only by the retention window) so the upsert reflects the complete picture, not just
#      what landed in the lookback. Avoids the corruption that a naive lookback-window
#      aggregate would cause when a long-lived session gets a fresh event late.
# The grouping key is $mcp_conversation_id, which the MCP service stamps onto every event in
# the same conversation. We persist it as MCPSession.session_id since that is the
# product-facing identifier of an MCP session.
_AGGREGATE_QUERY = """
SELECT
    team_id,
    JSONExtractString(properties, '$mcp_conversation_id') AS session_id,
    toString(min(timestamp)) AS session_start,
    toString(max(timestamp)) AS session_end,
    count() AS tool_call_count,
    groupUniqArrayIf(JSONExtractString(properties, '$mcp_tool_name'), JSONExtractString(properties, '$mcp_tool_name') != '') AS tools_used,
    argMax(distinct_id, timestamp) AS distinct_id,
    argMax(JSONExtractString(properties, '$mcp_client_name'), timestamp) AS mcp_client_name
FROM events
WHERE event = 'mcp_tool_call'
    AND JSONExtractString(properties, '$mcp_conversation_id') IN (
        SELECT DISTINCT JSONExtractString(properties, '$mcp_conversation_id')
        FROM events
        WHERE event = 'mcp_tool_call'
            AND JSONExtractString(properties, '$mcp_conversation_id') != ''
            AND timestamp >= now() - INTERVAL %(lookback_hours)s HOUR
    )
    AND timestamp >= now() - INTERVAL %(retention_days)s DAY
GROUP BY team_id, session_id
LIMIT 100000
FORMAT JSONEachRow
"""

# How far back we'll look when re-aggregating an active session. Bounded so the outer query
# can prune events partitions; anything older than this is effectively frozen anyway.
_RETENTION_DAYS = 7


def _parse_clickhouse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


@database_sync_to_async
def _upsert_session(row: dict[str, Any]) -> None:
    session_start = _parse_clickhouse_ts(row["session_start"])
    session_end = _parse_clickhouse_ts(row["session_end"])

    # Cross-team activity — backfills sessions for every team in a single ClickHouse pass.
    MCPSession.objects.unscoped().update_or_create(
        team_id=int(row["team_id"]),
        session_id=row["session_id"],
        defaults={
            "session_start": session_start,
            "session_end": session_end,
            "duration_seconds": max(0, int((session_end - session_start).total_seconds())),
            "tool_call_count": int(row.get("tool_call_count") or 0),
            "tools_used": [tool for tool in (row.get("tools_used") or []) if tool],
            "distinct_id": row.get("distinct_id") or "",
            "mcp_client_name": row.get("mcp_client_name") or "",
        },
    )


@activity.defn(name="aggregate-and-upsert-mcp-sessions")
async def aggregate_and_upsert_mcp_sessions(input: BackfillMCPSessionsInput) -> None:
    logger = LOGGER.bind(activity="aggregate-and-upsert-mcp-sessions")
    logger.info("Aggregating MCP sessions from ClickHouse", lookback_hours=input.lookback_hours)

    tag_queries(product=Product.MCP, feature=Feature.QUERY, name="mcp_sessions_backfill")

    async with get_client() as client:
        rows = await client.read_query_as_jsonl(
            _AGGREGATE_QUERY,
            query_parameters={
                "lookback_hours": int(input.lookback_hours),
                "retention_days": _RETENTION_DAYS,
            },
        )

    upserted = 0
    for row in rows:
        await _upsert_session(row)
        upserted += 1

    logger.info("MCP session backfill complete", rows_seen=len(rows), upserted=upserted)
