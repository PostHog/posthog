from posthog.test.base import BaseTest

from posthog.hogql.errors import QueryError
from posthog.hogql.postgres_executor import PostgresQueryExecutor, PostgresQueryResult, format_postgres_result_for_llm


class TestPostgresQueryExecutor(BaseTest):
    def test_validate_query_blocks_non_select(self):
        executor = PostgresQueryExecutor("INSERT INTO dashboard VALUES (1)", self.team, self.user)
        with self.assertRaises(QueryError) as context:
            executor._validate_query()
        self.assertIn("SELECT", str(context.exception))

    def test_validate_query_blocks_dangerous_keywords(self):
        dangerous_queries = [
            "SELECT * FROM dashboard; DROP TABLE dashboard",
            "SELECT * FROM dashboard; DELETE FROM dashboard",
            "SELECT * FROM dashboard; UPDATE dashboard SET name='hacked'",
            "SELECT * FROM dashboard; TRUNCATE dashboard",
        ]

        for query in dangerous_queries:
            executor = PostgresQueryExecutor(query, self.team, self.user)
            with self.assertRaises(QueryError):
                executor._validate_query()

    def test_validate_query_allows_select(self):
        executor = PostgresQueryExecutor("SELECT name FROM dashboard", self.team, self.user)
        # Should not raise
        executor._validate_query()

    def test_build_context_sets_team_id(self):
        executor = PostgresQueryExecutor("SELECT 1", self.team, self.user)
        context = executor._build_context()
        self.assertEqual(context.team_id, self.team.id)
        self.assertEqual(context.user_id, self.user.id)

    def test_build_context_detects_org_admin(self):
        from posthog.models import OrganizationMembership

        # Make user an org admin
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save()

        executor = PostgresQueryExecutor("SELECT 1", self.team, self.user)
        context = executor._build_context()
        self.assertTrue(context.is_org_admin)


class TestFormatPostgresResultForLLM(BaseTest):
    def test_format_basic_result(self):
        result = PostgresQueryResult(
            columns=["name", "count"],
            rows=[
                {"name": "Dashboard 1", "count": 10},
                {"name": "Dashboard 2", "count": 5},
            ],
            row_count=2,
            truncated=False,
        )

        formatted = format_postgres_result_for_llm(result)

        self.assertIn("Dashboard 1", formatted)
        self.assertIn("Dashboard 2", formatted)
        self.assertIn("name", formatted)
        self.assertIn("count", formatted)

    def test_format_truncated_result(self):
        result = PostgresQueryResult(
            columns=["id"],
            rows=[{"id": 1}],
            row_count=1,
            truncated=True,
        )

        formatted = format_postgres_result_for_llm(result)

        self.assertIn("truncated", formatted.lower())
