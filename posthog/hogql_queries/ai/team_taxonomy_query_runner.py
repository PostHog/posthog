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
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.hogql_queries.ai.utils import TaxonomyCacheMixin
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner

try:
    from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP
except ImportError:
    CORE_FILTER_DEFINITIONS_BY_GROUP = {}


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

    def _calculate(self):
        query = self.to_query()
        hogql = to_printed_hogql(query, self.team)

        with tags_context(product=Product.MAX_AI):
            response = execute_hogql_query(
                query_type="TeamTaxonomyQuery",
                query=query,
                team=self.team,
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        results: list[TeamTaxonomyItem] = []
        for event, count in response.results:
            if event_core_definition := CORE_FILTER_DEFINITIONS_BY_GROUP.get("events", {}).get(event):
                if event_core_definition.get("system") or event_core_definition.get("ignored_in_assistant"):
                    continue  # Skip irrelevant events
            results.append(TeamTaxonomyItem(event=event, count=count))

        return TeamTaxonomyQueryResponse(
            results=results, timings=response.timings, hogql=hogql, modifiers=self.modifiers
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
                    count DESC
                LIMIT 500
            """
        )

        return query
