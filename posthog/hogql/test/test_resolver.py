from datetime import UTC, date, datetime
from typing import Any, Optional, cast
from uuid import UUID

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest

from django.test import override_settings

from parameterized import parameterized

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
from posthog.hogql.database.schema.persons import PersonsTable
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast, print_prepared_ast
from posthog.hogql.resolver import ResolutionError, resolve_types
from posthog.hogql.resolver_utils import extract_base_table_types
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

    def test_resolve_table_column_aliases_dialect_guard(self):
        expr = self._select("SELECT 1 FROM events AS e (event_alias)")

        # Resolver allows column_aliases in any dialect; the printer enforces the dialect guard
        resolved = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="clickhouse"))
        assert isinstance(resolved.select_from, ast.JoinExpr)
        assert resolved.select_from.column_aliases == ["event_alias"]

        resolved = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="postgres"))
        assert isinstance(resolved.select_from, ast.JoinExpr)
        assert resolved.select_from.column_aliases == ["event_alias"]

    def test_resolve_limit_percent_dialect_guard(self):
        expr = self._select("SELECT 1 FROM events LIMIT 10 %")

        resolved = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="clickhouse"))
        assert resolved.limit_percent is True

        resolved = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="postgres"))
        assert resolved.limit_percent is True

    def test_resolve_limit_percent_expression_guard_clickhouse(self):
        expr = self._select("SELECT 1 FROM events LIMIT (60 + 7) %")

        with self.assertRaises(QueryError) as context:
            resolve_types(expr, self.context, dialect="clickhouse")
        self.assertEqual(
            str(context.exception),
            "LIMIT percent with expressions is not supported in clickhouse dialect",
        )

    def test_resolve_limit_percent_range_guard(self):
        expr = self._select("SELECT 1 FROM events LIMIT (100.1) %")

        with self.assertRaises(QueryError) as context:
            resolve_types(expr, self.context, dialect="postgres")
        self.assertEqual(
            str(context.exception),
            "Limit percent must be between 0 and 100",
        )

    @parameterized.expand(
        [
            ("current_date",),
            ("current_time",),
            ("current_timestamp",),
            ("localtime",),
            ("localtimestamp",),
        ]
    )
    def test_postgres_current_date_keyword_resolves_to_keyword(self, keyword: str):
        expr = self._select(f"SELECT {keyword}")
        resolved = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="postgres"))

        assert len(resolved.select) == 1
        select_expr = resolved.select[0]
        assert isinstance(select_expr, ast.Keyword)
        assert select_expr.name == keyword

    def test_postgres_current_date_alias_not_treated_as_keyword(self):
        expr = self._select(
            """
            SELECT
                distinct_id as current_date
            FROM
                events
            WHERE
                current_date is not null
            """
        )
        resolved = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="postgres"))

        assert isinstance(resolved.where, ast.CompareOperation)
        left = resolved.where.left
        if isinstance(left, ast.Alias):
            left = left.expr
        assert isinstance(left, ast.Field)

    @parameterized.expand(
        [
            ("events.created_at", None),
            ("created_at", None),
            ("e.created_at", "e"),
            ("events.created_at", "e"),
        ]
    )
    def test_resolve_exclude_qualified_columns(self, exclude, alias):
        expr = ast.SelectQuery(
            select=[ast.ColumnsExpr(all_columns=True, exclude=[exclude])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"]), alias=alias),
        )

        resolved = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="clickhouse"))
        selected_names = [str(field.chain[-1]) for field in resolved.select if isinstance(field, ast.Field)]
        assert "created_at" not in selected_names

    def test_resolve_exclude_missing_column(self):
        expr = ast.SelectQuery(
            select=[ast.ColumnsExpr(all_columns=True, exclude=["first_names"])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        )

        with self.assertRaises(QueryError) as context:
            resolve_types(expr, self.context, dialect="clickhouse")
        self.assertEqual(
            str(context.exception),
            'Column "first_names" in EXCLUDE list was not found in events',
        )

    def test_resolve_exclude_with_column_aliases(self):
        expr = ast.SelectQuery(
            select=[ast.ColumnsExpr(all_columns=True, exclude=["a", "b", "c"])],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"]),
                alias="c",
                column_aliases=["a", "b", "c"],
            ),
        )

        resolved = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="postgres"))
        selected_names = [str(field.chain[-1]) for field in resolved.select if isinstance(field, ast.Field)]
        assert "a" not in selected_names
        assert "b" not in selected_names
        assert "c" not in selected_names

    def test_resolve_replace_columns(self):
        expr = self._select("SELECT (* REPLACE (1 AS event)) FROM events")

        resolved = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="postgres"))
        selected_names = [str(field.chain[-1]) for field in resolved.select if isinstance(field, ast.Field)]
        assert "event" not in selected_names

        aliases = [alias for alias in resolved.select if isinstance(alias, ast.Alias)]
        assert any(
            alias.alias == "event" and isinstance(alias.expr, ast.Constant) and alias.expr.value == 1
            for alias in aliases
        )

    def test_resolve_replace_columns_with_exclude(self):
        expr = self._select("SELECT (* EXCLUDE (uuid) REPLACE (1 AS event)) FROM events")

        resolved = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="postgres"))
        selected_names = [str(field.chain[-1]) for field in resolved.select if isinstance(field, ast.Field)]
        assert "uuid" not in selected_names
        assert "event" not in selected_names

        aliases = [alias for alias in resolved.select if isinstance(alias, ast.Alias)]
        assert any(
            alias.alias == "event" and isinstance(alias.expr, ast.Constant) and alias.expr.value == 1
            for alias in aliases
        )

    def test_resolve_replace_missing_column(self):
        expr = self._select("SELECT (* REPLACE (1 AS does_not_exist)) FROM events")

        with self.assertRaises(QueryError) as context:
            resolve_types(expr, self.context, dialect="postgres")
        self.assertEqual(
            str(context.exception),
            'Column "does_not_exist" in REPLACE list was not found in events',
        )

    def test_resolve_replace_exclude_same_column(self):
        expr = self._select("SELECT (* EXCLUDE (event) REPLACE (1 AS event)) FROM events")

        with self.assertRaises(QueryError) as context:
            resolve_types(expr, self.context, dialect="postgres")
        self.assertEqual(
            str(context.exception),
            'Column "event" cannot occur in both EXCLUDE and REPLACE list',
        )

    def test_resolve_replace_expression_references_excluded_column(self):
        expr = self._select("SELECT (* EXCLUDE (event) REPLACE (concat(event, 'x') AS other)) FROM events")

        with self.assertRaises(QueryError) as context:
            resolve_types(expr, self.context, dialect="postgres")
        self.assertEqual(
            str(context.exception),
            'Replace expression for "other" cannot reference excluded column "event"',
        )

    def test_resolve_replace_with_column_aliases_success(self):
        expr = self._select(
            "SELECT (* REPLACE (0 AS a)) FROM (SELECT 1 AS customer_id, 2 AS b, 3 AS c) AS customers (a, b, c)"
        )

        resolved = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="postgres"))
        selected_names = [str(field.chain[-1]) for field in resolved.select if isinstance(field, ast.Field)]
        assert "a" not in selected_names
        aliases = [alias for alias in resolved.select if isinstance(alias, ast.Alias)]
        assert any(
            alias.alias == "a" and isinstance(alias.expr, ast.Constant) and alias.expr.value == 0 for alias in aliases
        )

    def test_resolve_replace_with_column_aliases_missing_column(self):
        expr = self._select(
            "SELECT (* REPLACE (0 AS customer_id)) FROM (SELECT 1 AS customer_id, 2 AS b, 3 AS c) AS customers (a, b, c)"
        )

        with self.assertRaises(QueryError) as context:
            resolve_types(expr, self.context, dialect="postgres")
        self.assertEqual(
            str(context.exception),
            'Column "customer_id" in REPLACE list was not found in customers',
        )

    def test_resolve_unpivot_tuple_shape_guard(self):
        expr = self._select(
            "SELECT field_name, field_value FROM events UNPIVOT ((field_value) FOR field_name IN ((event, uuid)))"
        )

        with self.assertRaises(QueryError) as context:
            resolve_types(expr, self.context, dialect="postgres")
        self.assertEqual(
            str(context.exception),
            "UNPIVOT value and name columns must both be tuples or both be single columns",
        )

    def test_resolve_unpivot_tuple_length_guard(self):
        expr = self._select(
            "SELECT field_name, field_value FROM events UNPIVOT ((field_value, other_value) FOR (field_name, other_name) IN ((event)))"
        )

        with self.assertRaises(QueryError) as context:
            resolve_types(expr, self.context, dialect="postgres")
        self.assertEqual(
            str(context.exception),
            "UNPIVOT IN values must be tuples of length 2",
        )

    def test_resolve_lambda_style_dialect_guard(self):
        expr = self._select("SELECT lambda x: x + 1")

        resolved = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="clickhouse"))
        assert isinstance(resolved.select[0], ast.Lambda)

        resolved = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="postgres"))
        assert isinstance(resolved.select[0], ast.Lambda)

    def test_resolve_array_slice_dialect_guard(self):
        expr = self._select("SELECT [1, 2, 3][1:2]")

        resolved = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="clickhouse"))
        assert isinstance(resolved.select[0], ast.ArraySlice)

        resolved = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="postgres"))
        assert isinstance(resolved.select[0], ast.ArraySlice)

    def test_resolve_try_cast_dialect_guard(self):
        expr = self._select("SELECT try_cast(1 AS Int64)")

        with self.assertRaises(QueryError) as context:
            resolve_types(expr, self.context, dialect="clickhouse")
        self.assertEqual(str(context.exception), "TRY_CAST is not allowed in clickhouse dialect")

        resolved = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="postgres"))
        assert isinstance(resolved.select[0], ast.TryCast)

    def test_resolve_is_distinct_from_unresolved_field(self):
        expr = self._select("SELECT missing is distinct from 1")
        with self.assertRaises(QueryError) as context:
            resolve_types(expr, self.context, dialect="clickhouse")
        self.assertEqual(str(context.exception), "Unable to resolve field: missing")

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

    def test_resolve_cte_types(self):
        node = self._select("with cte as (select event from events) select event from cte")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        assert isinstance(node.select[0], ast.Alias)

        printed = self._print_hogql("with cte as (select event from events) select event from cte")

        assert printed == "WITH cte AS (SELECT event FROM events) SELECT event FROM cte LIMIT 50000"

    @parameterized.expand(
        [
            ("SELECT event FROM (SELECT event FROM events) AS e", ["events"]),
            ("WITH event_cte AS (SELECT event FROM events) SELECT event FROM event_cte", ["events"]),
        ]
    )
    def test_extract_base_table_types(self, query: str, expected_tables: list[str]):
        node = self._select(query)
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))

        assert node.type is not None
        table_names = [table_type.table.to_printed_hogql() for table_type in extract_base_table_types(node.type)]

        self.assertEqual(table_names, expected_tables)

    def test_extract_base_table_types_from_select_set_type(self):
        select_set_type = ast.SelectSetQueryType(
            types=[
                ast.SelectQueryType(tables={"events": ast.TableType(table=EventsTable())}),
                ast.SelectQueryType(tables={"persons": ast.TableType(table=PersonsTable())}),
            ]
        )

        table_names = [table_type.table.to_printed_hogql() for table_type in extract_base_table_types(select_set_type)]

        self.assertEqual(table_names, ["events", "persons"])

    def test_select_set_order_by_prints(self):
        printed = self._print_hogql("select 1 union all select 2 order by 1")
        self.assertEqual(printed, "SELECT 1 LIMIT 50000 UNION ALL SELECT 2 ORDER BY 1 ASC LIMIT 50000")

    def test_ctes_loop(self):
        with self.assertRaises(QueryError) as e:
            self._print_hogql("with cte as (select * from cte) select * from cte")
        self.assertIn("Unknown table `cte`.", str(e.exception))

    def test_ctes_basic_column(self):
        expr = self._print_hogql("with 1 as cte select cte from events")
        self.assertEqual(expr, "WITH 1 AS cte SELECT cte FROM events LIMIT 50000")

    def test_ctes_recursive_column(self):
        self.assertEqual(
            self._print_hogql("with 1 as cte, cte as soap select soap from events"),
            "WITH 1 AS cte, cte AS soap SELECT soap FROM events LIMIT 50000",
        )

    def test_ctes_field_access(self):
        with self.assertRaises(QueryError) as e:
            self._print_hogql("with properties as cte select cte.$browser from events")
        self.assertIn("No scope or CTE available", str(e.exception))

    def test_ctes_subqueries(self):
        self.assertEqual(
            self._print_hogql("with my_table as (select event from events) select event from my_table"),
            "WITH my_table AS (SELECT event FROM events) SELECT event FROM my_table LIMIT 50000",
        )

        self.assertEqual(
            self._print_hogql(
                "with my_table as (select timestamp from events) select my_table.timestamp from my_table"
            ),
            "WITH my_table AS (SELECT timestamp FROM events) SELECT my_table.timestamp FROM my_table LIMIT 50000",
        )

        self.assertEqual(
            self._print_hogql("with my_table as (select timestamp from events) select timestamp from my_table"),
            "WITH my_table AS (SELECT timestamp FROM events) SELECT timestamp FROM my_table LIMIT 50000",
        )

    def test_ctes_subquery_deep(self):
        self.assertEqual(
            self._print_hogql(
                "with my_table as (select event from events), "
                "other_table as (select event from (select event from (select event from my_table))) "
                "select event from other_table"
            ),
            "WITH my_table AS (SELECT event FROM events), other_table AS (SELECT event FROM (SELECT event FROM (SELECT event FROM my_table))) SELECT event FROM other_table LIMIT 50000",
        )

    def test_ctes_subquery_recursion(self):
        self.assertEqual(
            self._print_hogql(
                "with users as (select event, timestamp as tt from events ), final as ( select tt from users ) select * from final"
            ),
            "WITH users AS (SELECT event, timestamp AS tt FROM events), final AS (SELECT tt FROM users) SELECT tt FROM final LIMIT 50000",
        )

    def test_ctes_with_aliases(self):
        self.assertEqual(
            self._print_hogql(
                "WITH initial_alias AS (SELECT 1 AS a) SELECT a FROM initial_alias AS new_alias WHERE new_alias.a=1"
            ),
            "WITH initial_alias AS (SELECT 1 AS a) SELECT a FROM initial_alias AS new_alias WHERE equals(new_alias.a, 1) LIMIT 50000",
        )

    def test_ctes_with_aliases_in_joins(self):
        self.assertEqual(
            self._print_hogql(
                """
                WITH
                    exposures AS (SELECT event AS person_id, timestamp AS exposure_time FROM events),
                    conversions AS (SELECT event AS person_id, timestamp AS conversion_time FROM events)
                SELECT
                    e.person_id,
                    e.exposure_time,
                    c.conversion_time
                FROM exposures AS e
                LEFT JOIN conversions AS c ON e.person_id = c.person_id AND c.conversion_time >= e.exposure_time
                """
            ),
            "WITH exposures AS (SELECT event AS person_id, timestamp AS exposure_time FROM events), "
            "conversions AS (SELECT event AS person_id, timestamp AS conversion_time FROM events) "
            "SELECT e.person_id, e.exposure_time, c.conversion_time "
            "FROM exposures AS e LEFT JOIN conversions AS c "
            "ON and(equals(e.person_id, c.person_id), greaterOrEquals(c.conversion_time, e.exposure_time)) "
            "LIMIT 50000",
        )

        self.assertEqual(
            self._print_hogql(
                """
                WITH
                    users AS (SELECT event AS user_id FROM events)
                SELECT
                    users.user_id,
                    u2.user_id
                FROM users
                LEFT JOIN users AS u2 ON users.user_id = u2.user_id
                """
            ),
            "WITH users AS (SELECT event AS user_id FROM events) "
            "SELECT users.user_id, u2.user_id "
            "FROM users LEFT JOIN users AS u2 ON equals(users.user_id, u2.user_id) "
            "LIMIT 50000",
        )

    def test_ctes_with_union_all(self):
        union_printed = self._print_hogql(
            """
                WITH cte1 AS (SELECT 1 AS a)
                SELECT 1 AS a
                UNION ALL
                WITH cte2 AS (SELECT 2 AS a)
                SELECT * FROM cte2
                UNION ALL
                WITH cte1 AS (SELECT 1 AS a)
                SELECT * FROM cte1
                    """
        )

        self.assertEqual(
            union_printed,
            "WITH cte1 AS (SELECT 1 AS a) SELECT 1 AS a LIMIT 50000 UNION ALL WITH cte2 AS (SELECT 2 AS a) SELECT a FROM cte2 LIMIT 50000 UNION ALL WITH cte1 AS (SELECT 1 AS a) SELECT a FROM cte1 LIMIT 50000",
        )

    def test_root_ctes_propagate_to_union_branches(self):
        # Root WITH propagates to all branches; branch-level CTEs shadow root CTEs
        printed = self._print_hogql(
            """
            WITH page_view_stats AS (SELECT 1 AS a)
            SELECT * FROM page_view_stats
            UNION ALL
            WITH purchase_stats AS (SELECT 2 AS a)
            SELECT * FROM page_view_stats
            """
        )
        self.assertEqual(
            printed,
            "WITH page_view_stats AS (SELECT 1 AS a) SELECT a FROM page_view_stats LIMIT 50000 UNION ALL WITH purchase_stats AS (SELECT 2 AS a) SELECT a FROM page_view_stats LIMIT 50000",
        )

    def test_with_clause_before_parens_select_set(self):
        printed = self._print_hogql("WITH cte AS (SELECT 1 AS a) (SELECT a FROM cte UNION ALL SELECT a FROM cte)")
        self.assertEqual(
            printed,
            "WITH cte AS (SELECT 1 AS a) SELECT a FROM cte LIMIT 50000 UNION ALL SELECT a FROM cte LIMIT 50000",
        )

    def test_ctes_scalar_subquery(self):
        self.assertEqual(
            self._print_hogql("WITH (SELECT 1) AS x SELECT x FROM events"),
            "WITH (SELECT 1) AS x SELECT x FROM events LIMIT 50000",
        )

        self.assertEqual(
            self._print_hogql("WITH (SELECT count() FROM events) AS event_count SELECT event_count FROM events"),
            "WITH (SELECT count() FROM events) AS event_count SELECT event_count FROM events LIMIT 50000",
        )

        self.assertEqual(
            self._print_hogql(
                "WITH params AS (SELECT 1 AS a, 2 AS b), "
                "(SELECT a FROM params) AS val_a, "
                "(SELECT b FROM params) AS val_b "
                "SELECT val_a + val_b FROM events"
            ),
            "WITH params AS (SELECT 1 AS a, 2 AS b), (SELECT a FROM params) AS val_a, (SELECT b FROM params) AS val_b SELECT plus(val_a, val_b) FROM events LIMIT 50000",
        )

    def test_ctes_with_scalar_subquery_column(self):
        # A table CTE that uses a scalar subquery as a SELECT column,
        # then referenced by another CTE — the resolver must unwrap
        # SelectQueryType to determine the column's field type
        self._print_hogql(
            "WITH latest AS (SELECT max(timestamp) AS ts FROM events), "
            "date_info AS ("
            "  SELECT (SELECT ts FROM latest) AS period_end FROM events"
            ") "
            "SELECT d.period_end FROM date_info d CROSS JOIN events e"
        )

    def test_ctes_table_subquery_as_scalar_error(self):
        with self.assertRaises(QueryError) as e:
            self._print_hogql("WITH x AS (SELECT 1) SELECT x FROM events")
        self.assertIn("Cannot use table CTE", str(e.exception))

    def test_ctes_in_subquery_for_clickhouse(self):
        # Test that CTEs defined in a subquery remain with that subquery for ClickHouse
        # This is necessary because CTEs get resolved with context-specific JOINs
        # (e.g., person_id triggers events__override LEFT JOIN)

        # Parse and prepare for ClickHouse dialect
        from posthog.hogql.context import HogQLContext
        from posthog.hogql.printer import prepare_and_print_ast

        query_str = "SELECT * FROM (WITH cte1 AS (SELECT 1 AS x) SELECT x FROM cte1) AS source"
        query = self._select(query_str)
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)

        # Prepare and print in one go
        sql, prepared = prepare_and_print_ast(query, context, "clickhouse")

        # Verify the subquery still has its CTE
        assert isinstance(prepared, ast.SelectQuery)
        assert prepared.select_from is not None
        assert isinstance(prepared.select_from, ast.JoinExpr)
        assert isinstance(prepared.select_from.table, ast.SelectQuery)
        subquery = prepared.select_from.table
        assert subquery.ctes is not None
        assert "cte1" in subquery.ctes

        # The CTE should appear inside the subquery parentheses in the SQL
        assert "WITH cte1 AS" in sql
        assert "FROM (WITH cte1 AS" in sql  # CTE is inside the subquery parentheses
        assert ") AS source" in sql  # Subquery is aliased as source

    def test_ctes_in_subquery_prevent_name_conflicts(self):
        # Test that CTEs in nested scopes can have the same name without conflict
        # since they're not hoisted
        query_str = (
            "WITH cte1 AS (SELECT 1 AS a) "
            "SELECT source.b, cte1.a FROM (WITH cte1 AS (SELECT 2 AS b) SELECT b FROM cte1) AS source, cte1"
        )

        # This should not raise an error since CTEs are in different scopes
        result = self._print_hogql(query_str)
        # Both CTEs should be present in the output
        assert "cte1" in result
        # The outer CTE and inner CTE should both exist
        assert "WITH cte1 AS (SELECT 1 AS a)" in result
        assert "(WITH cte1 AS (SELECT 2 AS b)" in result

    def test_ctes_with_person_id_in_subquery(self):
        # Test that mimics the experiment query structure where a CTE references person_id
        # and the query gets wrapped as a subquery. This tests that events__override JOIN
        # is added correctly within the CTE's scope.
        from posthog.hogql.printer import prepare_and_print_ast

        # Build a query with a CTE that references person_id, then wrap it
        query_str = """
            SELECT * FROM (
                WITH exposures AS (
                    SELECT person_id AS entity_id, event
                    FROM events
                    WHERE team_id = 1
                )
                SELECT entity_id FROM exposures
            ) AS source
        """
        query = self._select(query_str)

        # Prepare and print in one go
        sql, prepared = prepare_and_print_ast(query, self.context, "clickhouse")

        # Check that the subquery has the CTE
        assert isinstance(prepared, ast.SelectQuery)
        assert prepared.select_from is not None
        assert isinstance(prepared.select_from, ast.JoinExpr)
        assert isinstance(prepared.select_from.table, ast.SelectQuery)
        subquery = prepared.select_from.table
        assert subquery.ctes is not None
        assert "exposures" in subquery.ctes

        # The CTE should be in the subquery
        assert "FROM (WITH exposures AS" in sql or "FROM (\n    WITH exposures AS" in sql.replace("  ", " ")

        # The CTE should have the events__override LEFT JOIN
        # (The resolver automatically adds this when it sees person_id references)
        assert "events__override" in sql
        assert "LEFT" in sql.upper()

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
        assert cast(ast.Alias, constraint.expr).alias == "a"

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

    @parameterized.expand(
        [
            ("regex", "select COLUMNS('time') from events", ["timestamp"]),
            ("regex_caret", "select COLUMNS('^event$') from events", ["event"]),
            ("list", "select COLUMNS(event, timestamp) from events", ["event", "timestamp"]),
            ("subquery", "select COLUMNS('a') from (select 1 as a1, 2 as a2, 3 as b1)", ["a1", "a2"]),
        ]
    )
    def test_columns_expr_resolves(self, _name: str, query: str, expected_names: list[str]):
        node = self._select(query)
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        column_names = [
            col.type.name if isinstance(col.type, ast.FieldType) else cast(ast.Alias, col).alias for col in node.select
        ]
        assert sorted(column_names) == sorted(expected_names)

    def test_columns_expr_no_match_raises(self):
        node = self._select("select COLUMNS('^nonexistent_xyz$') from events")
        with self.assertRaises(QueryError) as e:
            resolve_types(node, self.context, dialect="clickhouse")
        assert "No columns matched" in str(e.exception)

    def test_columns_expr_subquery(self):
        node = self._select("select COLUMNS('a') from (select 1 as a1, 2 as a2, 3 as b1)")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        column_names = [
            col.type.name if isinstance(col.type, ast.FieldType) else cast(ast.Alias, col).alias for col in node.select
        ]
        assert sorted(column_names) == ["a1", "a2"]

    @parameterized.expand(
        [
            (
                "regex",
                "select coalesce(*COLUMNS('a')) from (select 1 as a1, 2 as a2, 3 as b1)",
                "coalesce",
                ["a1", "a2"],
            ),
            (
                "list",
                "select coalesce(*COLUMNS(event, timestamp)) from events",
                "coalesce",
                ["event", "timestamp"],
            ),
        ]
    )
    def test_spread_columns_in_function_call(self, _name, query, expected_fn, expected_args):
        node = self._select(query)
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        call = node.select[0]
        assert isinstance(call, ast.Call)
        assert call.name == expected_fn
        assert len(call.args) == len(expected_args)
        arg_names = [
            arg.type.name if isinstance(arg.type, ast.FieldType) else arg.type.alias
            for arg in call.args
            if isinstance(arg.type, (ast.FieldType, ast.FieldAliasType))
        ]
        assert sorted(arg_names) == sorted(expected_args)

    @parameterized.expand(
        [
            (
                "top_level",
                "select *COLUMNS('^event$') from events",
                "*COLUMNS",
            ),
            (
                "no_match",
                "select coalesce(*COLUMNS('^nonexistent$')) from events",
                "No columns matched",
            ),
        ]
    )
    def test_spread_columns_raises(self, _name, query, expected_msg):
        with self.assertRaises(QueryError) as e:
            node = self._select(query)
            resolve_types(node, self.context, dialect="clickhouse")
        assert expected_msg in str(e.exception)

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

    @parameterized.expand(
        [
            ("year", ast.DateType),
            ("quarter", ast.DateType),
            ("month", ast.DateType),
            ("week", ast.DateType),
            ("day", ast.DateTimeType),
            ("hour", ast.DateTimeType),
            ("minute", ast.DateTimeType),
            ("second", ast.DateTimeType),
        ]
    )
    def test_date_trunc_return_type(self, unit, expected_type):
        node = self._select(f"select dateTrunc('{unit}', timestamp) from events")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))
        self._assert_first_columm_is_type(node, expected_type(nullable=False))

    def test_assume_not_null_type(self):
        node = self._select(f"SELECT assumeNotNull(toDateTime('2020-01-01 00:00:00'))")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))

        [selected] = node.select
        assert isinstance(selected.type, ast.CallType)
        assert selected.type.return_type == ast.DateTimeType(nullable=False)

    def test_assume_not_null_with_unknown_arg_type(self):
        # When the inner function has no signatures (returns UnknownType), assumeNotNull should still force nullable=False
        node = self._select("SELECT assumeNotNull(base64Encode(unhex('DEADBEEF')))")
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))

        [selected] = node.select
        assert isinstance(selected.type, ast.CallType)
        assert selected.type.return_type.nullable is False

    @parameterized.expand(
        [
            ("toNullable('hello')", ""),
            ("toNullable(event)", "FROM events"),
            ("nullIf(event, '')", "FROM events"),
        ],
    )
    def test_nullable_functions_force_nullable_true(self, expr, from_clause):
        node = self._select(f"SELECT {expr} {from_clause}".strip())
        node = cast(ast.SelectQuery, resolve_types(node, self.context, dialect="clickhouse"))

        [selected] = node.select
        assert isinstance(selected.type, ast.CallType)
        assert selected.type.return_type.nullable is True

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

    def test_virtual_property_mapping(self):
        queries = [
            (
                "groups virtual prop",
                "SELECT properties.$virt_revenue FROM groups ORDER BY key ASC",
                ["$virt_revenue"],
            ),
            (
                "persons virtual prop from events",
                "SELECT person.properties.$virt_revenue FROM events",
                ["person", "$virt_revenue"],
            ),
            (
                "regular props are not affected",
                "SELECT properties.regular_prop FROM events",
                ["properties", "regular_prop"],
            ),
        ]
        for msg, query, expected_chain in queries:
            with self.subTest(msg):
                expr = self._select(query)
                resolved_expr = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="clickhouse"))

                revenue_field = resolved_expr.select[0]
                assert isinstance(revenue_field, ast.Alias)
                assert isinstance(revenue_field.expr, ast.Field)
                chain = revenue_field.expr.chain
                assert chain == expected_chain

    def test_cte_column_name_list_resolves_columns(self):
        expr = self._select("WITH stats(a, b) AS (SELECT 'x', 'y') SELECT a, b FROM stats")
        resolved = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="postgres"))

        # The resolved CTE's inner select should have the column names from the list
        assert resolved.ctes is not None
        cte = resolved.ctes["stats"]
        assert isinstance(cte.expr, ast.SelectQuery)
        assert isinstance(cte.expr.type, ast.SelectQueryType)
        assert list(cte.expr.type.columns.keys()) == ["a", "b"]

    def test_cte_column_name_list_overrides_existing_aliases(self):
        expr = self._select(
            "WITH stats(a, b) AS (SELECT event AS orig_a, timestamp AS orig_b FROM events) SELECT a, b FROM stats"
        )
        resolved = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="postgres"))

        assert resolved.ctes is not None
        cte = resolved.ctes["stats"]
        assert isinstance(cte.expr, ast.SelectQuery)
        assert isinstance(cte.expr.type, ast.SelectQueryType)
        assert list(cte.expr.type.columns.keys()) == ["a", "b"]

    def test_cte_column_name_list_qualified_access(self):
        expr = self._select("WITH stats(a, b) AS (SELECT 'x', 'y') SELECT stats.a, stats.b FROM stats")
        resolved = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="postgres"))

        assert len(resolved.select) == 2
        for i, name in enumerate(["a", "b"]):
            col = resolved.select[i]
            assert isinstance(col, ast.Alias)
            assert col.alias == name
            assert isinstance(col.expr, ast.Field)
            assert isinstance(col.expr.type, ast.FieldType)
            assert col.expr.type.name == name

    def test_cte_column_name_list_mismatch(self):
        query = "WITH stats (a, b, c) AS (SELECT 'a', 'b') SELECT a FROM stats"
        with self.assertRaisesMessage(
            QueryError,
            "CTE 'stats' has 2 column(s) but 3 column name(s) were provided",
        ):
            resolve_types(self._select(query), self.context, dialect="postgres")

        query = "WITH stats (a) AS (SELECT 'a', 'b') SELECT a FROM stats"
        with self.assertRaisesMessage(
            QueryError,
            "CTE 'stats' has 2 column(s) but 1 column name(s) were provided",
        ):
            resolve_types(self._select(query), self.context, dialect="postgres")

    def test_cte_column_name_list_union_all_resolves_columns(self):
        expr = self._select("WITH stats(a, b) AS (SELECT 'x', 'y' UNION ALL SELECT 'p', 'q') SELECT a, b FROM stats")
        resolved = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="postgres"))

        assert resolved.ctes is not None
        cte = resolved.ctes["stats"]
        assert isinstance(cte.expr, ast.SelectSetQuery)
        assert isinstance(cte.expr.type, ast.SelectSetQueryType)
        first_type = cte.expr.type.types[0]
        while isinstance(first_type, ast.SelectSetQueryType):
            first_type = first_type.types[0]
        assert list(first_type.columns.keys()) == ["a", "b"]

    @parameterized.expand(
        [
            (
                "too_many",
                "WITH stats (a, b, c) AS (SELECT 'x', 'y' UNION ALL SELECT 'p', 'q') SELECT a FROM stats",
                2,
                3,
            ),
            ("too_few", "WITH stats (a) AS (SELECT 'x', 'y' UNION ALL SELECT 'p', 'q') SELECT a FROM stats", 2, 1),
        ]
    )
    def test_cte_column_name_list_union_all_mismatch(self, _name, query, n_cols, n_names):
        with self.assertRaisesMessage(
            QueryError,
            f"CTE 'stats' has {n_cols} column(s) but {n_names} column name(s) were provided",
        ):
            resolve_types(self._select(query), self.context, dialect="postgres")

    def test_cte_using_key_valid_with_column_list(self):
        expr = self._select("WITH x(a, b) USING KEY (a) AS (SELECT 'hello' AS a, 'world' AS b) SELECT * FROM x")
        resolved = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="postgres"))
        assert resolved.ctes is not None
        assert resolved.ctes["x"].using_key == ["a"]

    def test_cte_using_key_valid_without_column_list(self):
        expr = self._select("WITH stats USING KEY (event) AS (SELECT event, timestamp FROM events) SELECT * FROM stats")
        resolved = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="postgres"))
        assert resolved.ctes is not None
        assert resolved.ctes["stats"].using_key == ["event"]

    def test_cte_using_key_invalid_column_with_column_list(self):
        with self.assertRaisesMessage(QueryError, "USING KEY column(s) 'd' not found in CTE 'x'"):
            resolve_types(
                self._select("WITH x(a, b, c) USING KEY (d) AS (SELECT 1, 2, 3) SELECT * FROM x"),
                self.context,
                dialect="postgres",
            )

    def test_cte_using_key_invalid_column_without_column_list(self):
        with self.assertRaisesMessage(QueryError, "USING KEY column(s) 'nonexistent' not found in CTE 'stats'"):
            resolve_types(
                self._select(
                    "WITH stats USING KEY (nonexistent) AS (SELECT event, timestamp FROM events) SELECT * FROM stats"
                ),
                self.context,
                dialect="postgres",
            )

    def test_values_query_basic(self):
        expr = self._select("SELECT * FROM (VALUES (1, 'a'), (2, 'b')) AS v (id, name)")
        expr = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="postgres"))
        assert isinstance(expr.select_from, ast.JoinExpr)
        assert isinstance(expr.select_from.type, ast.SelectQueryAliasType)
        assert expr.select_from.alias == "v"
        assert isinstance(expr.select_from.type.select_query_type, ast.SelectQueryType)
        columns = expr.select_from.type.select_query_type.columns
        assert "id" in columns
        assert "name" in columns

    def test_values_query_default_column_names(self):
        expr = self._select("SELECT * FROM (VALUES (1, 'a')) AS v")
        expr = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="postgres"))
        assert isinstance(expr.select_from, ast.JoinExpr)
        assert isinstance(expr.select_from.table, ast.ValuesQuery)
        assert expr.select_from.table.type is not None
        columns = expr.select_from.table.type.columns
        assert "col0" in columns
        assert "col1" in columns

    def test_values_query_row_length_mismatch(self):
        with self.assertRaisesMessage(QueryError, "VALUES row 2 has 1 columns, expected 2"):
            expr = self._select("SELECT * FROM (VALUES (1, 'a'), (2)) AS v")
            resolve_types(expr, self.context, dialect="postgres")

    def test_values_query_alias_column_count_mismatch(self):
        with self.assertRaisesMessage(QueryError, "VALUES has 2 column(s) but 3 column name(s) were provided"):
            expr = self._select("SELECT * FROM (VALUES (1, 'a')) AS v (id, name, extra)")
            resolve_types(expr, self.context, dialect="postgres")

    def test_unpivot_basic_resolves(self):
        expr = self._select(
            "SELECT field_name, field_value, distinct_id FROM events UNPIVOT (field_value FOR field_name IN (event))"
        )
        expr = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="postgres"))
        assert isinstance(expr.select_from, ast.JoinExpr)
        assert isinstance(expr.select_from.table, ast.UnpivotExpr)
        assert isinstance(expr.select_from.type, ast.SelectQueryType)

        columns = expr.select_from.type.columns
        assert "field_name" in columns
        assert "field_value" in columns
        assert "distinct_id" in columns
        assert "event" not in columns

        for column in expr.select:
            field = column.expr if isinstance(column, ast.Alias) else column
            assert isinstance(field, ast.Field)
            assert isinstance(field.type, ast.FieldType)

    def test_unpivot_non_postgres_dialect_error(self):
        with self.assertRaisesMessage(QueryError, "UNPIVOT is not allowed in clickhouse dialect"):
            expr = self._select(
                "SELECT field_name, field_value FROM events UNPIVOT (field_value FOR field_name IN (event))"
            )
            resolve_types(expr, self.context, dialect="clickhouse")

    def test_unpivot_non_identifier_output_columns_error(self):
        with self.assertRaisesMessage(QueryError, "UNPIVOT columns must be identifiers"):
            expr = self._select("SELECT * FROM events UNPIVOT (field_value + 1 FOR field_name IN (event))")
            resolve_types(expr, self.context, dialect="postgres")

    def test_unpivot_unknown_in_column_error(self):
        with self.assertRaisesMessage(QueryError, 'UNPIVOT value column "does_not_exist" was not found'):
            expr = self._select("SELECT * FROM events UNPIVOT (field_value FOR field_name IN (does_not_exist))")
            resolve_types(expr, self.context, dialect="postgres")

    def test_pivot_basic_resolves(self):
        expr = self._select("SELECT 1 FROM events PIVOT (count() FOR event IN ('a'))")
        expr = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="postgres"))
        assert isinstance(expr.select_from, ast.JoinExpr)
        assert isinstance(expr.select_from.table, ast.PivotExpr)
        assert isinstance(expr.select_from.type, ast.SelectQueryType)

        pivot = expr.select_from.table
        column_expr = pivot.columns[0].column
        if isinstance(column_expr, ast.Alias):
            column_expr = column_expr.expr
        assert isinstance(column_expr, ast.Field)
        assert isinstance(column_expr.type, ast.FieldType)

    def test_pivot_join_basic_resolves(self):
        expr = self._select("SELECT 1 FROM events JOIN events AS e2 ON 1 PIVOT (count() FOR events.event IN ('a'))")
        expr = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="postgres"))
        assert isinstance(expr.select_from, ast.JoinExpr)
        assert isinstance(expr.select_from.table, ast.PivotExpr)
        pivot = expr.select_from.table
        assert isinstance(pivot.table, ast.JoinExpr)
        column_expr = pivot.columns[0].column
        if isinstance(column_expr, ast.Alias):
            column_expr = column_expr.expr
        assert isinstance(column_expr, ast.Field)
        assert isinstance(column_expr.type, ast.FieldType)

    def test_pivot_expression_column_resolves(self):
        expr = self._select("SELECT 1 FROM events PIVOT (count() FOR toYear(timestamp) IN (2015))")
        expr = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="postgres"))
        assert isinstance(expr.select_from, ast.JoinExpr)
        assert isinstance(expr.select_from.table, ast.PivotExpr)

    def test_pivot_expression_unknown_column_error(self):
        with self.assertRaisesMessage(QueryError, 'PIVOT column "does_not_exist" was not found'):
            expr = self._select("SELECT 1 FROM events PIVOT (count() FOR toYear(does_not_exist) IN (2015))")
            resolve_types(expr, self.context, dialect="postgres")

    def test_pivot_aggregate_unknown_column_error(self):
        with self.assertRaisesMessage(QueryError, 'PIVOT column "thing" was not found'):
            expr = self._select("SELECT 1 FROM events PIVOT (sum(thing) FOR toYear(timestamp) IN (2015))")
            resolve_types(expr, self.context, dialect="postgres")

    def test_pivot_unknown_column_error(self):
        with self.assertRaisesMessage(QueryError, 'PIVOT column "does_not_exist" was not found'):
            expr = self._select("SELECT 1 FROM events PIVOT (count() FOR does_not_exist IN ('a'))")
            resolve_types(expr, self.context, dialect="postgres")

    def test_pivot_non_postgres_dialect_error(self):
        with self.assertRaisesMessage(QueryError, "PIVOT is not allowed in clickhouse dialect"):
            expr = self._select("SELECT 1 FROM events PIVOT (count() FOR event IN ('a'))")
            resolve_types(expr, self.context, dialect="clickhouse")

    def test_limit_with_ties_postgres_error(self):
        with self.assertRaisesMessage(QueryError, "WITH TIES is not supported in postgres dialect"):
            expr = self._select("SELECT 1 FROM events ORDER BY 1 LIMIT 1 WITH TIES")
            resolve_types(expr, self.context, dialect="postgres")

    def test_positional_refs_postgres(self):
        expr = self._select("SELECT #1, #2 FROM events")
        expr = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="postgres"))
        assert isinstance(expr.select[0], ast.PositionalRef)
        assert isinstance(expr.select[1], ast.PositionalRef)

    def test_function_call_order_by_resolves(self):
        expr = self._select("SELECT sum(event ORDER BY timestamp DESC) FROM events")
        expr = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="postgres"))
        assert isinstance(expr.select[0], ast.Call)
        call = expr.select[0]
        assert call.order_by is not None
        assert len(call.order_by) == 1
        assert call.order_by[0].order == "DESC"
        order_expr = call.order_by[0].expr
        if isinstance(order_expr, ast.Alias):
            order_expr = order_expr.expr
        assert isinstance(order_expr, ast.Field)
        assert isinstance(order_expr.type, ast.FieldType)

    def test_function_call_filter_resolves(self):
        expr = self._select("SELECT sum(event) FILTER (WHERE event = 'a') FROM events")
        expr = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="postgres"))
        assert isinstance(expr.select[0], ast.Call)
        call = expr.select[0]
        assert call.filter_expr is not None
        assert isinstance(call.filter_expr, ast.CompareOperation)
        left = call.filter_expr.left
        if isinstance(left, ast.Alias):
            left = left.expr
        assert isinstance(left, ast.Field)
        assert isinstance(left.type, ast.FieldType)

    def test_unpivot_include_nulls_resolves(self):
        expr = self._select(
            "SELECT field_name, field_value FROM events UNPIVOT INCLUDE NULLS (field_value FOR field_name IN (event))"
        )
        expr = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="postgres"))
        assert isinstance(expr.select_from, ast.JoinExpr)
        assert isinstance(expr.select_from.table, ast.UnpivotExpr)
        assert expr.select_from.table.include_nulls is True

    def test_unpivot_join_basic_resolves(self):
        expr = self._select(
            "SELECT field_name, field_value FROM events JOIN events AS e2 ON 1 "
            "UNPIVOT (field_value FOR field_name IN (events.event))"
        )
        expr = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="postgres"))
        assert isinstance(expr.select_from, ast.JoinExpr)
        assert isinstance(expr.select_from.table, ast.UnpivotExpr)
        assert isinstance(expr.select_from.type, ast.SelectQueryType)

    def test_positional_refs_non_postgres_error(self):
        with self.assertRaisesMessage(QueryError, "Positional references are not allowed in clickhouse dialect"):
            expr = self._select("SELECT #1 FROM events")
            resolve_types(expr, self.context, dialect="clickhouse")

    def test_subquery_alias_columns_remap(self):
        # Subquery with alias column list: SELECT * FROM (SELECT 1, 'a') AS v(id, name)
        # The resolver should remap columns so that v.id and v.name resolve correctly,
        # and SELECT * expansion uses the aliased names, not the original ones.
        expr = self._select("SELECT * FROM (SELECT 1, 'a') AS v(id, name)")
        expr = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="clickhouse"))
        assert isinstance(expr.select_from, ast.JoinExpr)
        assert isinstance(expr.select_from.type, ast.SelectQueryAliasType)
        assert isinstance(expr.select_from.type.select_query_type, ast.SelectQueryType)
        columns = expr.select_from.type.select_query_type.columns
        assert "id" in columns, f"Expected 'id' in columns, got {list(columns.keys())}"
        assert "name" in columns, f"Expected 'name' in columns, got {list(columns.keys())}"

    def test_subquery_alias_columns_qualified_access(self):
        # Qualified access via alias column names should resolve
        expr = self._select("SELECT v.id, v.name FROM (SELECT 1, 'a') AS v(id, name)")
        expr = cast(ast.SelectQuery, resolve_types(expr, self.context, dialect="clickhouse"))
        assert len(expr.select) == 2
        for col in expr.select:
            assert isinstance(col, ast.Alias)
            assert isinstance(col.expr, ast.Field)
            assert isinstance(col.expr.type, ast.FieldType)
        assert cast(ast.Alias, expr.select[0]).alias == "id"
        assert cast(ast.Alias, expr.select[1]).alias == "name"

    def test_subquery_alias_columns_count_mismatch(self):
        # Providing wrong number of alias columns for a subquery should error
        with self.assertRaises(QueryError):
            expr = self._select("SELECT * FROM (SELECT 1, 'a') AS v(id, name, extra)")
            resolve_types(expr, self.context, dialect="clickhouse")

    @parameterized.expand(
        [
            (
                "select_alias_shadows_properties",
                "SELECT argMin(properties, timestamp) as properties FROM events WHERE properties.foo = 'bar'",
            ),
            (
                "select_alias_shadows_deeper_chain",
                "SELECT argMin(properties, timestamp) as properties FROM events WHERE properties.a.b = 1",
            ),
        ]
    )
    def test_alias_shadowing_table_field_property_access(self, _name, query):
        expr = self._select(query)
        with self.assertRaisesRegex(QueryError, "Cannot access property.*renaming the alias"):
            resolve_types(expr, self.context, dialect="clickhouse")
