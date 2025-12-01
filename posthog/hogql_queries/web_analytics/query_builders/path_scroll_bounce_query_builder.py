from typing import Union

from posthog.schema import EventPropertyFilter, PersonPropertyFilter

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import (
    get_property_key,
    get_property_operator,
    get_property_type,
    get_property_value,
    property_to_expr,
)

from posthog.hogql_queries.web_analytics.query_builders.base_bounce_query_builder import BaseBounceQueryBuilder
from posthog.hogql_queries.web_analytics.query_constants.stats_table_queries import PATH_SCROLL_BOUNCE_QUERY


class PathScrollBounceQueryBuilder(BaseBounceQueryBuilder):
    def build(self) -> ast.SelectQuery:
        with self.runner.timings.measure("stats_table_bounce_query"):
            query = parse_select(
                PATH_SCROLL_BOUNCE_QUERY,
                timings=self.runner.timings,
                placeholders={
                    "session_properties": self._session_properties(),
                    "event_properties": self._event_properties(),
                    "event_properties_for_scroll": self._event_properties_for_scroll(),
                    "breakdown_value": self._counts_breakdown_value(),
                    "scroll_breakdown_value": self._scroll_prev_pathname_breakdown(),
                    "bounce_breakdown_value": self._bounce_entry_pathname_breakdown(),
                    "current_period": self._current_period_expression(),
                    "previous_period": self._previous_period_expression(),
                    "inside_periods": self._periods_expression(),
                },
            )
        assert isinstance(query, ast.SelectQuery)

        return self._apply_order_and_fill(query)

    def _event_properties_for_scroll(self) -> ast.Expr:
        def map_scroll_property(property: Union[EventPropertyFilter, PersonPropertyFilter]):
            if get_property_type(property) == "event" and get_property_key(property) == "$pathname":
                return EventPropertyFilter(
                    key="$prev_pageview_pathname",
                    operator=get_property_operator(property),
                    value=get_property_value(property),
                )
            return property

        properties = [
            map_scroll_property(p)
            for p in self.runner.query.properties + self.runner._test_account_filters
            if get_property_type(p) in ["event", "person"]
        ]
        return property_to_expr(properties, team=self.runner.team, scope="event")

    def _scroll_prev_pathname_breakdown(self) -> ast.Expr:
        return self.runner._apply_path_cleaning(ast.Field(chain=["events", "properties", "$prev_pageview_pathname"]))
