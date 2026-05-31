from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import (
    ActorsQuery,
    BreakdownFilter,
    EventPropertyFilter,
    EventsNode,
    EventsQuery,
    FunnelsDataWarehouseNode,
    FunnelsQuery,
    HogQLPropertyFilter,
    HogQLQuery,
    PathsFilter,
    PathsQuery,
    PropertyOperator,
    SessionsQuery,
    TrendsQuery,
)

from posthog.hogql_queries.contains_user_hogql import contains_user_hogql


class TestContainsUserHogQL(BaseTest):
    @parameterized.expand(
        [
            ("plain_trends", TrendsQuery(series=[EventsNode(event="$pageview")]), False),
            (
                "event_property_filter_not_hogql",
                TrendsQuery(
                    series=[
                        EventsNode(
                            event="$pageview",
                            properties=[
                                EventPropertyFilter(key="country", value="US", operator=PropertyOperator.EXACT)
                            ],
                        )
                    ]
                ),
                False,
            ),
            (
                "math_hogql",
                TrendsQuery(series=[EventsNode(event="$pageview", math="hogql", math_hogql="avg(properties.x)")]),
                True,
            ),
            (
                "invalid_math_hogql_still_detected",
                TrendsQuery(series=[EventsNode(event="$pageview", math="hogql", math_hogql="this is not (((valid")]),
                True,
            ),
            (
                "hogql_breakdown",
                TrendsQuery(
                    series=[EventsNode(event="$pageview")],
                    breakdownFilter=BreakdownFilter(breakdown_type="hogql", breakdown="properties.foo"),
                ),
                True,
            ),
            (
                "event_metadata_breakdown_not_hogql",
                TrendsQuery(
                    series=[EventsNode(event="$pageview")],
                    breakdownFilter=BreakdownFilter(breakdown_type="event_metadata", breakdown="$session_id"),
                ),
                False,
            ),
            ("sql_editor", HogQLQuery(query="select 1"), True),
            ("events_query_where", EventsQuery(select=["event"], where=["properties.x = 1"]), True),
            ("events_query_select_only_constants", EventsQuery(select=["event", "timestamp"]), True),
            ("actors_query_select", ActorsQuery(select=["id"]), True),
            ("sessions_query_select", SessionsQuery(select=["session_id"]), True),
            (
                "hogql_property_filter_nested",
                TrendsQuery(
                    series=[EventsNode(event="$pageview", properties=[HogQLPropertyFilter(type="hogql", key="1 = 1")])]
                ),
                True,
            ),
            (
                "paths_hogql_expression",
                PathsQuery(pathsFilter=PathsFilter(pathsHogQLExpression="properties.$current_url")),
                True,
            ),
            (
                "data_warehouse_node_timestamp_field",
                FunnelsQuery(
                    series=[
                        FunnelsDataWarehouseNode(
                            id="my_table",
                            table_name="my_table",
                            id_field="id",
                            timestamp_field="created_at",
                            aggregation_target_field="person_id",
                        )
                    ]
                ),
                True,
            ),
        ]
    )
    def test_contains_user_hogql(self, _name: str, query: object, expected: bool) -> None:
        self.assertEqual(contains_user_hogql(query), expected)

    def test_eventsquery_select_distinguishes_user_authored(self) -> None:
        # EventsQuery.select is always user-authored HogQL (the columns the user typed),
        # so even constant-looking selects count. This mirrors the runtime tag site.
        self.assertTrue(contains_user_hogql(EventsQuery(select=["count()"])))
