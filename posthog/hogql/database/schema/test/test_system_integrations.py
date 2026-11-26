import json
from typing import Any

from posthog.test.base import BaseTest, NonAtomicBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.schema import integrations as integrations_module
from posthog.hogql.database.schema.integrations import MAX_INTEGRATION_ROWS, IntegrationsTable, integrations
from posthog.hogql.database.schema.system import SystemTables
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import execute_hogql_query

from posthog.integrations import IntegrationManager
from posthog.models import Organization, Team
from posthog.models.project import Project


def _create_integration(team: Team, external_id: str, **config: Any) -> None:
    IntegrationManager.slack.oauth.create(
        team.pk,
        external_id=external_id,
        config={"team": {"name": external_id}, **config},
        sensitive_config={"access_token": "xoxb-secret-token", "refresh_token": "refresh-secret"},
    )


class TestSystemIntegrationsTable(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        other_org = Organization.objects.create(name="other_org")
        other_project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=other_org)
        self.other_team = Team.objects.create(id=other_project.id, project=other_project, organization=other_org)

    def _query(self, sql: str):
        return execute_hogql_query(sql, team=self.team, user=self.user)

    def test_rows_of_the_team_appear_with_typed_columns(self):
        _create_integration(self.team, "T001")

        response = self._query(
            "SELECT id, team_id, kind, integration_id, config.team.name, errors, created_at, created_by_id "
            "FROM system.integrations"
        )

        assert len(response.results) == 1
        row_id, team_id, kind, external_id, name, errors, created_at, created_by_id = response.results[0]
        assert isinstance(row_id, int)
        assert team_id == self.team.pk
        assert kind == "slack"
        assert external_id == "T001"
        assert name == "T001"
        assert errors == ""
        assert created_at is not None and created_at.year >= 2024
        assert created_by_id is None

    def test_config_is_queryable_as_json(self):
        _create_integration(self.team, "T001", scopes="chat:write")

        response = self._query("SELECT config FROM system.integrations")

        assert json.loads(response.results[0][0])["scopes"] == "chat:write"

    def test_other_teams_rows_do_not_appear(self):
        _create_integration(self.team, "mine")
        _create_integration(self.other_team, "theirs")

        response = self._query("SELECT integration_id FROM system.integrations")

        assert response.results == [("mine",)]

    def test_team_with_no_integrations_returns_no_rows(self):
        _create_integration(self.other_team, "theirs")

        response = self._query("SELECT id, config FROM system.integrations")

        assert response.results == []

    def test_no_secret_column_exists(self):
        assert set(integrations.fields) == {
            "id",
            "team_id",
            "kind",
            "integration_id",
            "config",
            "errors",
            "created_at",
            "created_by_id",
        }

    @parameterized.expand([("sensitive_config",), ("access_token",), ("refresh_token",)])
    def test_secret_columns_cannot_be_selected(self, column):
        _create_integration(self.team, "T001")

        with self.assertRaises(Exception) as raised:
            self._query(f"SELECT {column} FROM system.integrations")

        assert "xoxb-secret-token" not in str(raised.exception)

    def test_secret_values_never_reach_the_query_result_or_sql(self):
        _create_integration(self.team, "T001")

        response = self._query("SELECT * FROM system.integrations")

        dumped = json.dumps(response.results, default=str) + (response.clickhouse or "")
        assert "xoxb-secret-token" not in dumped
        assert "refresh-secret" not in dumped

    def test_rows_above_the_cap_keep_the_newest(self):
        for index in range(5):
            _create_integration(self.team, f"T{index}")

        with patch.object(integrations_module, "MAX_INTEGRATION_ROWS", 3):
            response = self._query("SELECT integration_id FROM system.integrations ORDER BY integration_id")

        assert response.results == [("T2",), ("T3",), ("T4",)]

    def test_cap_is_a_sane_bound(self):
        assert 0 < MAX_INTEGRATION_ROWS <= 1000

    def test_rows_load_once_per_query_even_with_two_references(self):
        _create_integration(self.team, "T001")

        calls = []
        original = integrations_module.load_integration_rows

        def counting(context: HogQLContext):
            first_load = context.system_integrations_rows is None
            rows = original(context)
            if first_load:
                calls.append(1)
            return rows

        with patch.object(integrations_module, "load_integration_rows", counting):
            response = self._query(
                "SELECT a.integration_id, b.integration_id FROM system.integrations AS a "
                "JOIN system.integrations AS b ON a.id = b.id"
            )

        assert response.results == [("T001", "T001")]
        assert len(calls) == 1

    def test_query_without_the_table_does_not_load_rows(self):
        with patch.object(integrations_module, "load_integration_rows") as load:
            self._query("SELECT id FROM system.dashboards")

        load.assert_not_called()


class TestSystemIntegrationsSchema(BaseTest):
    def test_table_keeps_system_table_access_control(self):
        table = SystemTables().children["integrations"].table
        assert isinstance(table, IntegrationsTable)
        assert table.access_scope == "integration"
        assert table.access_control_id is None

    def test_printed_clickhouse_does_not_read_postgres(self):
        db = Database.create_for(team=self.team, user=self.user)
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, database=db)

        query, _ = prepare_and_print_ast(
            parse_select("SELECT id FROM system.integrations"), context, dialect="clickhouse"
        )

        assert "postgresql(" not in query
        assert "posthog_integration" not in query
