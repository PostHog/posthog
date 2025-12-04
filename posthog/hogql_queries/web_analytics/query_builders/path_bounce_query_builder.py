from posthog.schema import WebStatsBreakdown

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import get_property_key, get_property_type, property_to_expr

from posthog.hogql_queries.web_analytics.query_builders.base_bounce_query_builder import BaseBounceQueryBuilder
from posthog.hogql_queries.web_analytics.query_constants.stats_table_queries import PATH_BOUNCE_QUERY


class PathBounceQueryBuilder(BaseBounceQueryBuilder):
    def build(self) -> ast.SelectQuery:
        if self.runner.query.breakdownBy not in [WebStatsBreakdown.INITIAL_PAGE, WebStatsBreakdown.PAGE]:
            raise NotImplementedError("Bounce rate is only supported for page breakdowns")

        with self.runner.timings.measure("stats_table_scroll_query"):
            query = parse_select(
                PATH_BOUNCE_QUERY,
                timings=self.runner.timings,
                placeholders={
                    "breakdown_value": self._counts_breakdown_value(),
                    "where_breakdown": self.where_breakdown(),
                    "session_properties": self._session_properties(),
                    "event_properties": self._event_properties(),
                    "bounce_event_properties": self._event_properties_for_bounce_rate(),
                    "bounce_breakdown_value": self._bounce_entry_pathname_breakdown(),
                    "current_period": self._current_period_expression(),
                    "previous_period": self._previous_period_expression(),
                    "inside_periods": self._periods_expression(),
                },
            )
        assert isinstance(query, ast.SelectQuery)

        return self._apply_order_and_fill(query)

    def _event_properties_for_bounce_rate(self) -> ast.Expr:
        # Exclude pathname filters for bounce rate calculation
        #
        # This provides consistent bounce rates when filtering by multiple pathnames.
        # Without this, pathname filters would affect which sessions are considered for the
        # bounce rates calculations but since we group them by entry_pathname, the results could be misleading
        # as the events would be filtered by a IN(pathname) and the bounce shown would be for the first pathname
        # which users are not necessarily expecting to see.
        properties = [
            p
            for p in self.runner.query.properties + self.runner._test_account_filters
            if not (get_property_type(p) == "event" and get_property_key(p) == "$pathname")
        ]
        return property_to_expr(properties, team=self.runner.team, scope="event")
