from typing import Literal

from posthog.test.base import BaseTest

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    FloatDatabaseField,
    StringDatabaseField,
    TableNode,
)
from posthog.hogql.database.s3_table import DataWarehouseTable
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import create_default_modifiers_for_team

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
    def _print(self, query: str, dialect: Literal["hogql", "clickhouse"] = "hogql") -> str:
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
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=database,
            modifiers=create_default_modifiers_for_team(self.team),
        )
        return prepare_and_print_ast(parse_select(query), context, dialect=dialect)[0]

    def test_asterisk_branches_align_by_name(self):
        printed = self._print("SELECT * FROM new_table UNION ALL SELECT * FROM old_table")
        self.assertEqual(
            printed,
            "SELECT uuid, timestamp, tlat, city FROM new_table LIMIT 50000"
            " UNION ALL SELECT uuid, timestamp, tlat, city FROM old_table LIMIT 50000",
        )

    def test_asterisk_branches_align_by_name_nested(self):
        printed = self._print(
            "SELECT * FROM new_table UNION ALL (SELECT * FROM old_table UNION DISTINCT SELECT * FROM old_table)"
        )
        self.assertIn("SELECT uuid, timestamp, tlat, city FROM old_table", printed)
        self.assertNotIn("SELECT city, tlat, uuid, timestamp", printed)

    def test_explicit_select_lists_stay_positional(self):
        printed = self._print("SELECT uuid, city FROM new_table UNION ALL SELECT city, uuid FROM old_table")
        self.assertEqual(
            printed,
            "SELECT uuid, city FROM new_table LIMIT 50000 UNION ALL SELECT city, uuid FROM old_table LIMIT 50000",
        )

    def test_asterisk_branches_with_differing_columns_raise(self):
        with self.assertRaises(ExposedHogQLError) as e:
            self._print("SELECT * FROM new_table UNION ALL SELECT * FROM extra_table")
        self.assertIn("unexpected: extra", str(e.exception))
        self.assertIn("List the columns explicitly", str(e.exception))

    def test_union_all_by_name_lowered_for_clickhouse(self):
        printed = self._print(
            "SELECT uuid, city FROM new_table UNION ALL BY NAME SELECT city, uuid FROM old_table",
            dialect="clickhouse",
        )
        self.assertNotIn("BY NAME", printed)
        self.assertIn(
            "UNION ALL SELECT old_table.uuid AS uuid, old_table.city AS city",
            printed,
        )

    def test_union_all_by_name_kept_in_hogql_dialect(self):
        printed = self._print("SELECT uuid, city FROM new_table UNION ALL BY NAME SELECT city, uuid FROM old_table")
        self.assertIn("UNION ALL BY NAME SELECT city, uuid FROM old_table", printed)

    def test_projection_pushdown_prunes_aligned_branches_symmetrically(self):
        printed = self._print(
            "SELECT city FROM (SELECT * FROM new_table UNION ALL SELECT * FROM old_table) AS u",
            dialect="clickhouse",
        )
        self.assertIn("SELECT new_table.city AS city FROM", printed)
        self.assertIn("UNION ALL SELECT old_table.city AS city FROM", printed)
        self.assertNotIn("tlat", printed)

    def test_union_all_by_name_with_differing_columns_raises(self):
        with self.assertRaises(ExposedHogQLError):
            self._print(
                "SELECT uuid, city FROM new_table UNION ALL BY NAME SELECT city, extra FROM extra_table",
                dialect="clickhouse",
            )
