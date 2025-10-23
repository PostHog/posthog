from collections.abc import Generator

from posthog.schema import CachedTraceQueryResponse, DateRange, HogQLPropertyFilter, LLMTrace, QueryLogTags, TraceQuery

from posthog.hogql_queries.ai.trace_query_runner import TraceQueryRunner
from posthog.models.team.team import Team


class TracesAnalyzerCollector:
    def __init__(self, team: Team):
        self._team = team
        # Should be large enough to go fast, and small enough to avoid any memory issues
        self._traces_per_page = 2000

    def collect_traces_to_analyze(self, date_range: DateRange) -> Generator[list[LLMTrace], None, None]:
        """
        Collect traces, return page by page to avoid storing too many full traces in memory at once.
        """
        offset = 0
        while True:
            response = self._get_db_traces_per_page(offset=offset, date_range=date_range)
            results = response.results
            offset += len(results)
            if len(results) == 0:
                break
            yield results
            if response.hasMore is not True:
                break

    def _create_traces_query(self, offset: int, date_range: DateRange) -> TraceQuery:
        return TraceQuery(
            dateRange=date_range,
            filterTestAccounts=False,  # Internal users are active, so don't see the reason to filter them out, for now
            limit=self._traces_per_page,
            offset=offset,
            limit_context=self._traces_per_page,
            properties=[
                HogQLPropertyFilter(
                    # Analyze only LangGraph traces initially
                    type="hogql",
                    key="properties.$ai_span_name = 'LangGraph'",
                    value=None,
                )
            ],
            tags=QueryLogTags(productKey="LLMAnalytics"),
        )

    def _get_db_traces_per_page(self, offset: int, date_range: DateRange) -> CachedTraceQueryResponse:
        query = self._create_traces_query(offset=offset, date_range=date_range)
        runner = TraceQueryRunner(query=query, team=self._team)
        response = runner.run()
        if not isinstance(response, CachedTraceQueryResponse):
            raise ValueError(f"Failed to get result for the previous day when analyzing LLM traces: {response}")
        return response
