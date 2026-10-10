"""ClickHouse queries for trace summarization.

Routes through `TraceQueryRunner` so reads land on the dedicated `ai_events`
table (falling back to the shared `events` table for data beyond the retention
window). The runner re-merges the heavy columns into `event.properties`, so
downstream formatters keep working.
"""

from posthog.schema import DateRange, LLMTrace, NodeKind, TraceQuery

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.hogql_queries.ai.ai_table_resolver import query_ai_events
from posthog.hogql_queries.ai.trace_query_runner import TraceQueryRunner
from posthog.models.team import Team
from posthog.temporal.ai_observability.evaluation_payload import PAYLOAD_BYTES_EXPR

# Matches what `TraceQueryRunner` reads from `ai_events`: the same event types, with no timestamp
# bounds, so the size measured here is the size the fetch would load.
_TRACE_SIZE_SQL = f"""
SELECT count() AS event_count, {PAYLOAD_BYTES_EXPR} AS payload_bytes
FROM posthog.ai_events AS ai_events
WHERE event IN ('$ai_span', '$ai_generation', '$ai_embedding', '$ai_metric', '$ai_feedback', '$ai_trace')
  AND trace_id = {{trace_id}}
"""


@frozen
class TraceSize:
    event_count: int
    payload_bytes: int


def fetch_trace_size(team: Team, trace_id: str) -> TraceSize:
    """Measure a trace in ClickHouse without loading its payload.

    A trace ID that a client reuses for every run grows without limit, and `fetch_trace` loads all of
    it into worker memory in one result row. Check this size first and skip traces over the limit.
    """
    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY, team_id=team.id):
        result = query_ai_events(
            query=parse_select(_TRACE_SIZE_SQL),
            placeholders={"trace_id": ast.Constant(value=trace_id)},
            team=team,
            query_type="TraceSummarizationTraceSize",
            fall_back_to_events=False,
        )
    if not result.results:
        return TraceSize(event_count=0, payload_bytes=0)
    row = result.results[0]
    return TraceSize(event_count=int(row[0] or 0), payload_bytes=int(row[1] or 0))


def fetch_trace(team: Team, trace_id: str, window_start: str, window_end: str) -> LLMTrace | None:
    """Fetch a single trace by ID via the migrated `TraceQueryRunner`.

    The runner reads `ai_events` with no timestamp bounds, so this loads the whole trace whatever
    the window says. The window bounds only the fallback read of the shared `events` table. Call
    `fetch_trace_size` first when the trace can be large.

    Returns the LLMTrace produced by the runner (with heavy columns re-merged
    into `event.properties`), or None if no events were found in the window.
    """
    trace_query = TraceQuery(
        kind=NodeKind.TRACE_QUERY,
        traceId=trace_id,
        dateRange=DateRange(date_from=window_start, date_to=window_end),
    )
    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY, team_id=team.id):
        runner = TraceQueryRunner(team=team, query=trace_query)
        response = runner.calculate()

    if not response.results:
        return None

    return response.results[0]
