"""ClickHouse queries for trace summarization.

Routes through `TraceQueryRunner` so reads land on the dedicated `ai_events`
table when the rollout flag is on (and fall back to the shared `events` table
otherwise). The runner re-merges the stripped heavy columns into
`event.properties`, so downstream formatters keep working post-strip.
"""

from posthog.schema import DateRange, LLMTrace, NodeKind, TraceQuery

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.ai.trace_query_runner import TraceQueryRunner
from posthog.models.team import Team


def fetch_trace(team: Team, trace_id: str, window_start: str, window_end: str) -> LLMTrace | None:
    """Fetch a single trace by ID via the migrated `TraceQueryRunner`.

    The runner's `TraceQueryDateRange` widens the input window by ±10 minutes
    internally, so callers should pass the raw window — no pre-widening here.

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
