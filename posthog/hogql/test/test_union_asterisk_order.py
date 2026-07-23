import re
from typing import Literal

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    ExpressionField,
    FieldOrTable,
    FloatDatabaseField,
    StringDatabaseField,
    TableNode,
)
from posthog.hogql.database.s3_table import DataWarehouseTable
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import create_default_modifiers_for_team
from posthog.hogql.resolver import resolve_types

TYPES = {
    "uuid": (StringDatabaseField, "String"),
    "city": (StringDatabaseField, "String"),
    "timestamp": (DateTimeDatabaseField, "DateTime64(6)"),
    "tlat": (FloatDatabaseField, "Float64"),
    "extra": (StringDatabaseField, "String"),
}

SELECT_ORDER = ["uuid", "timestamp", "tlat", "city"]
JSONB_ORDER = ["city", "tlat", "uuid", "timestamp"]


def _make_table(name: str, order: list[str]) -> DataWarehouseTable:
    fields: dict[str, FieldOrTable] = {c: TYPES[c][0](name=c, nullable=True) for c in order}
    structure = ", ".join(f"`{c}` Nullable({TYPES[c][1]})" for c in order)
    return DataWarehouseTable(
        name=name,
        url=f"http://bucket/{name}/",
        format="Parquet",
        fields=fields,
        structure=structure,
    )


class TestUnionAsteriskOrder(BaseTest):
    def _context(self) -> HogQLContext:
        database = Database.create_for(team=self.team)
        database._add_warehouse_tables(
            TableNode(
                children={
                    "new_table": TableNode(name="new_table", table=_make_table("new_table", SELECT_ORDER)),
                    "old_table": TableNode(name="old_table", table=_make_table("old_table", JSONB_ORDER)),
                    "extra_table": TableNode(
                        name="extra_table", table=_make_table("extra_table", [*JSONB_ORDER, "extra"])
                    ),
                }
            )
        )
        return HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=database,
            modifiers=create_default_modifiers_for_team(self.team),
        )

    def _print(self, query: str, dialect: Literal["hogql", "clickhouse"] = "hogql") -> str:
        return prepare_and_print_ast(parse_select(query), self._context(), dialect=dialect)[0]

    @parameterized.expand(
        [
            (
                "asterisk branches align on the first branch's order",
                "SELECT * FROM new_table UNION ALL SELECT * FROM old_table",
                "SELECT uuid, timestamp, tlat, city FROM new_table LIMIT 50000"
                " UNION ALL SELECT uuid, timestamp, tlat, city FROM old_table LIMIT 50000",
            ),
            (
                "explicit select lists stay positional",
                "SELECT uuid, city FROM new_table UNION ALL SELECT city, uuid FROM old_table",
                "SELECT uuid, city FROM new_table LIMIT 50000 UNION ALL SELECT city, uuid FROM old_table LIMIT 50000",
            ),
        ]
    )
    def test_branch_column_order(self, _name: str, query: str, expected: str):
        self.assertEqual(self._print(query), expected)

    def test_nested_set_query_branches_and_type_follow_the_outer_order(self):
        query = "SELECT * FROM new_table UNION ALL (SELECT * FROM old_table UNION DISTINCT SELECT * FROM old_table)"
        self.assertIn("SELECT uuid, timestamp, tlat, city FROM old_table", self._print(query))

        # The nested set query unified its columns in its own branch order. The outer unification
        # pairs branches positionally, so leaving it stale crosses the outer column types while the
        # printed SQL still looks correct.
        node = resolve_types(parse_select(query), self._context(), dialect="clickhouse")
        assert node.type is not None
        self.assertEqual(
            [type(t).__name__ for t in node.type.columns.values()],
            ["StringType", "DateTimeType", "FloatType", "StringType"],
        )

    def test_branches_align_in_the_clickhouse_dialect_with_an_expression_field(self):
        # An expression field resolves to an alias over an expression rather than over a field, and
        # only the clickhouse dialect rewrites it that way — so alignment has to survive that shape
        # or it silently declines for every table carrying a computed column.
        context = self._context()
        for table_name in ("new_table", "old_table"):
            table = context.database.get_table(table_name)
            table.fields["virt"] = ExpressionField(name="virt", expr=parse_expr("upper(city)"))
        printed = prepare_and_print_ast(
            parse_select("SELECT * FROM new_table UNION ALL SELECT * FROM old_table"),
            context,
            dialect="clickhouse",
        )[0]
        branches = printed.split("UNION ALL")
        self.assertEqual(len(branches), 2)
        columns = [re.findall(r"AS (\w+)", branch.split(" FROM ")[0]) for branch in branches]
        self.assertEqual(columns[0], columns[1])

    def test_positional_order_by_still_references_the_same_column(self):
        # Reordering a branch's select list moves the columns its positional ORDER BY/GROUP BY
        # ordinals point at, so the ordinal has to keep designating the column the user wrote.
        printed = self._print("SELECT * FROM new_table UNION ALL (SELECT * FROM old_table ORDER BY 2 LIMIT 10)")
        branch = printed.split("UNION ALL", 1)[1]
        select_list = [column.strip() for column in re.search(r"SELECT (.*?) FROM", branch).group(1).split(",")]
        ordinal = int(re.search(r"ORDER BY (\d+)", branch).group(1))
        self.assertEqual(select_list[ordinal - 1], "tlat")

    def test_only_stored_column_order_is_realigned(self):
        # Reordering is justified only because a table's stored field order is arbitrary. A
        # subquery's order is the author's, so overriding it would change what their query returns.
        authored = self._print(
            "SELECT * FROM (SELECT 1 AS a, 2 AS b) AS x UNION ALL SELECT * FROM (SELECT 3 AS b, 4 AS a) AS y"
        )
        self.assertIn("SELECT b, a FROM (SELECT 3 AS b, 4 AS a) AS y", authored)

        # A subquery that is itself asterisk-expanded carries the table's stored order, so the
        # branch selecting from it still aligns.
        stored = self._print("SELECT * FROM new_table UNION ALL SELECT * FROM (SELECT * FROM old_table) AS y")
        self.assertIn("UNION ALL SELECT uuid, timestamp, tlat, city FROM (", stored)

    def test_asterisk_branches_with_differing_columns_raise(self):
        with self.assertRaises(ExposedHogQLError) as e:
            self._print("SELECT * FROM new_table UNION ALL SELECT * FROM extra_table")
        self.assertIn("unexpected: extra", str(e.exception))
        self.assertIn("List the columns explicitly", str(e.exception))

    def test_projection_pushdown_prunes_aligned_branches_symmetrically(self):
        printed = self._print(
            "SELECT city FROM (SELECT * FROM new_table UNION ALL SELECT * FROM old_table) AS u",
            dialect="clickhouse",
        )
        self.assertIn("SELECT new_table.city AS city FROM", printed)
        self.assertIn("UNION ALL SELECT old_table.city AS city FROM", printed)
        self.assertNotIn("tlat", printed)
