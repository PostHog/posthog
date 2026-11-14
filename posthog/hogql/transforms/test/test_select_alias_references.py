from typing import Any

from unittest.mock import patch

from django.test import SimpleTestCase

import duckdb
from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.constants import HogQLDialect
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.direct_motherduck_table import DirectMotherDuckTable
from posthog.hogql.database.direct_mysql_table import DirectMySQLTable
from posthog.hogql.database.direct_postgres_table import DirectPostgresTable
from posthog.hogql.database.direct_redshift_table import DirectRedshiftTable
from posthog.hogql.database.direct_snowflake_table import DirectSnowflakeTable
from posthog.hogql.database.models import (
    FieldOrTable,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringArrayDatabaseField,
    StringDatabaseField,
    Table,
    TableNode,
)
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.trino_parameters import convert_pyformat_placeholders

PRODUCT_ROWS = [(1, "a", 1.0), (2, "A", 2.0), (3, "b", 10.0), (4, "c", 4.0), (5, "c", 6.0)]
ORDER_ROWS = [(1, "x", 3.0), (2, "y", 5.0), (9, "z", 7.0)]


def _table(dialect: HogQLDialect, name: str) -> Table:
    fields: dict[str, FieldOrTable] = {
        "id": IntegerDatabaseField(name="id", nullable=False),
        "name": StringDatabaseField(name="name", nullable=False),
        "net_price": FloatDatabaseField(name="net_price", nullable=False),
        "tags": StringArrayDatabaseField(name="tags", nullable=False),
    }
    common: dict[str, Any] = {"name": name, "fields": fields, "external_data_source_id": "source-id"}
    if dialect == "postgres":
        return DirectPostgresTable(postgres_schema="public", postgres_table_name=name, **common)
    if dialect == "redshift":
        return DirectRedshiftTable(postgres_schema="public", postgres_table_name=name, **common)
    if dialect == "mysql":
        return DirectMySQLTable(mysql_schema="shop", mysql_table_name=name, **common)
    if dialect == "snowflake":
        return DirectSnowflakeTable(snowflake_schema="PUBLIC", snowflake_table_name=name, **common)
    return DirectMotherDuckTable(
        motherduck_database="md", motherduck_schema="main", motherduck_table_name=name, **common
    )


def _print(query: str, dialect: HogQLDialect = "postgres") -> tuple[str, dict[str, Any]]:
    database = Database(include_posthog_tables=False)
    for name in ("product", "orders"):
        database.tables.add_child(TableNode(name=name, table=_table(dialect, name)))
    context = HogQLContext(
        database=database,
        # Unset, this modifier falls back to an instance setting, which is a database read.
        modifiers=HogQLQueryModifiers(useNewEventsSchema=False),
        enable_select_queries=True,
        limit_top_select=False,
        restricted_properties=set(),
    )
    sql, _ = prepare_and_print_ast(parse_select(query), context, dialect)
    return sql, context.values


def _duckdb_rows(query: str) -> list[tuple[Any, ...]]:
    sql, values = _print(query, "duckdb")
    sql, parameters = convert_pyformat_placeholders(sql, values)
    with duckdb.connect(":memory:") as connection:
        connection.execute("ATTACH ':memory:' AS md")
        for table, rows in (("product", PRODUCT_ROWS), ("orders", ORDER_ROWS)):
            connection.execute(f"CREATE TABLE md.main.{table} (id INTEGER, name VARCHAR, net_price DOUBLE)")
            connection.executemany(f"INSERT INTO md.main.{table} VALUES (?, ?, ?)", rows)
        return connection.execute(sql, parameters or None).fetchall()


