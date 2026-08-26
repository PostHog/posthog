from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.hogql import ast
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
                "aliased_any",
                "select any(person.properties) as properties from events where person.id = '019cf684-0000-0000-0000-000000000000'",
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

    def test_rewrites_lookup_nested_in_outer_query(self):
        result = self._transform(
            "select properties from "
            "(select any(person.properties) as properties from events where person.id = '019cf684-0000-0000-0000-000000000000')"
        )
        assert "FROM persons" in result
        assert "FROM events" not in result

    def test_rewritten_where_is_table_qualified_against_alias_capture(self):
        result = self._transform(
            "select any(person.properties) as id from events where person.id = '019cf684-0000-0000-0000-000000000000'"
        )
        assert "FROM persons" in result
        assert "persons.id" in result

    def test_outer_cte_named_events_shadows_the_table(self):
        # Printing is impossible here (the shadowed query cannot resolve `person`), which
        # is the point: a retarget to persons would turn an invalid query into data.
        node = rewrite_person_lookups(
            parse_select(
                "with events as (select 1 as x) "
                "select properties from "
                "(select any(person.properties) as properties from events where person.id = '019cf684-0000-0000-0000-000000000000')"
            )
        )
        assert isinstance(node, ast.SelectQuery)
        assert node.select_from is not None
        inner = node.select_from.table
        assert isinstance(inner, ast.SelectQuery)
        assert inner.select_from is not None
        assert isinstance(inner.select_from.table, ast.Field)
        assert inner.select_from.table.chain == ["events"]

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
                "group_by_all",
                "select person.properties from events where person.id = '019cf684-0000-0000-0000-000000000000' group by all",
            ),
            (
                "bare_field_changes_cardinality",
                "select person.properties from events where person.id = '019cf684-0000-0000-0000-000000000000'",
            ),
            (
                "argmax_is_deterministic_latest",
                "select argMax(person.properties, timestamp) from events where person.id = '019cf684-0000-0000-0000-000000000000'",
            ),
            (
                "any_distinct",
                "select any(distinct person.properties) from events where person.id = '019cf684-0000-0000-0000-000000000000'",
            ),
            (
                "multiple_identity_predicates",
                "select any(person.properties) from events where person.id = '019cf684-0000-0000-0000-000000000000' and distinct_id = 'abc'",
            ),
            (
                "repeated_distinct_id_equalities",
                "select any(person.properties) from events where distinct_id = 'a' and distinct_id = 'b'",
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

    def _assert_untouched_events_source(self, node) -> None:
        rewritten = rewrite_person_lookups(node)
        assert isinstance(rewritten, ast.SelectQuery)
        assert rewritten.select_from is not None
        assert isinstance(rewritten.select_from.table, ast.Field)
        assert rewritten.select_from.table.chain == ["events"]

    @parameterized.expand(
        [
            ("limit_percent", "limit_percent"),
            ("limit_with_ties", "limit_with_ties"),
        ]
    )
    def test_limit_flags_disqualify(self, _name, attribute):
        node = parse_select(
            "select any(person.properties) from events where person.id = '019cf684-0000-0000-0000-000000000000' limit 10"
        )
        setattr(node, attribute, True)
        self._assert_untouched_events_source(node)

    def test_filter_expr_on_any_disqualifies(self):
        node = parse_select(
            "select any(person.properties) from events where person.id = '019cf684-0000-0000-0000-000000000000'"
        )
        assert isinstance(node, ast.SelectQuery)
        call = node.select[0]
        assert isinstance(call, ast.Call)
        call.filter_expr = ast.Constant(value=True)
        self._assert_untouched_events_source(node)

    @parameterized.expand(
        [
            ("direct_connection_skips", "0198aabb-0000-0000-0000-000000000000", None, "events"),
            ("native_schema_rewrites", None, None, "persons"),
            ("no_override_mode_skips", None, "person_id_no_override_properties_on_events", "events"),
        ]
    )
    def test_optimizer_gate(self, _name, connection_id, poe_mode, expected_table):
        from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode

        from posthog.hogql.query import HogQLQueryExecutor

        modifiers = HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode(poe_mode)) if poe_mode else None
        executor = HogQLQueryExecutor(
            query="select any(person.properties) from events where person.id = '019cf684-0000-0000-0000-000000000000'",
            team=self.team,
            connection_id=connection_id,
            modifiers=modifiers,
        )
        executor._parse_query()
        executor._apply_optimizers()
        assert isinstance(executor.select_query, ast.SelectQuery)
        assert executor.select_query.select_from is not None
        assert isinstance(executor.select_query.select_from.table, ast.Field)
        assert executor.select_query.select_from.table.chain == [expected_table]


class TestPersonLookupRewriteExecution(ClickhouseTestMixin, BaseTest):
    def _lookup(self, person_uuid, rewrite: bool):
        from posthog.schema import HogQLQueryModifiers

        return execute_hogql_query(
            f"select any(person.properties.email) from events where person.id = '{person_uuid}'",
            team=self.team,
            modifiers=HogQLQueryModifiers(rewritePersonEventLookups=rewrite),
        ).results

    @parameterized.expand([("one_event", 1), ("multiple_events", 3)])
    def test_lookup_parity_when_person_has_events(self, _name, event_count):
        from posthog.test.base import _create_event, flush_persons_and_events

        person = create_person(team=self.team, distinct_ids=["parity-user"], properties={"email": "a@example.com"})
        for _ in range(event_count):
            _create_event(
                event="$pageview",
                distinct_id="parity-user",
                team=self.team,
                person_properties={"email": "a@example.com"},
            )
        flush_persons_and_events()
        assert self._lookup(person.uuid, rewrite=True) == self._lookup(person.uuid, rewrite=False)

    def test_lookup_serves_current_properties_without_events(self):
        person = create_person(team=self.team, distinct_ids=["lookup-user"], properties={"email": "a@example.com"})
        # The intentional exception: with no events the events scan finds nothing, while
        # the rewritten lookup still answers from the persons table.
        assert self._lookup(person.uuid, rewrite=False) == [(None,)]
        assert self._lookup(person.uuid, rewrite=True) == [("a@example.com",)]
