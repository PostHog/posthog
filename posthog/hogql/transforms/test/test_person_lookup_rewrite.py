from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest import mock

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.transforms.person_lookup_rewrite import rewrite_person_lookups

from posthog.test.persons import create_person


class TestPersonLookupRewrite(BaseTest):
    def _transform(self, query: str) -> str:
        node, _ = rewrite_person_lookups(parse_select(query))
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

    def test_unaliased_select_keeps_its_implicit_column_name(self):
        result = self._transform(
            "select any(person.properties.email) from events where person.id = '019cf684-0000-0000-0000-000000000000'"
        )
        assert "AS `any(person.properties.email)`" in result

    def test_outer_query_can_reference_the_implicit_column_name(self):
        result = self._transform(
            "select `any(person.properties.email)` from "
            "(select any(person.properties.email) from events where person.id = '019cf684-0000-0000-0000-000000000000')"
        )
        assert "FROM persons" in result

    @parameterized.expand([("id",), ("properties",), ("created_at",)])
    def test_rewritten_select_fields_are_table_qualified_against_alias_capture(self, colliding_name):
        result = self._transform(
            f"select any(person.properties.email) as {colliding_name}, any(person.{colliding_name}) "
            "from events where person.id = '019cf684-0000-0000-0000-000000000000'"
        )
        assert "FROM persons" in result
        assert f"any(toNullable(persons.{colliding_name}))" in result

    @parameterized.expand(
        [
            ("events", "person.id = '019cf684-0000-0000-0000-000000000000'"),
            ("persons", "person.id = '019cf684-0000-0000-0000-000000000000'"),
            ("person_distinct_ids", "distinct_id = 'abc'"),
        ]
    )
    def test_outer_cte_shadowing_a_source_or_target_table_disables_the_rewrite(self, cte_name, predicate):
        node, rewrote = rewrite_person_lookups(
            parse_select(
                f"with {cte_name} as (select 1 as x) "
                "select properties from "
                f"(select any(person.properties) as properties from events where {predicate})"
            )
        )
        assert not rewrote
        assert isinstance(node, ast.SelectQuery)
        assert node.select_from is not None
        inner = node.select_from.table
        assert isinstance(inner, ast.SelectQuery)
        assert inner.select_from is not None
        assert isinstance(inner.select_from.table, ast.Field)
        assert inner.select_from.table.chain == ["events"]

    def test_cte_on_one_union_branch_shadows_the_other_branches(self):
        node, rewrote = rewrite_person_lookups(
            parse_select(
                "with events as (select 1 as x) select x from events "
                "union all "
                "select any(person.properties) from events where person.id = '019cf684-0000-0000-0000-000000000000'"
            )
        )
        assert not rewrote
        assert isinstance(node, ast.SelectSetQuery)
        later = node.subsequent_select_queries[0].select_query
        assert isinstance(later, ast.SelectQuery)
        assert later.select_from is not None
        assert isinstance(later.select_from.table, ast.Field)
        assert later.select_from.table.chain == ["events"]

    def test_union_branches_rewrite_when_nothing_is_shadowed(self):
        node, rewrote = rewrite_person_lookups(
            parse_select(
                "select any(person.properties) from events where person.id = '019cf684-0000-0000-0000-000000000000' "
                "union all "
                "select any(person.properties) from events where person.id = '019cf684-1111-0000-0000-000000000000'"
            )
        )
        assert rewrote
        assert isinstance(node, ast.SelectSetQuery)
        for branch in node.select_queries():
            assert isinstance(branch, ast.SelectQuery)
            assert branch.select_from is not None
            assert isinstance(branch.select_from.table, ast.Field)
            assert branch.select_from.table.chain == ["persons"]

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
        rewritten, rewrote = rewrite_person_lookups(node)
        assert not rewrote
        assert isinstance(rewritten, ast.SelectQuery)
        assert rewritten.select_from is not None
        assert isinstance(rewritten.select_from.table, ast.Field)
        assert rewritten.select_from.table.chain == ["events"]

    @parameterized.expand(
        [
            ("limit_percent", "limit_percent", True),
            ("limit_with_ties", "limit_with_ties", True),
            ("interpolate", "interpolate", [ast.InterpolateExpr(expr=ast.Field(chain=["timestamp"]))]),
        ]
    )
    def test_unhandled_select_fields_disqualify(self, _name, attribute, value):
        node = parse_select(
            "select any(person.properties) from events where person.id = '019cf684-0000-0000-0000-000000000000' limit 10"
        )
        setattr(node, attribute, value)
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
    def _execute(self, query: str, rewrite: bool):
        if rewrite:
            return execute_hogql_query(query, team=self.team)
        with mock.patch("posthog.hogql.query.rewrite_person_lookups", new=lambda node: (node, False)):
            return execute_hogql_query(query, team=self.team)

    def _lookup(self, predicate: str, rewrite: bool):
        return self._execute(f"select any(person.properties.email) from events where {predicate}", rewrite).results

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
        predicate = f"person.id = '{person.uuid}'"
        assert self._lookup(predicate, rewrite=True) == self._lookup(predicate, rewrite=False)

    def test_lookup_parity_by_distinct_id_across_merged_ids(self):
        from posthog.test.base import _create_event, flush_persons_and_events

        create_person(team=self.team, distinct_ids=["pdi-a", "pdi-b"], properties={"email": "a@example.com"})
        for distinct_id in ["pdi-a", "pdi-b"]:
            _create_event(
                event="$pageview",
                distinct_id=distinct_id,
                team=self.team,
                person_properties={"email": "a@example.com"},
            )
        flush_persons_and_events()
        assert self._lookup("distinct_id = 'pdi-b'", rewrite=True) == self._lookup(
            "distinct_id = 'pdi-b'", rewrite=False
        )
        assert self._lookup("distinct_id = 'pdi-b'", rewrite=True) == [("a@example.com",)]

    def test_lookup_serves_current_properties_without_events(self):
        person = create_person(team=self.team, distinct_ids=["lookup-user"], properties={"email": "a@example.com"})
        assert self._lookup(f"person.id = '{person.uuid}'", rewrite=False) == [(None,)]
        assert self._lookup(f"person.id = '{person.uuid}'", rewrite=True) == [("a@example.com",)]

    def test_lookup_returns_null_for_unknown_person_across_all_fields(self):
        query = (
            "select any(person.id), any(person.created_at), any(person.properties) "
            "from events where person.id = '019cf684-9999-0000-0000-000000000000'"
        )
        assert self._execute(query, rewrite=True).results == [(None, None, None)]

    def test_lookup_preserves_implicit_response_columns(self):
        query = (
            "select any(person.properties.email) from events where person.id = '019cf684-9999-0000-0000-000000000000'"
        )
        assert self._execute(query, rewrite=True).columns == self._execute(query, rewrite=False).columns
        assert self._execute(query, rewrite=True).columns == ["any(person.properties.email)"]
