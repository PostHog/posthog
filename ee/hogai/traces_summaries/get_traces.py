from posthog.schema import CachedTracesQueryResponse, DateRange, HogQLPropertyFilter, QueryLogTags, TracesQuery

from posthog.hogql_queries.ai.traces_query_runner import TracesQueryRunner
from posthog.models.team.team import Team


class TracesSummarizerCollector:
    def __init__(self, team: Team):
        self._team = team
        # Should be large enough to go fast, and small enough to avoid any memory issues
        self._traces_per_page = 100

    def get_db_traces_per_page(self, offset: int, date_range: DateRange) -> CachedTracesQueryResponse:
        query = self._create_traces_query(offset=offset, date_range=date_range)
        runner = TracesQueryRunner(query=query, team=self._team)
        response = runner.run()
        if not isinstance(response, CachedTracesQueryResponse):
            raise ValueError(f"Failed to get result for the previous day when summarizing LLM traces: {response}")
        return response

    def _create_traces_query(self, offset: int, date_range: DateRange) -> TracesQuery:
        return TracesQuery(
            dateRange=date_range,
            filterTestAccounts=False,  # Internal users are active, so don't see the reason to filter them out, for now
            limit=self._traces_per_page,
            offset=offset,
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
