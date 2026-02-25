from typing import Literal

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import IntegerDatabaseField, StringDatabaseField, TableNode
from posthog.hogql.database.postgres_table import PostgresTable, build_function_call
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import create_default_modifiers_for_team


class TestPostgresTable(BaseTest):
    def _init_database(self):
        self.database = Database.create_for(team=self.team)

        self.database.tables.add_child(
            TableNode(
                name="postgres_table",
                table=PostgresTable(
                    name="postgres_table",
                    postgres_table_name="some_table_on_postgres",
                    fields={
                        "id": IntegerDatabaseField(name="id"),
                        "team_id": IntegerDatabaseField(name="team_id"),
                        "name": StringDatabaseField(name="name"),
                    },
                ),
            )
        )

        self.context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=self.database,
            modifiers=create_default_modifiers_for_team(self.team),
        )

    def _select(self, query: str, dialect: Literal["hogql", "clickhouse"] = "clickhouse") -> str:
        return prepare_and_print_ast(parse_select(query), self.context, dialect=dialect)[0]

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


class TestBuildFunctionCallRdsproxyPriority(BaseTest):
    RDSPROXY_SETTINGS = {
        "CLICKHOUSE_HOGQL_RDSPROXY_READ_HOST": "aurora.example.com",
        "CLICKHOUSE_HOGQL_RDSPROXY_READ_PORT": "5432",
        "CLICKHOUSE_HOGQL_RDSPROXY_READ_DATABASE": "eval_db",
        "CLICKHOUSE_HOGQL_RDSPROXY_READ_USER": "eval_user",
        "CLICKHOUSE_HOGQL_RDSPROXY_READ_PASSWORD": "eval_pass",
    }

    @parameterized.expand(
        [
            ("debug_mode", True, False),
            ("test_mode", False, True),
            ("both_modes", True, True),
        ]
    )
    def test_rdsproxy_preferred_over_debug_fallback(self, _name: str, debug: bool, test: bool):
        with (
            patch("posthog.hogql.database.postgres_table.settings") as mock_settings,
        ):
            for key, value in self.RDSPROXY_SETTINGS.items():
                setattr(mock_settings, key, value)
            mock_settings.DEBUG = debug
            mock_settings.TEST = test

            result = build_function_call("posthog_team")
            assert "aurora.example.com:5432" in result
            assert "eval_db" in result

    def test_debug_fallback_when_no_rdsproxy(self):
        with (
            patch("posthog.hogql.database.postgres_table.settings") as mock_settings,
        ):
            mock_settings.CLICKHOUSE_HOGQL_RDSPROXY_READ_HOST = None
            mock_settings.DEBUG = True
            mock_settings.TEST = False
            mock_settings.DATABASES = {
                "default": {
                    "NAME": "posthog_test",
                    "USER": "postgres",
                    "PASSWORD": "password",
                },
            }

            result = build_function_call("posthog_team")
            assert "db:5432" in result
            assert "posthog_test" in result

    def test_raises_when_no_rdsproxy_and_not_debug(self):
        with (
            patch("posthog.hogql.database.postgres_table.settings") as mock_settings,
        ):
            mock_settings.CLICKHOUSE_HOGQL_RDSPROXY_READ_HOST = None
            mock_settings.DEBUG = False
            mock_settings.TEST = False

            with self.assertRaises(ValueError, msg="CLICKHOUSE_HOGQL_RDSPROXY env vars missing"):
                build_function_call("posthog_team")

    def test_raises_when_rdsproxy_partially_configured(self):
        with (
            patch("posthog.hogql.database.postgres_table.settings") as mock_settings,
        ):
            mock_settings.CLICKHOUSE_HOGQL_RDSPROXY_READ_HOST = "aurora.example.com"
            mock_settings.CLICKHOUSE_HOGQL_RDSPROXY_READ_PORT = None
            mock_settings.CLICKHOUSE_HOGQL_RDSPROXY_READ_DATABASE = None
            mock_settings.CLICKHOUSE_HOGQL_RDSPROXY_READ_USER = None
            mock_settings.CLICKHOUSE_HOGQL_RDSPROXY_READ_PASSWORD = None

            with self.assertRaises(ValueError, msg="partially configured"):
                build_function_call("posthog_team")
