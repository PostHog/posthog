from datetime import UTC, date, datetime
from typing import Any, Optional, cast
from uuid import UUID

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest

from django.test import override_settings

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    ExpressionField,
    FieldTraverser,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
    TableNode,
)
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast, print_prepared_ast
from posthog.hogql.resolver import ResolutionError, resolve_types
from posthog.hogql.test.utils import pretty_dataclasses
from posthog.hogql.visitor import clone_expr


class TestResolver(BaseTest):
    maxDiff = None
    snapshot: Any

    def _select(self, query: str, placeholders: Optional[dict[str, ast.Expr]] = None) -> ast.SelectQuery:
        return cast(
            ast.SelectQuery,
            clone_expr(parse_select(query, placeholders=placeholders), clear_locations=True),
        )

    def _print_hogql(self, select: str):
        expr = self._select(select)
        return prepare_and_print_ast(
            expr,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "hogql",
        )[0]

    def setUp(self):
        self.database = Database.create_for(team=self.team)
        self.context = HogQLContext(database=self.database, team_id=self.team.pk, enable_select_queries=True)

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_events_table(self):
        expr = self._select("SELECT event, events.timestamp FROM events WHERE events.event = 'test'")
        expr = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="clickhouse"))
        assert pretty_dataclasses(expr) == self.snapshot

    def test_will_not_run_twice(self):
        expr = self._select("SELECT event, events.timestamp FROM events WHERE events.event = 'test'")
        expr = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="clickhouse"))
        with self.assertRaises(ResolutionError) as context:
            expr = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="clickhouse"))
        self.assertEqual(
            str(context.exception),
            "Type already resolved for SelectQuery (SelectQueryType). Can't run again.",
        )

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_events_table_alias(self):
        expr = self._select("SELECT event, e.timestamp FROM events e WHERE e.event = 'test'")
        expr = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="clickhouse"))
        assert pretty_dataclasses(expr) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_events_table_column_alias(self):
        expr = self._select("SELECT event as ee, ee, ee as e, e.timestamp FROM events e WHERE e.event = 'test'")
        expr = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="clickhouse"))
        assert pretty_dataclasses(expr) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_events_table_column_alias_inside_subquery(self):
        expr = self._select("SELECT b FROM (select event as b, timestamp as c from events) e WHERE e.b = 'test'")
        expr = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="clickhouse"))
        assert pretty_dataclasses(expr) == self.snapshot

    def test_resolve_subquery_no_field_access(self):
        # From ClickHouse's GitHub: "Aliases defined outside of subquery are not visible in subqueries (but see below)."
        expr = self._select(
            "SELECT event, (select count() from events where event = e.event) as c FROM events e where event = '$pageview'"
        )
        with self.assertRaises(QueryError) as e:
            expr = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="clickhouse"))
        self.assertEqual(str(e.exception), "Unable to resolve field: e")

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_constant_type(self):
        with freeze_time("2020-01-10 00:00:00"):
            expr = self._select(
                "SELECT 1, 'boo', true, 1.1232, null, {date}, {datetime}, {uuid}, {array}, {array12}, {tuple}",
                placeholders={
                    "date": ast.Constant(value=date(2020, 1, 10)),
                    "datetime": ast.Constant(value=datetime(2020, 1, 10, 0, 0, 0, tzinfo=UTC)),
                    "uuid": ast.Constant(value=UUID("00000000-0000-4000-8000-000000000000")),
                    "array": ast.Constant(value=[]),
                    "array12": ast.Constant(value=[1, 2]),
                    "tuple": ast.Constant(value=(1, 2, 3)),
                },
            )
            expr = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="clickhouse"))
            assert pretty_dataclasses(expr) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_boolean_operation_types(self):
        expr = self._select("SELECT 1 and 1, 1 or 1, not true")
        expr = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="clickhouse"))
        assert pretty_dataclasses(expr) == self.snapshot

    def test_resolve_errors(self):
        queries = [
            "SELECT event, (select count() from events where event = x.event) as c FROM events x where event = '$pageview'",
            "SELECT x, (SELECT 1 AS x)",
            "SELECT x IN (SELECT 1 AS x)",
            "SELECT events.x FROM (SELECT event as x FROM events) AS t",
            "SELECT x.y FROM (SELECT event as y FROM events AS x) AS t",
        ]
        for query in queries:
            with self.assertRaises(QueryError) as e:
                resolve_types(self._select(query), self.context, dialect="clickhouse")
            self.assertIn("Unable to resolve field:", str(e.exception))

    def test_unresolved_field_type(self):
        query = "SELECT x"
        # raises with ClickHouse
        with self.assertRaises(QueryError):
            resolve_types(self._select(query), self.context, dialect="clickhouse")
        # does not raise with HogQL
        select = self._select(query)
        select = cast(ast.SelectQuery, resolve_types(select, self.context, dialect="hogql"))
        assert isinstance(select.select[0].type, ast.UnresolvedFieldType)

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_lazy_pdi_person_table(self):
        expr = self._select("select distinct_id, person.id from person_distinct_ids")
        expr = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="clickhouse"))
        assert pretty_dataclasses(expr) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_lazy_events_pdi_table(self):
        expr = self._select("select event, pdi.person_id from events")
        expr = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="clickhouse"))
        assert pretty_dataclasses(expr) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_lazy_events_pdi_table_aliased(self):
        expr = self._select("select event, e.pdi.person_id from events e")
        expr = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="clickhouse"))
        assert pretty_dataclasses(expr) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_lazy_events_pdi_person_table(self):
        expr = self._select("select event, pdi.person.id from events")
        expr = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="clickhouse"))
        assert pretty_dataclasses(expr) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_lazy_events_pdi_person_table_aliased(self):
        expr = self._select("select event, e.pdi.person.id from events e")
        expr = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="clickhouse"))
        assert pretty_dataclasses(expr) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_virtual_events_poe(self):
        expr = self._select("select event, poe.id from events")
        expr = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="clickhouse"))
        assert pretty_dataclasses(expr) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_union_all(self):
        node = self._select("select event, timestamp from events union all select event, timestamp from events")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        assert pretty_dataclasses(node) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_call_type(self):
        node = self._select("select max(timestamp) from events")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        assert pretty_dataclasses(node) == self.snapshot

    def test_ctes_loop(self):
        with self.assertRaises(QueryError) as e:
            self._print_hogql("with cte as (select * from cte) select * from cte")
        self.assertIn("Too many CTE expansions (50+). Probably a CTE loop.", str(e.exception))

    def test_ctes_basic_column(self):
        expr = self._print_hogql("with 1 as cte select cte from events")
        expected = self._print_hogql("select 1 from events")
        self.assertEqual(expr, expected)

    def test_ctes_recursive_column(self):
        self.assertEqual(
            self._print_hogql("with 1 as cte, cte as soap select soap from events"),
            self._print_hogql("select 1 from events"),
        )

    def test_ctes_field_access(self):
        with self.assertRaises(QueryError) as e:
            self._print_hogql("with properties as cte select cte.$browser from events")
        self.assertIn("Cannot access fields on CTE cte yet", str(e.exception))

    def test_ctes_subqueries(self):
        self.assertEqual(
            self._print_hogql("with my_table as (select * from events) select * from my_table"),
            self._print_hogql("select * from (select * from events) my_table"),
        )

        self.assertEqual(
            self._print_hogql("with my_table as (select * from events) select my_table.timestamp from my_table"),
            self._print_hogql("select my_table.timestamp from (select * from events) my_table"),
        )

        self.assertEqual(
            self._print_hogql("with my_table as (select * from events) select timestamp from my_table"),
            self._print_hogql("select timestamp from (select * from events) my_table"),
        )

    def test_ctes_subquery_deep(self):
        self.assertEqual(
            self._print_hogql(
                "with my_table as (select * from events), "
                "other_table as (select * from (select * from (select * from my_table))) "
                "select * from other_table"
            ),
            self._print_hogql(
                "select * from (select * from (select * from (select * from (select * from events) as my_table))) as other_table"
            ),
        )

    def test_ctes_subquery_recursion(self):
        self.assertEqual(
            self._print_hogql(
                "with users as (select event, timestamp as tt from events ), final as ( select tt from users ) select * from final"
            ),
            self._print_hogql(
                "select * from (select tt from (select event, timestamp as tt from events) AS users) AS final"
            ),
        )

    def test_ctes_with_aliases(self):
        self.assertEqual(
            self._print_hogql(
                "WITH initial_alias AS (SELECT 1 AS a) SELECT a FROM initial_alias AS new_alias WHERE new_alias.a=1"
            ),
            self._print_hogql("SELECT a FROM (SELECT 1 AS a) AS new_alias WHERE new_alias.a=1"),
        )

    def test_ctes_with_union_all(self):
        self.assertEqual(
            self._print_hogql(
                """
                    WITH cte1 AS (SELECT 1 AS a)
                    SELECT 1 AS a
                    UNION ALL
                    WITH cte2 AS (SELECT 2 AS a)
                    SELECT * FROM cte2
                    UNION ALL
                    SELECT * FROM cte1
                        """
            ),
            self._print_hogql(
                """
                    SELECT 1 AS a
                    UNION ALL
                    SELECT * FROM (SELECT 2 AS a) AS cte2
                    UNION ALL
                    SELECT * FROM (SELECT 1 AS a) AS cte1
                        """
            ),
        )

    def test_join_using(self):
        node = self._select(
            "WITH my_table AS (SELECT 1 AS a) SELECT q1.a FROM my_table AS q1 INNER JOIN my_table AS q2 USING a"
        )
        node = resolve_types(node, self.context, dialect="clickhouse")
        assert isinstance(node, ast.SelectQuery)
        assert isinstance(node.select_from, ast.JoinExpr)
        assert isinstance(node.select_from.next_join, ast.JoinExpr)
        assert isinstance(node.select_from.next_join.constraint, ast.JoinConstraint)
        constraint = node.select_from.next_join.constraint
        assert constraint.constraint_type == "USING"
        assert cast(ast.Field, cast(ast.Alias, constraint.expr).expr).chain == ["a"]

        node = self._select("SELECT q1.event FROM events AS q1 INNER JOIN events AS q2 USING event")
        node = resolve_types(node, self.context, dialect="clickhouse")
        assert isinstance(node, ast.SelectQuery)
        assert isinstance(node.select_from, ast.JoinExpr)
        assert isinstance(node.select_from.next_join, ast.JoinExpr)
        assert isinstance(node.select_from.next_join.constraint, ast.JoinConstraint)
        assert node.select_from.next_join.constraint.constraint_type == "USING"

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    @pytest.mark.usefixtures("unittest_snapshot")
    def test_asterisk_expander_table(self):
        self.setUp()  # rebuild self.database with PERSON_ON_EVENTS_OVERRIDE=False
        node = self._select("select * from events")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        assert pretty_dataclasses(node) == self.snapshot

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    @pytest.mark.usefixtures("unittest_snapshot")
    def test_asterisk_expander_table_alias(self):
        self.setUp()  # rebuild self.database with PERSON_ON_EVENTS_OVERRIDE=False
        node = self._select("select * from events e")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        assert pretty_dataclasses(node) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_asterisk_expander_subquery(self):
        node = self._select("select * from (select 1 as a, 2 as b)")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        assert pretty_dataclasses(node) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_asterisk_expander_hidden_field(self):
        self.database.get_table("events").fields["hidden_field"] = ExpressionField(
            name="hidden_field", hidden=True, expr=ast.Field(chain=["event"])
        )
        node = self._select("select * from events")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        assert pretty_dataclasses(node) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_expression_field_type_scope(self):
        self.database.get_table("events").fields["some_expr"] = ExpressionField(
            name="some_expr", expr=ast.Field(chain=["properties"]), isolate_scope=True
        )
        self.database.get_table("persons").fields["some_expr"] = ExpressionField(
            name="some_expr", expr=ast.Field(chain=["properties"]), isolate_scope=True
        )

        node = self._select("select e.some_expr, p.some_expr from events e left join persons p on e.uuid = p.id")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        assert pretty_dataclasses(node) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_asterisk_expander_subquery_alias(self):
        node = self._select("select x.* from (select 1 as a, 2 as b) x")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        assert pretty_dataclasses(node) == self.snapshot

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    @pytest.mark.usefixtures("unittest_snapshot")
    def test_asterisk_expander_from_subquery_table(self):
        self.setUp()  # rebuild self.database with PERSON_ON_EVENTS_OVERRIDE=False
        node = self._select("select * from (select * from events)")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        assert pretty_dataclasses(node) == self.snapshot

    def test_asterisk_expander_multiple_table_error(self):
        node = self._select("select * from (select 1 as a, 2 as b) x left join (select 1 as a, 2 as b) y on x.a = y.a")
        with self.assertRaises(QueryError) as e:
            resolve_types(node, self.context, dialect="clickhouse")
        self.assertEqual(
            str(e.exception),
            "Cannot use '*' without table name when there are multiple tables in the query",
        )

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    @pytest.mark.usefixtures("unittest_snapshot")
    def test_asterisk_expander_multiple_table_with_scope(self):
        node = self._select(
            "select x.* from (select 1 as a, 2 as b) x left join (select 1 as a, 2 as b) y on x.a = y.a"
        )
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        assert pretty_dataclasses(node) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_asterisk_expander_multiple_base_table_with_scope(self):
        node = self._select("select e.* from session_replay_events e join sessions s on s.session_id=e.session_id")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        assert pretty_dataclasses(node) == self.snapshot

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    @pytest.mark.usefixtures("unittest_snapshot")
    def test_asterisk_expander_select_union(self):
        self.setUp()  # rebuild self.database with PERSON_ON_EVENTS_OVERRIDE=False
        node = self._select("select * from (select * from events union all select * from events)")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        assert pretty_dataclasses(node) == self.snapshot

    def test_lambda_parent_scope(self):
        # does not raise
        node = self._select("select timestamp, arrayMap(x -> x + timestamp, [2]) as am from events")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))

        # found a type
        lambda_type: ast.SelectQueryType = cast(
            ast.SelectQueryType, cast(ast.Call, cast(ast.Alias, node.select[1]).expr).args[0].type
        )
        self.assertEqual(lambda_type.parent, node.type)
        self.assertEqual(list(lambda_type.aliases.keys()), ["x"])
        assert isinstance(lambda_type.parent, ast.SelectQueryType)
        self.assertEqual(list(lambda_type.parent.columns.keys()), ["timestamp", "am"])

    def test_field_traverser_double_dot(self):
        # Create a condition where we want to ".." out of "events.poe." to get to a higher level prop
        self.database.get_table("events").fields["person"] = FieldTraverser(chain=["poe"])
        assert isinstance(self.database.get_table("events").fields["poe"], Table)
        self.database.get_table("events").fields["poe"].fields["id"] = FieldTraverser(chain=["..", "pdi", "person_id"])  # type: ignore
        self.database.get_table("events").fields["poe"].fields["created_at"] = FieldTraverser(  # type: ignore
            chain=["..", "pdi", "person", "created_at"]
        )
        self.database.get_table("events").fields["poe"].fields["properties"] = StringJSONDatabaseField(  # type: ignore
            name="person_properties", nullable=False
        )

        node = self._select("SELECT event, person.id, person.properties, person.created_at FROM events")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))

        # all columns resolve to a type in the end
        assert cast(ast.FieldType, node.select[0].type).resolve_database_field(self.context) == StringDatabaseField(
            name="event", array=None, nullable=False
        )
        assert cast(ast.FieldType, node.select[1].type).resolve_database_field(self.context) == StringDatabaseField(
            name="person_id", array=None, nullable=False
        )
        assert cast(ast.FieldType, node.select[2].type).resolve_database_field(self.context) == StringJSONDatabaseField(
            name="person_properties", nullable=False
        )
        assert cast(ast.FieldType, node.select[3].type).resolve_database_field(self.context) == DateTimeDatabaseField(
            name="created_at", array=None, nullable=False
        )

    def test_visit_hogqlx_tag(self):
        node = self._select("select event from <HogQLQuery query='select event from events' />")
        assert isinstance(node, ast.SelectQuery)
        node = resolve_types(node, self.context, dialect="clickhouse")
        assert isinstance(node.select_from, ast.JoinExpr)
        table_node = node.select_from.table
        assert table_node is not None
        expected = ast.SelectQuery(
            select=[ast.Alias(hidden=True, alias="event", expr=ast.Field(chain=["event"]))],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        )
        assert cast(ast.SelectQuery, clone_expr(table_node, clear_types=True)) == expected

    def test_visit_hogqlx_tag_alias(self):
        node = self._select("select event from <HogQLQuery query='select event from events' /> a")
        assert isinstance(node, ast.SelectQuery)
        node = resolve_types(node, self.context, dialect="clickhouse")
        assert isinstance(node.select_from, ast.JoinExpr)
        assert node.select_from.alias == "a"

    def test_visit_hogqlx_tag_source(self):
        query = """
            select id, email from (
                <ActorsQuery
                    select={['id', 'properties.email as email']}
                    source={
                        <HogQLQuery query='select distinct person_id from events' />
                    }
                />
            )
        """
        node = cast(ast.SelectQuery, resolve_types(self._select(query), self.context, dialect="hogql"))
        hogql = print_prepared_ast(node, HogQLContext(team_id=self.team.pk, enable_select_queries=True), "hogql")
        expected = (
            "SELECT id, email FROM "
            "(SELECT id, properties.email AS email FROM "
            "(SELECT DISTINCT person_id FROM events) "
            "AS source INNER JOIN "
            "persons ON equals(persons.id, source.person_id) ORDER BY id ASC) "
            f"LIMIT {MAX_SELECT_RETURNED_ROWS}"
        )

        assert hogql == expected

    def test_visit_hogqlx_recording_button(self):
        node = self._select("select <RecordingButton sessionId={'12345-6789'} />")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        expected = ast.SelectQuery(
            select=[
                ast.Tuple(
                    exprs=[
                        ast.Constant(value="__hx_tag"),
                        ast.Constant(value="RecordingButton"),
                        ast.Constant(value="sessionId"),
                        ast.Constant(value="12345-6789"),
                    ]
                )
            ],
        )
        assert clone_expr(node, clear_types=True) == expected

    def test_visit_hogqlx_explain_csp_report(self):
        node = self._select(
            "select <ExplainCSPReport properties={{'violated_directive': 'script-src', 'original_policy': 'script-src https://example.com'}} />"
        )
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        expected = ast.SelectQuery(
            select=[
                ast.Tuple(
                    exprs=[
                        ast.Constant(value="__hx_tag"),
                        ast.Constant(value="ExplainCSPReport"),
                        ast.Constant(value="properties"),
                        ast.Tuple(
                            exprs=[
                                ast.Constant(value="__hx_tag"),
                                ast.Constant(value="__hx_obj"),
                                ast.Constant(value="violated_directive"),
                                ast.Constant(value="script-src"),
                                ast.Constant(value="original_policy"),
                                ast.Constant(value="script-src https://example.com"),
                            ]
                        ),
                    ]
                ),
            ]
        )
        actual = clone_expr(node, clear_types=True)
        assert actual == expected, f"\nExpected:\n{expected}\n\nActual:\n{actual}"

    def test_visit_hogqlx_sparkline(self):
        node = self._select("select <Sparkline data={[1,2,3]} />")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        expected = ast.SelectQuery(
            select=[
                ast.Tuple(
                    exprs=[
                        ast.Constant(value="__hx_tag"),
                        ast.Constant(value="Sparkline"),
                        ast.Constant(value="data"),
                        ast.Tuple(
                            exprs=[
                                ast.Constant(value=1),
                                ast.Constant(value=2),
                                ast.Constant(value=3),
                            ]
                        ),
                    ]
                )
            ],
        )
        assert clone_expr(node, clear_types=True) == expected

    def test_visit_hogqlx_object(self):
        node = self._select("select {'key': {'key': 'value'}}")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        expected = ast.SelectQuery(
            select=[
                ast.Tuple(
                    exprs=[
                        ast.Constant(value="__hx_tag"),
                        ast.Constant(value="__hx_obj"),
                        ast.Constant(value="key"),
                        ast.Tuple(
                            exprs=[
                                ast.Constant(value="__hx_tag"),
                                ast.Constant(value="__hx_obj"),
                                ast.Constant(value="key"),
                                ast.Constant(value="value"),
                            ]
                        ),
                    ]
                )
            ],
        )
        assert clone_expr(node, clear_types=True) == expected

    def _assert_first_columm_is_type(self, node: ast.SelectQuery, type: ast.ConstantType):
        column_type = node.select[0].type
        assert column_type is not None
        assert column_type.resolve_constant_type(self.context) == type

    def test_types_pass_outside_subqueries_two_levels(self):
        node: ast.SelectQuery = self._select("select event from (select event from events)")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))

        assert node.select_from is not None
        assert node.select_from.table is not None

        self._assert_first_columm_is_type(cast(ast.SelectQuery, node.select_from.table), ast.StringType(nullable=False))
        self._assert_first_columm_is_type(node, ast.StringType(nullable=False))

    def test_types_pass_outside_subqueries_three_levels(self):
        node: ast.SelectQuery = self._select("select event from (select event from (select event from events))")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))

        assert node.select_from is not None
        assert node.select_from.table is not None

        self._assert_first_columm_is_type(cast(ast.SelectQuery, node.select_from.table), ast.StringType(nullable=False))
        self._assert_first_columm_is_type(node, ast.StringType(nullable=False))

    def test_arithmetic_types(self):
        node: ast.SelectQuery = self._select("select 1 + 2 as key from events")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        self._assert_first_columm_is_type(node, ast.IntegerType(nullable=False))

        node = self._select("select key from (select 1 + 2 as key from events)")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        self._assert_first_columm_is_type(node, ast.IntegerType(nullable=False))

        node = self._select("select 1.0 + 2.0 as key from events")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        self._assert_first_columm_is_type(node, ast.FloatType(nullable=False))

        node = self._select("select 100 + 2.0 as key from events")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        self._assert_first_columm_is_type(node, ast.FloatType(nullable=False))

        node = self._select("select 1.0 + 200 as key from events")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        self._assert_first_columm_is_type(node, ast.FloatType(nullable=False))

    def test_boolean_types(self):
        node: ast.SelectQuery = self._select("select true and false as key from events")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        self._assert_first_columm_is_type(node, ast.BooleanType(nullable=False))

        node = self._select("select key from (select true or false as key from events)")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        self._assert_first_columm_is_type(node, ast.BooleanType(nullable=False))

    def test_compare_types(self):
        node: ast.SelectQuery = self._select("select 1 < 2 from events")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        self._assert_first_columm_is_type(node, ast.BooleanType(nullable=False))

        node = self._select("select key from (select 3 = 4 as key from events)")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        self._assert_first_columm_is_type(node, ast.BooleanType(nullable=False))

        node = self._select("select key from (select 3 = null as key from events)")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        self._assert_first_columm_is_type(node, ast.BooleanType(nullable=False))

    def test_function_types(self):
        node: ast.SelectQuery = self._select("select abs(3) from events")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        self._assert_first_columm_is_type(node, ast.IntegerType(nullable=False))

        node = self._select("select plus(1, 2) from events")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        self._assert_first_columm_is_type(node, ast.IntegerType(nullable=False))

    def test_assume_not_null_type(self):
        node = self._select(f"SELECT assumeNotNull(toDateTime('2020-01-01 00:00:00'))")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))

        [selected] = node.select
        assert isinstance(selected.type, ast.CallType)
        assert selected.type.return_type == ast.DateTimeType(nullable=False)

    def test_interval_type_arithmetic(self):
        operators = ["+", "-"]
        granularites = ["Second", "Minute", "Hour", "Day", "Week", "Month", "Quarter", "Year"]
        exprs = []
        for granularity in granularites:
            for operator in operators:
                exprs.append(f"timestamp {operator} toInterval{granularity}(1)")

        node = self._select(f"""SELECT {",".join(exprs)} FROM events""")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))

        assert len(node.select) == len(exprs)
        for selected in node.select:
            assert selected.type == ast.DateTimeType(nullable=False)

    def test_recording_button_tag(self):
        node: ast.SelectQuery = self._select(
            "select <RecordingButton sessionId={'12345'} recordingStatus={'active'} />"
        )
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))

        node2 = self._select("select recordingButton('12345', 'active')")
        node2 = cast(ast.SelectQuery, resolve_types(node2, self.context, dialect="clickhouse"))
        assert node == node2

    def test_explain_csp_report_tag(self):
        node: ast.SelectQuery = self._select(
            "select <ExplainCSPReport properties={{'violated_directive': 'script-src', 'original_policy': 'script-src https://example.com'}} />"
        )
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))

        node2 = self._select(
            "select explainCSPReport({'violated_directive': 'script-src', 'original_policy': 'script-src https://example.com'})"
        )
        node2 = cast(ast.SelectQuery, resolve_types(node2, self.context, dialect="clickhouse"))
        assert node == node2

    def test_sparkline_tag(self):
        node: ast.SelectQuery = self._select("select <Sparkline data={[1,2,3]} />")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))

        node2 = self._select("select sparkline((1,2,3))")
        node2 = cast(ast.SelectQuery, resolve_types(node2, self.context, dialect="clickhouse"))
        assert node == node2

    def test_globals(self):
        context = HogQLContext(
            team_id=self.team.pk, database=self.database, globals={"globalVar": 1}, enable_select_queries=True
        )
        node: ast.SelectQuery = self._select("select globalVar from events")
        node = cast(ast.SelectQuery, resolve_types(node, context, dialect="clickhouse"))
        self._assert_first_columm_is_type(node, ast.IntegerType(nullable=False))
        assert isinstance(node.select[0], ast.Constant)
        assert node.select[0].value == 1
        query = print_prepared_ast(node, context, "hogql")
        assert "SELECT 1 FROM events LIMIT " in query

    def test_globals_nested(self):
        context = HogQLContext(
            team_id=self.team.pk,
            database=self.database,
            globals={"globalVar": {"nestedVar": "banana"}},
            enable_select_queries=True,
        )
        node: ast.SelectQuery = self._select("select globalVar.nestedVar from events")
        node = cast(ast.SelectQuery, resolve_types(node, context, dialect="clickhouse"))
        self._assert_first_columm_is_type(node, ast.StringType(nullable=False))
        assert isinstance(node.select[0], ast.Constant)
        assert node.select[0].value == "banana"
        query = print_prepared_ast(node, context, "hogql")
        assert "SELECT 'banana' FROM events LIMIT " in query

    def test_globals_nested_error(self):
        context = HogQLContext(
            team_id=self.team.pk, database=self.database, globals={"globalVar": 1}, enable_select_queries=True
        )
        node: ast.SelectQuery = self._select("select globalVar.nested from events")
        with self.assertRaises(QueryError) as ctx:
            node = cast(ast.SelectQuery, resolve_types(node, context, dialect="clickhouse"))
        self.assertEqual(str(ctx.exception), "Cannot resolve field: globalVar.nested")

    def test_property_access_with_arrays_zero_index_error(self):
        query = f"SELECT properties.something[0] FROM events"
        context = HogQLContext(
            team_id=self.team.pk, database=self.database, globals={"globalVar": 1}, enable_select_queries=True
        )
        with self.assertRaisesMessage(
            QueryError,
            "SQL indexes start from one, not from zero. E.g: array[1]",
        ):
            node: ast.SelectQuery = self._select(query)
            resolve_types(node, context, dialect="clickhouse")

    def test_property_access_with_tuples_zero_index_error(self):
        query = f"SELECT properties.something.0 FROM events"
        context = HogQLContext(
            team_id=self.team.pk, database=self.database, globals={"globalVar": 1}, enable_select_queries=True
        )
        with self.assertRaisesMessage(
            QueryError,
            "SQL indexes start from one, not from zero. E.g: array.1",
        ):
            node: ast.SelectQuery = self._select(query)
            resolve_types(node, context, dialect="clickhouse")

    def test_nested_table_name(self):
        table_group = TableNode(
            children={
                "nested": TableNode(
                    name="nested",
                    children={"events": TableNode(name="events", table=EventsTable())},
                )
            },
        )
        self.database.tables.merge_with(table_group)

        query = "SELECT * FROM nested.events"
        resolve_types(self._select(query), self.context, dialect="hogql")

    def test_deeply_nested_table_name(self):
        table_group = TableNode(
            children={
                "very": TableNode(
                    name="very",
                    children={
                        "deeply": TableNode(
                            name="deeply",
                            children={
                                "nested": TableNode(
                                    name="nested",
                                    children={"events": TableNode(name="events", table=EventsTable())},
                                )
                            },
                        )
                    },
                )
            },
        )
        self.database.tables.merge_with(table_group)

        query = "SELECT * FROM very.deeply.nested.events"
        resolve_types(self._select(query), self.context, dialect="hogql")

    def test_nested_table_on_existing_table(self):
        table_group = TableNode(
            children={
                "events": TableNode(
                    name="events",
                    table=EventsTable(),
                    children={"copy": TableNode(name="copy", table=EventsTable())},
                )
            },
        )
        self.database.tables.merge_with(table_group)

        query = "SELECT * FROM events"
        resolve_types(self._select(query), self.context, dialect="hogql")

        query = "SELECT * FROM events.copy"
        resolve_types(self._select(query), self.context, dialect="hogql")

    def test_lambda_scope(self):
        query = "SELECT arrayMap(a -> e.timestamp, [1]) as a FROM events e"
        resolve_types(self._select(query), self.context, dialect="hogql")
        resolve_types(self._select(query), self.context, dialect="clickhouse")

    def test_lambda_scope_mixed_scopes(self):
        query = "SELECT arrayMap(a -> concat(a, e.event), ['str']) FROM events e"
        resolve_types(self._select(query), self.context, dialect="hogql")
        resolve_types(self._select(query), self.context, dialect="clickhouse")
