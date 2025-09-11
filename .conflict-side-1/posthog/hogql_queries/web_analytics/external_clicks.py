from typing import Literal, cast

from posthog.schema import (
    CachedWebStatsTableQueryResponse,
    WebAnalyticsOrderByDirection,
    WebAnalyticsOrderByFields,
    WebExternalClicksTableQuery,
    WebExternalClicksTableQueryResponse,
    WebStatsTableQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import WebAnalyticsQueryRunner, map_columns


class WebExternalClicksTableQueryRunner(WebAnalyticsQueryRunner[WebExternalClicksTableQueryResponse]):
    query: WebExternalClicksTableQuery
    cached_response: CachedWebStatsTableQueryResponse
    paginator: HogQLHasMorePaginator

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY, limit=self.query.limit if self.query.limit else None
        )

    def to_query(self) -> ast.SelectQuery:
        if self.query.stripQueryParams:
            url_expr: ast.Expr = ast.Call(
                name="cutQueryStringAndFragment",
                args=[ast.Field(chain=["properties", "$external_click_url"])],
            )
        else:
            url_expr = ast.Field(chain=["properties", "$external_click_url"])

        with self.timings.measure("stats_table_query"):
            query = parse_select(
                """
SELECT
    url AS "context.columns.url",
    tuple(uniqIf(filtered_person_id, {current_period}), uniqIf(filtered_person_id, {previous_period})) AS "context.columns.visitors",
    tuple(sumIf(filtered_click_count, {current_period}), sumIf(filtered_click_count, {previous_period})) AS "context.columns.clicks"
FROM (
    SELECT
        any(person_id) AS filtered_person_id,
        count() AS filtered_click_count,
        {url_expr} AS url,
        MIN(session.$start_timestamp) AS start_timestamp
    FROM events
    WHERE and(
        events.event == '$autocapture',
        events.properties.$event_type == 'click',
        url IS NOT NULL,
        url != '',
        cutToFirstSignificantSubdomain(properties.`$external_click_url`) != cutToFirstSignificantSubdomain(properties.`$host`),
        {inside_periods},
        {all_properties},
    )
    GROUP BY {events_session_id}, url
)
GROUP BY "context.columns.url"
""",
                timings=self.timings,
                placeholders={
                    "url_expr": url_expr,
                    "all_properties": self._all_properties(),
                    "current_period": self._current_period_expression(),
                    "previous_period": self._previous_period_expression(),
                    "inside_periods": self._periods_expression(),
                    "events_session_id": self.events_session_property,
                },
            )
        assert isinstance(query, ast.SelectQuery)

        # Compute query order based on the columns we're selecting
        columns = [select.alias for select in query.select if isinstance(select, ast.Alias)]
        query.order_by = self._order_by(columns)

        return query

    def _order_by(self, columns: list[str]) -> list[ast.OrderExpr] | None:
        column = "context.columns.clicks"
        direction: Literal["ASC", "DESC"] = "DESC"
        if self.query.orderBy:
            field = cast(WebAnalyticsOrderByFields, self.query.orderBy[0])
            direction = cast(WebAnalyticsOrderByDirection, self.query.orderBy[1]).value

            if field == WebAnalyticsOrderByFields.VISITORS:
                column = "context.columns.visitors"
            elif field == WebAnalyticsOrderByFields.CLICKS:
                column = "context.columns.clicks"

        return [
            expr
            for expr in [
                # Primary sorting column. We always have a default sort
                ast.OrderExpr(expr=ast.Field(chain=[column]), order=direction) if column in columns else None,
                # Always add URL as final sort
                ast.OrderExpr(expr=ast.Field(chain=["context.columns.url"]), order="ASC"),
            ]
            if expr is not None
        ]

    def _all_properties(self) -> ast.Expr:
        properties = self.query.properties + self._test_account_filters
        return property_to_expr(properties, team=self.team)

    def _calculate(self):
        query = self.to_query()
        response = self.paginator.execute_hogql_query(
            query_type="stats_table_query",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
        )
        results = self.paginator.results

        assert results is not None

        results_mapped = map_columns(
            results,
            {
                1: lambda tuple, row: (  # Visitors (tuple)
                    self._unsample(tuple[0], row),
                    self._unsample(tuple[1], row),
                ),
                2: lambda tuple, row: (  # Clicks (tuple)
                    self._unsample(tuple[0], row),
                    self._unsample(tuple[1], row),
                ),
            },
        )

        return WebStatsTableQueryResponse(
            columns=response.columns,
            results=results_mapped,
            timings=response.timings,
            types=response.types,
            hogql=response.hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )
