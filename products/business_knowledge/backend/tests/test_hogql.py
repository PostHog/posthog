"""
Cross-team isolation test for the HogQL-exposed business_knowledge tables.

This is the red-team test called out in the plan as a Stage 1 blocker: the
agent queries `business_knowledge_*` tables via HogQL, and team_id isolation
has to be enforced by the query rewriter — never by convention.
"""

from posthog.test.base import BaseTest

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

from posthog.models.team import Team

from products.business_knowledge.backend.logic import create_text_source


class TestBusinessKnowledgeHogQLIsolation(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.other_team = Team.objects.create_with_data(
            organization=self.organization, initiating_user=self.user, name="Other"
        )
        create_text_source(team_id=self.team.id, created_by_id=self.user.id, name="Mine", text="secret content")
        create_text_source(team_id=self.other_team.id, created_by_id=self.user.id, name="Theirs", text="other secret")

    def _render(self, sql: str, team: Team) -> str:
        context = HogQLContext(team_id=team.id, enable_select_queries=True)
        printed, _ = prepare_and_print_ast(parse_select(sql), context=context, dialect="clickhouse")
        return printed

    def test_chunks_query_injects_team_id_predicate(self) -> None:
        # Whatever SQL the agent writes, the printed ClickHouse output must
        # carry `team_id = <team.id>` against the chunk table. Without this
        # guarantee, one team's agent could read another team's chunks.
        printed = self._render("SELECT content FROM business_knowledge_chunks", self.team)
        assert (
            f"equals({{placeholder:team_id}}, {self.team.id})" in printed
            or f"team_id, {self.team.id}" in printed
            or f"= {self.team.id}" in printed
        )

    def test_documents_query_injects_team_id_predicate(self) -> None:
        printed = self._render("SELECT title FROM business_knowledge_documents", self.team)
        assert f"= {self.team.id}" in printed or f"{self.team.id})" in printed

    def test_sources_query_injects_team_id_predicate(self) -> None:
        printed = self._render("SELECT name FROM business_knowledge_sources", self.team)
        assert f"= {self.team.id}" in printed or f"{self.team.id})" in printed

    def test_all_three_tables_are_registered(self) -> None:
        from posthog.hogql.database.database import Database

        db = Database.create_for(team=self.team)
        # Registered under the `system` node.
        assert db.has_table(["business_knowledge_sources"]) or db.has_table(["system", "business_knowledge_sources"])
        assert db.has_table(["business_knowledge_documents"]) or db.has_table(
            ["system", "business_knowledge_documents"]
        )
        assert db.has_table(["business_knowledge_chunks"]) or db.has_table(["system", "business_knowledge_chunks"])
