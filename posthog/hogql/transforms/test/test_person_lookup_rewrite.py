from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.hogql.parser import parse_select
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.transforms.person_lookup_rewrite import rewrite_person_lookups

from posthog.test.persons import create_person


class TestPersonLookupRewrite(BaseTest):
    def _transform(self, query: str) -> str:
        node = rewrite_person_lookups(parse_select(query))
        return " ".join(to_printed_hogql(node, self.team).split())

    @parameterized.expand(
        [
            (
                "any_properties_by_person_id",
                "select any(person.properties) from events where person.id = '019cf684-0000-0000-0000-000000000000'",
            ),
            (
                "bare_field_with_alias",
                "select person.properties as properties from events where person.id = '019cf684-0000-0000-0000-000000000000'",
            ),
            (
                "argmax_by_timestamp",
                "select argMax(person.properties, timestamp) from events where person.id = '019cf684-0000-0000-0000-000000000000'",
            ),
            (
                "property_key_and_created_at",
                "select any(person.properties.email), any(person.created_at) from events where person.id = '019cf684-0000-0000-0000-000000000000'",
            ),
            (
                "events_table_alias",
                "select any(e.person.properties) from events as e where e.person.id = '019cf684-0000-0000-0000-000000000000'",
            ),
            (
                "with_limit",
                "select any(person.properties) from events where person.id = '019cf684-0000-0000-0000-000000000000' limit 1",
            ),
        ]
    )
    def test_rewrites_person_id_lookup_to_persons(self, _name, query):
        result = self._transform(query)
        assert "FROM persons" in result
        assert "FROM events" not in result
        assert "person.id" not in result

    def test_rewrites_distinct_id_lookup_via_person_distinct_ids(self):
        result = self._transform("select any(person.properties) from events where distinct_id = 'abc'")
        assert "FROM persons" in result
        assert "FROM person_distinct_ids" in result
        assert "FROM events" not in result

    def test_multiple_identity_predicates_all_rewrite(self):
        result = self._transform(
            "select any(person.properties) from events "
            "where person.id = '019cf684-0000-0000-0000-000000000000' and distinct_id = 'abc'"
        )
        assert "FROM persons" in result
        assert "FROM events" not in result

    def test_rewrites_lookup_nested_in_outer_query(self):
        result = self._transform(
            "select properties from "
            "(select any(person.properties) as properties from events where person.id = '019cf684-0000-0000-0000-000000000000')"
        )
        assert "FROM persons" in result
        assert "FROM events" not in result

    @parameterized.expand(
        [
            (
                "timestamp_bound_is_era_scoped",
                "select any(person.properties) from events where person.id = '019cf684-0000-0000-0000-000000000000' and timestamp > '2026-01-01'",
            ),
            (
                "event_column_in_select",
                "select any(person.properties), any(event) from events where person.id = '019cf684-0000-0000-0000-000000000000'",
            ),
            (
                "event_predicate_in_where",
                "select any(person.properties) from events where person.id = '019cf684-0000-0000-0000-000000000000' and event = '$pageview'",
            ),
            (
                "raw_person_id_column_skips_override_resolution",
                "select any(person.properties) from events where person_id = '019cf684-0000-0000-0000-000000000000'",
            ),
            (
                "group_by",
                "select any(person.properties) from events where person.id = '019cf684-0000-0000-0000-000000000000' group by distinct_id",
            ),
            (
                "order_by",
                "select any(person.properties) from events where person.id = '019cf684-0000-0000-0000-000000000000' order by timestamp",
            ),
            (
                "join",
                "select any(person.properties) from events join groups on events.$group_0 = groups.key where person.id = '019cf684-0000-0000-0000-000000000000'",
            ),
            (
                "non_equality_operator",
                "select any(person.properties) from events where person.id != '019cf684-0000-0000-0000-000000000000'",
            ),
            (
                "non_constant_comparison",
                "select any(person.properties) from events where person.id = distinct_id",
            ),
            (
                "no_where",
                "select any(person.properties) from events",
            ),
            (
                "or_predicate",
                "select any(person.properties) from events where person.id = '019cf684-0000-0000-0000-000000000000' or distinct_id = 'abc'",
            ),
            (
                "other_table",
                "select any(properties) from persons where id = '019cf684-0000-0000-0000-000000000000'",
            ),
            (
                "count_aggregate",
                "select count() from events where person.id = '019cf684-0000-0000-0000-000000000000'",
            ),
        ]
    )
    def test_ineligible_queries_are_untouched(self, _name, query):
        expected = " ".join(to_printed_hogql(parse_select(query), self.team).split())
        result = self._transform(query)
        assert result == expected


class TestPersonLookupRewriteExecution(ClickhouseTestMixin, BaseTest):
    def test_lookup_serves_current_properties_without_events(self):
        person = create_person(team=self.team, distinct_ids=["lookup-user"], properties={"email": "a@example.com"})
        response = execute_hogql_query(
            f"select any(person.properties.email) from events where person.id = '{person.uuid}'",
            team=self.team,
        )
        # The person has no events, so a result proves the query read the persons table.
        assert response.results == [("a@example.com",)]
