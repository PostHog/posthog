from typing import Literal

from posthog.test.base import BaseTest

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import create_hogql_database
from posthog.hogql.database.models import IntegerDatabaseField, StringDatabaseField
from posthog.hogql.database.postgres_table import PostgresTable
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.hogql.query import create_default_modifiers_for_team


class TestPostgresTable(BaseTest):
    def _init_database(self):
        self.database = create_hogql_database(team=self.team)

        setattr(  # noqa: B010
            self.database,
            "postgres_table",
            PostgresTable(
                name="postgres_table",
                postgres_table_name="some_table_on_postgres",
                fields={
                    "id": IntegerDatabaseField(name="id"),
                    "team_id": IntegerDatabaseField(name="team_id"),
                    "name": StringDatabaseField(name="name"),
                },
            ),
        )

        self.context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=self.database,
            modifiers=create_default_modifiers_for_team(self.team),
        )

    def _select(self, query: str, dialect: Literal["hogql", "clickhouse"] = "clickhouse") -> str:
        return print_ast(parse_select(query), self.context, dialect=dialect)

    def test_postgres_table_select(self):
        self._init_database()

        hogql = self._select(query="SELECT * FROM postgres_table LIMIT 10", dialect="hogql")
        self.assertEqual(
            hogql,
            "SELECT id, team_id, name FROM postgres_table LIMIT 10",
        )

        clickhouse = self._select(query="SELECT * FROM postgres_table LIMIT 10", dialect="clickhouse")

        self.assertEqual(
            clickhouse,
            f"SELECT postgres_table.id AS id, postgres_table.team_id AS team_id, postgres_table.name AS name FROM postgresql(%(hogql_val_1_sensitive)s, %(hogql_val_2_sensitive)s, %(hogql_val_0_sensitive)s, %(hogql_val_3_sensitive)s, %(hogql_val_4_sensitive)s) AS postgres_table WHERE equals(postgres_table.team_id, {self.team.id}) LIMIT 10",
        )
