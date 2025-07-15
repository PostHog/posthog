import uuid
from flaky import flaky

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
                id="static_id",
                vector=[1],
                text="example text",
            )
        ]
        bulk_create_pg_embeddings(vectors)

        response = VectorSearchQueryRunner(VectorSearchQuery(embedding=[1]), self.team).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, "static_id")
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

        id1, id2 = str(uuid.uuid4()), str(uuid.uuid4())

        vectors = [
            PgEmbeddingRow(
                domain="action",
                team_id=self.team.id,
                id=id1,
                vector=[1],
                text="example text",
            ),
            PgEmbeddingRow(
                domain="action",
                team_id=team2.id,
                id=id2,
                vector=[1],
                text="example text",
            ),
        ]
        bulk_create_pg_embeddings(vectors)

        response = VectorSearchQueryRunner(VectorSearchQuery(embedding=[1]), self.team).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, id1)
        self.assertEqual(response.results[0].distance, 0)

    def test_vector_search_returns_distances_in_ascending_order(self):
        id1, id2 = str(uuid.uuid4()), str(uuid.uuid4())
        vectors = [
            PgEmbeddingRow(
                domain="action",
                team_id=self.team.id,
                id=id1,
                vector=[1, 4],
                text="example text",
            ),
            PgEmbeddingRow(
                domain="action",
                team_id=self.team.id,
                id=id2,
                vector=[4, 2],
                text="example text 2",
            ),
        ]
        bulk_create_pg_embeddings(vectors)

        response = VectorSearchQueryRunner(VectorSearchQuery(embedding=[2, 4]), self.team).calculate()
        self.assertEqual(len(response.results), 2)
        self.assertEqual(response.results[0].id, id1)
        self.assertEqual(response.results[1].id, id2)

    def test_vector_search_excludes_deleted_vectors(self):
        id1, id2 = str(uuid.uuid4()), str(uuid.uuid4())
        vectors = [
            PgEmbeddingRow(
                domain="action",
                team_id=self.team.id,
                id=id1,
                vector=[1, 4],
                text="example text",
                is_deleted=True,
            ),
            PgEmbeddingRow(
                domain="action",
                team_id=self.team.id,
                id=id2,
                vector=[4, 2],
                text="example text 2",
            ),
        ]
        bulk_create_pg_embeddings(vectors)

        response = VectorSearchQueryRunner(VectorSearchQuery(embedding=[2, 4]), self.team).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, id2)

    @flaky(max_runs=3, min_passes=1)
    def test_vector_search_selects_max_version(self):
        query = VectorSearchQuery(embedding=[2, 4])
        id = str(uuid.uuid4())
        # Version 1
        vectors = [
            PgEmbeddingRow(
                domain="action",
                team_id=self.team.id,
                id=id,
                vector=[1, 1],
                text="example text",
            ),
        ]
        bulk_create_pg_embeddings(vectors)

        response = VectorSearchQueryRunner(query, self.team).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, id)

        # Version 2
        vectors = [
            PgEmbeddingRow(
                domain="action",
                team_id=self.team.id,
                id=id,
                vector=[4, 2],
                text="example text 2",
            ),
        ]
        bulk_create_pg_embeddings(vectors)

        response = VectorSearchQueryRunner(query, self.team).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, id)
        self.assertAlmostEqual(response.results[0].distance, 0.2, delta=0.05)  # 0.19999999999999996

    def test_vector_search_saves_properties(self):
        query = VectorSearchQuery(embedding=[2, 4])
        id = str(uuid.uuid4())
        vectors = [
            PgEmbeddingRow(
                domain="action",
                team_id=self.team.id,
                id=id,
                vector=[1, 4],
                text="example text",
                properties={"test": "test"},
            ),
        ]
        bulk_create_pg_embeddings(vectors)

        response = VectorSearchQueryRunner(query, self.team).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, id)

    def test_vector_search_searches_by_the_embedding_version(self):
        """Test that vectors with older embedding versions are excluded from results."""
        id1, id2 = str(uuid.uuid4()), str(uuid.uuid4())

        # Create vector with old embedding version (version 1) using direct SQL
        vectors_old = [
            PgEmbeddingRow(
                domain="action",
                team_id=self.team.id,
                id=id1,
                vector=[2, 4],
                text="old version text",
            ),
        ]
        bulk_create_pg_embeddings(vectors_old, embedding_version=1)

        # Create vector with current embedding version (version 2)
        vectors_current = [
            PgEmbeddingRow(
                domain="action",
                team_id=self.team.id,
                id=id2,
                vector=[2, 4],
                text="current version text",
            ),
        ]
        bulk_create_pg_embeddings(vectors_current, embedding_version=2)

        response = VectorSearchQueryRunner(VectorSearchQuery(embedding=[2, 4]), self.team).calculate()
        self.assertEqual(len(response.results), 2)

        response = VectorSearchQueryRunner(
            VectorSearchQuery(embedding=[2, 4], embeddingVersion=1), self.team
        ).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, id1)

        response = VectorSearchQueryRunner(
            VectorSearchQuery(embedding=[2, 4], embeddingVersion=2), self.team
        ).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, id2)

    def test_vector_search_searches_if_the_embedding_version_is_not_specified(self):
        """Test that vectors without versions are handled."""
        id1, id2 = str(uuid.uuid4()), str(uuid.uuid4())

        # Create vector with old embedding version (version 1) using direct SQL
        vectors_old = [
            PgEmbeddingRow(
                domain="action",
                team_id=self.team.id,
                id=id1,
                vector=[2, 4],
                text="old version text",
            ),
        ]
        bulk_create_pg_embeddings(vectors_old, embedding_version=None)

        # Create vector with current embedding version (version 2)
        vectors_current = [
            PgEmbeddingRow(
                domain="action",
                team_id=self.team.id,
                id=id2,
                vector=[2, 4],
                text="current version text",
            ),
        ]
        bulk_create_pg_embeddings(vectors_current, embedding_version=1)

        response = VectorSearchQueryRunner(VectorSearchQuery(embedding=[2, 4]), self.team).calculate()
        self.assertEqual(len(response.results), 2)

        response = VectorSearchQueryRunner(
            VectorSearchQuery(embedding=[2, 4], embeddingVersion=1), self.team
        ).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, id2)