class TestSelectAliasReferences(SimpleTestCase):
    maxDiff = None

    @parameterized.expand(
        [
            (
                "postgres",
                "SELECT (product.net_price * 1.23) AS gross_price, "
                "((product.net_price * 1.23) * 0.5) AS discounted_gross_price "
                "FROM public.product AS product WHERE (((product.net_price * 1.23) * 0.5) < 10.0)",
            ),
            (
                "redshift",
                "SELECT (product.net_price * 1.23) AS gross_price, "
                "((product.net_price * 1.23) * 0.5) AS discounted_gross_price "
                "FROM public.product AS product WHERE (((product.net_price * 1.23) * 0.5) < 10.0)",
            ),
            (
                "mysql",
                "SELECT (product.net_price * 1.23) AS gross_price, "
                "((product.net_price * 1.23) * 0.5) AS discounted_gross_price "
                "FROM shop.product AS product WHERE (((product.net_price * 1.23) * 0.5) < 10.0)",
            ),
            (
                "duckdb",
                "SELECT (product.net_price * 1.23) AS gross_price, "
                "((product.net_price * 1.23) * 0.5) AS discounted_gross_price "
                "FROM md.main.product AS product WHERE (((product.net_price * 1.23) * 0.5) < 10.0)",
            ),
            (
                "snowflake",
                'SELECT ("product"."net_price" * 1.23) AS "gross_price", '
                '(("product"."net_price" * 1.23) * 0.5) AS "discounted_gross_price" '
                'FROM "PUBLIC"."product" AS "product" WHERE ((("product"."net_price" * 1.23) * 0.5) < 10.0)',
            ),
            # The HogQL printer shows a query to its author, so it keeps the names the author wrote.
            (
                "hogql",
                "SELECT multiply(net_price, 1.23) AS gross_price, "
                "multiply(gross_price, 0.5) AS discounted_gross_price "
                "FROM product WHERE less(discounted_gross_price, 10.0)",
            ),
        ]
    )
    def test_alias_reused_in_select_and_where(self, dialect: HogQLDialect, expected: str) -> None:
        sql, _ = _print(
            "SELECT net_price * 1.23 AS gross_price, gross_price * 0.5 AS discounted_gross_price "
            "FROM product WHERE discounted_gross_price < 10.0",
            dialect,
        )
        self.assertEqual(sql, expected)

    @parameterized.expand(
        [
            (
                "alias_defined_inside_an_expression",
                "SELECT (net_price * 2 AS doubled) + 1 AS x, doubled * 3 AS y FROM product WHERE doubled > 3",
                "SELECT ((product.net_price * 2) + 1) AS x, ((product.net_price * 2) * 3) AS y "
                "FROM public.product AS product WHERE ((product.net_price * 2) > 3)",
            ),
            (
                "group_by_takes_the_column_position",
                "SELECT upper(name) AS name, count() AS c FROM product GROUP BY name",
                "SELECT upper(product.name) AS name, count(*) AS c FROM public.product AS product GROUP BY 1",
            ),
            (
                "having_and_order_by_expression",
                "SELECT upper(name) AS n, count() AS c FROM product GROUP BY n HAVING c > 1 ORDER BY c * -1",
                "SELECT upper(product.name) AS n, count(*) AS c FROM public.product AS product "
                "GROUP BY 1 HAVING (count(*) > 1) ORDER BY (count(*) * -1) ASC",
            ),
            (
                "bare_order_by_keeps_the_name",
                "SELECT upper(name) AS n, count() AS c FROM product GROUP BY n ORDER BY c DESC, n",
                "SELECT upper(product.name) AS n, count(*) AS c FROM public.product AS product "
                "GROUP BY 1 ORDER BY c DESC, n ASC",
            ),
            (
                "reference_as_a_column_keeps_its_name",
                "SELECT net_price * 2 AS d, d FROM product ORDER BY d",
                "SELECT (product.net_price * 2) AS d, (product.net_price * 2) AS d "
                "FROM public.product AS product ORDER BY (product.net_price * 2) ASC",
            ),
            (
                "grouping_function_argument",
                "SELECT upper(name) AS n, count() AS c FROM product GROUP BY ROLLUP(n)",
                "SELECT upper(product.name) AS n, count(*) AS c FROM public.product AS product "
                "GROUP BY ROLLUP(upper(product.name))",
            ),
            (
                "window_over_an_aggregate_alias",
                "SELECT count() AS c, sum(c) OVER (PARTITION BY c) AS total FROM product GROUP BY name",
                "SELECT count(*) AS c, sum(count(*)) OVER (PARTITION BY count(*)) AS total "
                "FROM public.product AS product GROUP BY product.name",
            ),
            (
                "subquery_alias_stays_in_its_query",
                "SELECT d + 1 AS e FROM (SELECT net_price * 2 AS d FROM product WHERE d > 1) AS sub WHERE e > 2",
                "SELECT (sub.d + 1) AS e FROM (SELECT (product.net_price * 2) AS d FROM public.product AS product "
                "WHERE ((product.net_price * 2) > 1)) AS sub WHERE ((sub.d + 1) > 2)",
            ),
            (
                "scalar_subquery_alias",
                "SELECT (SELECT max(net_price) FROM orders) AS top FROM product WHERE net_price < top",
                "SELECT (SELECT max(orders.net_price) FROM public.orders AS orders) AS top "
                "FROM public.product AS product "
                "WHERE (product.net_price < (SELECT max(orders.net_price) FROM public.orders AS orders))",
            ),
        ]
    )
    def test_postgres_sql(self, _name: str, query: str, expected: str) -> None:
        sql, _ = _print(query)
        self.assertEqual(sql, expected)

    @parameterized.expand(
        [
            (
                "where",
                "SELECT upper(name) AS name FROM product WHERE name = 'A'",
                [("A",), ("A",)],
            ),
            (
                "later_select_column",
                "SELECT upper(name) AS name, concat(name, '!') AS shout FROM product WHERE id = 1",
                [("A", "A!")],
            ),
            (
                "group_by",
                "SELECT upper(name) AS name, count() AS c FROM product GROUP BY name ORDER BY name",
                [("A", 2), ("B", 1), ("C", 2)],
            ),
            (
                "order_by_expression",
                "SELECT -net_price AS net_price FROM product ORDER BY net_price * 1 LIMIT 1",
                [(-10.0,)],
            ),
            (
                "having",
                "SELECT upper(name) AS name, count() AS id FROM product GROUP BY name HAVING id > 1 ORDER BY name",
                [("A", 2), ("C", 2)],
            ),
            (
                "window_partition",
                "SELECT upper(name) AS name, count() OVER (PARTITION BY name) AS c FROM product WHERE id = 1 OR id = 2",
                [("A", 2), ("A", 2)],
            ),
        ]
    )
    def test_alias_wins_over_a_column_of_the_same_name(
        self, _name: str, query: str, expected: list[tuple[Any, ...]]
    ) -> None:
        self.assertEqual(_duckdb_rows(query), expected)

    @parameterized.expand(
        [
            (
                "aggregate_in_where",
                "SELECT count() AS c FROM product WHERE c > 5",
                'Alias "c" holds an aggregate function, so WHERE can\'t use it. Filter on it in HAVING instead.',
            ),
            (
                "aggregate_reached_through_another_alias",
                "SELECT count() AS c, c + 1 AS d FROM product WHERE d > 1",
                'Alias "d" holds an aggregate function, so WHERE can\'t use it. Filter on it in HAVING instead.',
            ),
            (
                "aggregate_alias_named_like_a_column",
                "SELECT max(net_price) AS net_price FROM product WHERE net_price > 5",
                'Alias "net_price" holds an aggregate function, so WHERE can\'t use it. '
                "Filter on it in HAVING instead. To use the column instead, write product.net_price.",
            ),
            (
                "aggregate_in_group_by",
                "SELECT upper(name) AS n, count() AS c FROM product GROUP BY n, c",
                'Alias "c" holds an aggregate function, so GROUP BY can\'t use it.',
            ),
            (
                "aggregate_in_aggregate",
                "SELECT sum(net_price) AS net_price, avg(net_price) AS mean FROM product",
                'Alias "net_price" holds an aggregate function, so another aggregate function can\'t use it. '
                "To use the column instead, write product.net_price.",
            ),
            (
                "window_function_in_where",
                "SELECT row_number() OVER (ORDER BY id) AS rn FROM product WHERE rn = 1",
                'Alias "rn" holds a window function, so WHERE can\'t use it. '
                "Select it in a subquery and use it in the outer query.",
            ),
            (
                "window_function_in_having",
                "SELECT name, row_number() OVER (ORDER BY name) AS rn FROM product GROUP BY name HAVING rn = 1",
                'Alias "rn" holds a window function, so HAVING can\'t use it. '
                "Select it in a subquery and use it in the outer query.",
            ),
            (
                "new_value_on_each_call",
                "SELECT rand() AS r FROM product WHERE r > 10",
                'Alias "r" calls rand(), which returns a new value each time it runs, '
                "so the query can't use the alias a second time. "
                "Select it in a subquery and use it in the outer query.",
            ),
            (
                "more_than_one_row",
                "SELECT arrayJoin(tags) AS tag, upper(tag) AS loud FROM product",
                'Alias "tag" calls arrayJoin(), which returns more than one row, '
                "so the query can't use the alias a second time. "
                "Select it in a subquery and use it in the outer query.",
            ),
        ]
    )
    def test_alias_that_the_clause_cannot_use(self, _name: str, query: str, expected: str) -> None:
        with self.assertRaises(QueryError) as raised:
            _print(query)
        self.assertEqual(str(raised.exception), expected)

    @parameterized.expand([("duckdb",), ("snowflake",), ("redshift",)])
    def test_engine_that_reuses_aliases_keeps_the_name_of_an_uncopyable_alias(self, dialect: HogQLDialect) -> None:
        sql, _ = _print("SELECT rand() AS r, r + 1 AS r2 FROM product", dialect)
        self.assertRegex(sql, r'\("?r"? \+ 1\) AS "?r2"?')

    def test_order_by_an_uncopyable_alias(self) -> None:
        sql, _ = _print("SELECT rand() AS r FROM product ORDER BY r")
        self.assertEqual(sql, "SELECT random() AS r FROM public.product AS product ORDER BY r ASC")

    def test_expansion_limit(self) -> None:
        with patch("posthog.hogql.transforms.select_alias_references.MAX_INLINED_ALIAS_NODES", 500):
            columns = ["net_price AS a0"] + [f"a{i} + a{i} AS a{i + 1}" for i in range(12)]
            with self.assertRaises(QueryError) as raised:
                _print(f"SELECT {', '.join(columns)} FROM product")
        self.assertIn("expand into too many expressions", str(raised.exception))
