from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
from posthog.models.filters.mixins.utils import cached_property


class WebOverviewSessionBasedQueryRunner(WebOverviewQueryRunner):
    """
    A specialized WebOverviewQueryRunner that uses only session-based filtering.

    This class inherits from WebOverviewQueryRunner and overrides the inner_select
    method to always use session-based filtering, which only filters by session
    start timestamp rather than both event timestamp and session start timestamp.

    This filtering approach matches the behavior of pre-aggregated tables and is
    used for accuracy checks to ensure our pre-aggregated tables are correct.
    """

    @cached_property
    def inner_select(self) -> ast.SelectQuery:
        """
        Override the inner_select method to always use session-based filtering.

        Session-based filtering only filters by session start timestamp, which
        matches the filtering behavior of pre-aggregated tables. This is different
        from regular filtering that filters by both event timestamp and session
        start timestamp.
        """
        # Session-based filtering: only filter by session start timestamp
        parsed_select = parse_select(
            """
SELECT
    any(events.person_id) as session_person_id,
    session.session_id as session_id,
    min(session.$start_timestamp) as start_timestamp
FROM events
WHERE and(
    {events_session_id} IS NOT NULL,
    {event_type_expr},
    {all_properties},
)
GROUP BY session_id
HAVING {inside_start_timestamp_period}
            """,
            placeholders={
                "all_properties": self.all_properties(),
                "event_type_expr": self.event_type_expr,
                "inside_start_timestamp_period": self._periods_expression("start_timestamp"),
                "events_session_id": self.events_session_property,
            },
        )

        assert isinstance(parsed_select, ast.SelectQuery)

        # Add the same fields as the parent class would add based on whether it's a conversion goal
        if self.conversion_count_expr and self.conversion_person_id_expr:
            raise NotImplementedError("Conversion metrics are not supported for session-based filtering")
        if self.query.includeRevenue:
            raise NotImplementedError("Revenue metrics are not supported for session-based filtering")

        parsed_select.select.append(
            ast.Alias(
                alias="session_duration",
                expr=ast.Call(name="any", args=[ast.Field(chain=["session", "$session_duration"])]),
            )
        )
        parsed_select.select.append(ast.Alias(alias="filtered_pageview_count", expr=self.pageview_count_expression))
        parsed_select.select.append(
            ast.Alias(alias="is_bounce", expr=ast.Call(name="any", args=[ast.Field(chain=["session", "$is_bounce"])]))
        )

        return parsed_select
