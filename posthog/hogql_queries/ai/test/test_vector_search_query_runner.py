from posthog.hogql_queries.ai.vector_search_query_runner import VectorSearchQueryRunner
from posthog.models import Organization, Project, Team
from posthog.models.ai.utils import PgEmbeddingRow, bulk_create_pg_embeddings
from posthog.schema import VectorSearchQuery
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    snapshot_clickhouse_queries,
)


class TestVectorSearchQueryRunner(ClickhouseTestMixin, APIBaseTest):
    @snapshot_clickhouse_queries
    def test_vector_search_query_runner(self):
        vectors = [
            PgEmbeddingRow(
                domain="action",
                team_id=self.team.id,
                id="1",
                vector=[1],
                text="example text",
            )
        ]
        bulk_create_pg_embeddings(vectors)

        response = VectorSearchQueryRunner(VectorSearchQuery(embedding=[1]), self.team).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, "1")
        self.assertEqual(response.results[0].distance, 0)

    def test_vector_search_only_returns_this_team_vectors(self):
        organization = Organization.objects.create(name="Org 2")
        project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=organization)
        team2 = Team.objects.create(
            id=project.id,
            project=project,
            organization=organization,
            api_token="token2",
            test_account_filters=[
                {
                    "key": "email",
                    "value": "@posthog.com",
                    "operator": "not_icontains",
                    "type": "person",
                }
            ],
            has_completed_onboarding_for={"product_analytics": True},
        )

        vectors = [
            PgEmbeddingRow(
                domain="action",
                team_id=self.team.id,
                id="1",
                vector=[1],
                text="example text",
            ),
            PgEmbeddingRow(
                domain="action",
                team_id=team2.id,
                id="2",
                vector=[1],
                text="example text",
            ),
        ]
        bulk_create_pg_embeddings(vectors)

        response = VectorSearchQueryRunner(VectorSearchQuery(embedding=[1]), self.team).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, "1")
        self.assertEqual(response.results[0].distance, 0)

    def test_vector_search_returns_distances_in_ascending_order(self):
        vectors = [
            PgEmbeddingRow(
                domain="action",
                team_id=self.team.id,
                id="1",
                vector=[1, 4],
                text="example text",
            ),
            PgEmbeddingRow(
                domain="action",
                team_id=self.team.id,
                id="2",
                vector=[4, 2],
                text="example text 2",
            ),
        ]
        bulk_create_pg_embeddings(vectors)

        response = VectorSearchQueryRunner(VectorSearchQuery(embedding=[2, 4]), self.team).calculate()
        self.assertEqual(len(response.results), 2)
        self.assertEqual(response.results[0].id, "1")
        self.assertAlmostEqual(response.results[0].distance, 0.024, places=3)  # 0.02381293981604715
        self.assertEqual(response.results[1].id, "2")
        self.assertAlmostEqual(response.results[1].distance, 0.2, places=3)  # 0.19999999999999996

    def test_vector_search_excludes_deleted_vectors(self):
        vectors = [
            PgEmbeddingRow(
                domain="action",
                team_id=self.team.id,
                id="1",
                vector=[1, 4],
                text="example text",
                is_deleted=True,
            ),
            PgEmbeddingRow(
                domain="action",
                team_id=self.team.id,
                id="2",
                vector=[4, 2],
                text="example text 2",
            ),
        ]
        bulk_create_pg_embeddings(vectors)

        response = VectorSearchQueryRunner(VectorSearchQuery(embedding=[2, 4]), self.team).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, "2")
        self.assertAlmostEqual(response.results[0].distance, 0.2, places=3)  # 0.19999999999999996

    def test_vector_search_selects_max_version(self):
        query = VectorSearchQuery(embedding=[2, 4])

        # Version 1
        vectors = [
            PgEmbeddingRow(
                domain="action",
                team_id=self.team.id,
                id="1",
                vector=[1, 4],
                text="example text",
            ),
        ]
        bulk_create_pg_embeddings(vectors)

        response = VectorSearchQueryRunner(query, self.team).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, "1")
        self.assertAlmostEqual(response.results[0].distance, 0.024, places=3)  # 0.02381293981604715

        # Version 2
        vectors = [
            PgEmbeddingRow(
                domain="action",
                team_id=self.team.id,
                id="1",
                vector=[4, 2],
                text="example text 2",
            ),
        ]
        bulk_create_pg_embeddings(vectors)

        response = VectorSearchQueryRunner(query, self.team).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, "1")
        self.assertAlmostEqual(response.results[0].distance, 0.2, places=2)  # 0.19999999999999996

    def test_vector_search_saves_properties(self):
        query = VectorSearchQuery(embedding=[2, 4])
        vectors = [
            PgEmbeddingRow(
                domain="action",
                team_id=self.team.id,
                id="1",
                vector=[1, 4],
                text="example text",
                properties={"test": "test"},
            ),
        ]
        bulk_create_pg_embeddings(vectors)

        response = VectorSearchQueryRunner(query, self.team).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, "1")
        self.assertAlmostEqual(response.results[0].distance, 0.024, places=3)  # 0.02381293981604715
