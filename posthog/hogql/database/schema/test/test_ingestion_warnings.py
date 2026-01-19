from posthog.test.base import BaseTest

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast


class TestIngestionWarningsTable(BaseTest):
    def test_select_from_ingestion_warnings_system_table(self):
        db = Database.create_for(team=self.team)
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
        )

        sql = "SELECT source, type, details, timestamp FROM system.ingestion_warnings"
        query, _ = prepare_and_print_ast(parse_select(sql), context, dialect="clickhouse")

        assert "ingestion_warnings" in query
        assert "source" in query
        assert "type" in query
        assert "details" in query
        assert "timestamp" in query

    def test_ingestion_warnings_table_is_in_system_tables(self):
        db = Database.create_for(team=self.team)
        system_table_names = db.get_system_table_names()

        assert "system.ingestion_warnings" in system_table_names

    def test_ingestion_warnings_table_has_team_id_filter(self):
        db = Database.create_for(team=self.team)
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
        )

        sql = "SELECT * FROM system.ingestion_warnings"
        query, _ = prepare_and_print_ast(parse_select(sql), context, dialect="clickhouse")

        assert f"team_id = {self.team.pk}" in query or f"equals(ingestion_warnings.team_id, {self.team.pk})" in query
