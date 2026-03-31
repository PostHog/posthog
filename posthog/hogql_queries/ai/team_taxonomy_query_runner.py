from posthog.schema import (
    CachedTeamTaxonomyQueryResponse,
    TeamTaxonomyItem,
    TeamTaxonomyQuery,
    TeamTaxonomyQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import to_printed_hogql

from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.hogql_queries.ai.utils import TaxonomyCacheMixin
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner

try:
    from posthog.taxonomy.taxonomy import IGNORED_EVENT_NAMES
except ImportError:
    IGNORED_EVENT_NAMES = []

DEFAULT_LIMIT = 500


class TeamTaxonomyQueryRunner(TaxonomyCacheMixin, AnalyticsQueryRunner[TeamTaxonomyQueryResponse]):
    """
    Calculates the top events for a team sorted by count. The EventDefinition model doesn't store the count of events,
    so this query mitigates that.
    """

    query: TeamTaxonomyQuery
    cached_response: CachedTeamTaxonomyQueryResponse
    settings: HogQLGlobalSettings | None

    def __init__(self, *args, settings: HogQLGlobalSettings | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.settings = settings
        self.paginator = HogQLHasMorePaginator(
            limit=self.query.limit or DEFAULT_LIMIT,
            offset=self.query.offset or 0,
        )

    def _calculate(self):
        query = self.to_query()
        hogql = to_printed_hogql(query, self.team)

        with tags_context(product=Product.MAX_AI):
            self.paginator.execute_hogql_query(
                query_type="TeamTaxonomyQuery",
                query=query,
                team=self.team,
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        results: list[TeamTaxonomyItem] = [
            TeamTaxonomyItem(event=event, count=count) for event, count in self.paginator.results
        ]

        return TeamTaxonomyQueryResponse(
            results=results,
            timings=self.paginator.response.timings if self.paginator.response else None,
            hogql=hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        query = parse_select(
            """
                SELECT
                    event,
                    count() as count
                FROM events
                WHERE
                    timestamp >= now () - INTERVAL 30 DAY
                GROUP BY
                    event
                ORDER BY
                    count DESC,
                    event ASC
            """
        )

        if IGNORED_EVENT_NAMES:
            assert isinstance(query, ast.SelectQuery)
            ignored_constants: list[ast.Expr] = [ast.Constant(value=name) for name in IGNORED_EVENT_NAMES]
            filter_expr = ast.CompareOperation(
                left=ast.Field(chain=["event"]),
                op=ast.CompareOperationOp.NotIn,
                right=ast.Array(exprs=ignored_constants),
            )
            if query.where:
                query.where = ast.And(exprs=[query.where, filter_expr])
            else:
                query.where = filter_expr

        return query
