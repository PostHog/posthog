"""
Bulk-loads every transcript AI event for a session in a single query.

`session_id` is bloom-filter indexed on both `ai_events` (native `session_id` column) and
`events` (materialized `$ai_session_id` column), so the lookup is index-pruned without the
need for a trace list or timestamp range.

Reads `posthog.ai_events` when the `ai-events-table-rollout` flag is on, falling back to the
shared `events` table when that response is empty (non-migrated teams, or sessions whose
events have all aged past the `ai_events` 30-day TTL). Heavy AI properties (`$ai_input`,
`$ai_output`, ...) live in dedicated `ai_events` columns; they're merged back into each
event's `properties` so the response matches the `LLMTraceEvent` shape and the frontend can
group by `properties.$ai_trace_id` without knowing about the dedicated columns.

Events older than the `ai_events` TTL are intentionally not recovered from `events` for
migrated teams: per the retention policy those payloads are dropped, and the shared-table
copy only lingers mid-migration. A trace whose events straddle the TTL keeps only its
in-TTL portion.
"""

from datetime import datetime
from typing import Any, cast

from posthog.schema import (
    CachedSessionMessagesQueryResponse,
    LLMTraceEvent,
    NodeKind,
    SessionMessagesQuery,
    SessionMessagesQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.ai.ai_table_resolver import execute_with_ai_events_fallback
from posthog.hogql_queries.ai.utils import HEAVY_COLUMN_NAMES, merge_heavy_properties
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner

# Per the prod distribution of events-per-session over the last 30 day, 2500 covers
# everything except a tiny fraction which are long-running autonomous-agent loops
# that can't be usefully shown as a transcript anyway.
_MAX_EVENTS = 2_500

# Excludes `$ai_metric`, `$ai_feedback`, `$ai_evaluation` which are not rendered on the sessions page.
_SESSION_TRANSCRIPT_EVENT_NAMES: frozenset[str] = frozenset(
    {"$ai_generation", "$ai_span", "$ai_trace", "$ai_embedding"}
)


class SessionMessagesQueryRunner(AnalyticsQueryRunner[SessionMessagesQueryResponse]):
    query: SessionMessagesQuery
    cached_response: CachedSessionMessagesQueryResponse

    def _calculate(self) -> SessionMessagesQueryResponse:
        result = execute_with_ai_events_fallback(
            query=self._build_query(),
            placeholders=self._build_placeholders(),
            team=self.team,
            query_type=NodeKind.SESSION_MESSAGES_QUERY,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        columns: list[str] = result.columns or []
        results = [self._map_event(dict(zip(columns, row))) for row in result.results]

        return SessionMessagesQueryResponse(
            columns=columns,
            results=results,
            timings=result.timings,
            hogql=result.hogql,
            modifiers=self.modifiers,
        )

    def to_query(self) -> ast.SelectQuery:
        return self._build_query()

    def _build_query(self) -> ast.SelectQuery:
        query = parse_select(
            """
            SELECT
                uuid,
                event,
                timestamp,
                properties,
                input,
                output,
                output_choices,
                input_state,
                output_state,
                tools
            FROM posthog.ai_events
            WHERE event IN {transcript_event_names}
              AND {filter_conditions}
            ORDER BY trace_id, timestamp
            LIMIT {max_events}
            """,
        )
        return cast(ast.SelectQuery, query)

    def _build_placeholders(self) -> dict[str, ast.Expr]:
        return {
            "filter_conditions": self._build_where_clause(),
            "transcript_event_names": ast.Tuple(
                exprs=[ast.Constant(value=name) for name in sorted(_SESSION_TRANSCRIPT_EVENT_NAMES)]
            ),
            "max_events": ast.Constant(value=_MAX_EVENTS),
        }

    def _build_where_clause(self) -> ast.Expr:
        # No timestamp bound: `session_id` is bloom-filter indexed, and the `ai_events` TTL
        # already caps how far back the dedicated table reaches. The resolver rewrites
        # `session_id`/`trace_id` to `properties.$ai_*` on the events fallback path.
        return ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["session_id"]),
                    right=ast.Constant(value=self.query.sessionId),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.NotEq,
                    left=ast.Field(chain=["trace_id"]),
                    right=ast.Constant(value=""),
                ),
            ]
        )

    def _map_event(self, row: dict[str, Any]) -> LLMTraceEvent:
        heavy_columns = {name: row.get(name) or "" for name in HEAVY_COLUMN_NAMES}
        properties_json = row.get("properties") or ""
        return LLMTraceEvent.model_validate(
            {
                "id": str(row["uuid"]),
                "event": row["event"],
                "createdAt": cast(datetime, row["timestamp"]).isoformat(),
                "properties": merge_heavy_properties(properties_json, heavy_columns),
            }
        )

    def get_cache_payload(self) -> dict:
        # Bump `schema_version` to invalidate cached responses on response-shape changes.
        return {**super().get_cache_payload(), "schema_version": 1}
