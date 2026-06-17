from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import EventsNode, HogQLQuery, TrendsQuery

from posthog.hogql_queries.access_controlled_resources import queried_access_controlled_resources


class TestQueriedAccessControlledResources(BaseTest):
    @parameterized.expand(
        [
            ("system_table", "select * from system.notebooks", {"notebook"}),
            ("through_subquery", "select * from (select * from system.notebooks)", {"notebook"}),
            ("through_cte_body", "with n as (select 1 from system.notebooks) select * from n", {"notebook"}),
            ("multiple", "select 1 from system.notebooks, system.surveys", {"notebook", "survey"}),
            ("no_access_controlled_table", "select 1", set()),
            ("events_table", "select * from events", set()),
        ]
    )
    def test_hogql_query_system_scopes(self, _name, sql, expected):
        assert queried_access_controlled_resources(HogQLQuery(query=sql)) == expected

    def test_unparseable_hogql_fails_closed(self):
        assert queried_access_controlled_resources(HogQLQuery(query="select from from")) is None

    def test_structured_query_reads_no_system_table(self):
        query = TrendsQuery(series=[EventsNode(event="$pageview")])
        assert queried_access_controlled_resources(query) == set()
