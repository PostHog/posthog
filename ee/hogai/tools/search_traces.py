from datetime import UTC
from typing import Literal, cast

from django.utils import timezone

import structlog
from pydantic import BaseModel, Field

from posthog.schema import DateRange, LLMTrace, TracesQuery

from ee.hogai.context.insight.query_executor import AssistantQueryExecutor
from ee.hogai.tool import MaxTool

logger = structlog.get_logger(__name__)

SEARCH_TRACES_TOOL_PROMPT = """
Search for LLM traces based on criteria like date range, model, error status, and other properties.

# When to use this tool:
- User asks to find, search, or list LLM traces
- User asks about LLM usage, costs, latency, or errors
- User wants to filter traces by model, date, or other criteria
- User asks questions like "show me recent traces" or "what are the most expensive calls"
- User asks to "show more" or see "next page" of results (use the cursor from previous results)

# What this tool returns:
A formatted list of matching traces with their name, timestamp, latency, cost, token counts, and error count.
If more results are available, a cursor will be provided for pagination.
All timestamps are in UTC timezone.
""".strip()

SEARCH_TRACES_QUERY_DESCRIPTION = """
User's question converted into a traces query.

IMPORTANT: When the user asks to "show more" or "next page", pass the cursor
from the previous response to continue pagination. Do NOT modify the query parameters.

# Query Structure

## dateRange (optional but recommended)
Time range for the query:
- date_from: Start date (relative like "-7d", "-30d" or absolute "2024-12-01")
- date_to: End date (null for "until now", or absolute date)
Default: last 7 days if not specified.

## properties (optional)
HogQL property filters for advanced filtering. Common properties:
- $ai_model: LLM model name (e.g., "gpt-4", "claude-3")
- $ai_is_error: Whether the trace had errors (true/false)
- $ai_span_name: Name of the trace/span
- $ai_provider: LLM provider name

## filterTestAccounts (optional)
- true: Exclude internal/test accounts
- false: Include all accounts (default)

## limit (optional)
Number of results to return (1-100, default 50). Use a higher limit to see more results
instead of paginating. Use filters and date ranges to narrow down results.
""".strip()


class SearchLLMTracesArgs(BaseModel):
    query: TracesQuery = Field(description=SEARCH_TRACES_QUERY_DESCRIPTION)
    cursor: str | None = Field(
        default=None,
        description="Pagination cursor from previous search results. Pass this to get the next page of results.",
    )


class SearchLLMTracesTool(MaxTool):
    name: Literal["search_llm_traces"] = "search_llm_traces"
    args_schema: type[BaseModel] = SearchLLMTracesArgs
    description: str = SEARCH_TRACES_TOOL_PROMPT

    def get_required_resource_access(self):
        return [("llm_analytics", "viewer")]

    async def _arun_impl(self, query: TracesQuery, cursor: str | None = None) -> tuple[str, None]:
        if query.limit is None or query.limit <= 0:
            query.limit = 50
        elif query.limit > 100:
            query.limit = 100

        if query.dateRange is None:
            query.dateRange = DateRange(date_from="-7d")

        if query.filterTestAccounts is None:
            query.filterTestAccounts = False

        # Pagination: the cursor is a stringified offset. This is simpler than timestamp-based
        # cursors and works correctly because TracesQueryRunner's subquery and main query now
        # use the same ordering (min(timestamp) DESC), so offset-based pagination is stable.
        current_offset = 0
        if cursor:
            try:
                current_offset = int(cursor)
            except ValueError:
                logger.warning("Invalid pagination cursor", cursor=cursor)
        query.offset = current_offset

        utc_now = timezone.now().astimezone(UTC)
        executor = AssistantQueryExecutor(self._team, utc_now)
        query_results = await executor.aexecute_query(query)

        raw_results = cast(list[dict], query_results.get("results", []))
        results = [LLMTrace.model_validate(r) for r in raw_results]
        has_more = cast(bool, query_results.get("hasMore", False))

        # The query runner returns limit+1 results when hasMore=True — the extra row is
        # purely for detection and should not be displayed. Trim to the requested limit.
        if has_more and len(results) > query.limit:
            results = results[: query.limit]
        next_cursor = str(current_offset + len(results)) if has_more else None

        content = self._format_results(results, has_more, next_cursor)
        return content, None

    def _format_results(self, results: list[LLMTrace], has_more: bool, next_cursor: str | None = None) -> str:
        if not results:
            return "No traces found matching your criteria. Try a wider date range or different filters."

        total_count = len(results)
        if total_count == 1:
            content = "Found 1 trace:\n\n"
        else:
            content = f"Found {total_count} traces:\n\n"

        for i, trace in enumerate(results, 1):
            content += self._format_trace(i, trace)

        if has_more and next_cursor:
            content += f'\nMore traces are available. Pass cursor="{next_cursor}" to see the next page.'

        return content

    def _format_trace(self, index: int, trace: LLMTrace) -> str:
        name = trace.traceName or "Unnamed trace"
        trace_id = trace.id
        created_at = trace.createdAt

        parts = [f"ID: {trace_id}"]

        if trace.totalLatency is not None:
            parts.append(f"Latency: {trace.totalLatency:.2f}s")

        if trace.totalCost is not None:
            parts.append(f"Cost: ${trace.totalCost:.4f}")

        if trace.inputTokens is not None or trace.outputTokens is not None:
            input_tokens = int(trace.inputTokens) if trace.inputTokens else 0
            output_tokens = int(trace.outputTokens) if trace.outputTokens else 0
            parts.append(f"Tokens: {input_tokens:,} in / {output_tokens:,} out")

        if trace.errorCount is not None and trace.errorCount > 0:
            parts.append(f"Errors: {int(trace.errorCount)}")

        lines = [f"{index}. {name}"]
        lines.append(f"   {' | '.join(parts)}")
        lines.append(f"   Created: {created_at}")
        lines.append("")
        return "\n".join(lines)
