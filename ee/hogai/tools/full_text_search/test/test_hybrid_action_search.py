from posthog.test.base import NonAtomicBaseTest
from unittest.mock import AsyncMock, patch

from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from posthog.schema import CachedVectorSearchQueryResponse, VectorSearchResponseItem

from posthog.models import Action

from ee.hogai.context import AssistantContextManager
from ee.hogai.tools.full_text_search.hybrid_action_search import HybridActionSearchTool
from ee.hogai.utils.types.base import AssistantState


class TestHybridActionSearchTool(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.tool = HybridActionSearchTool(
            team=self.team,
            user=self.user,
            state=AssistantState(messages=[]),
            config=RunnableConfig(configurable={}),
            context_manager=AssistantContextManager(self.team, self.user, {}),
        )

    @parameterized.expand(
        [
            # Vector only
            (
                [("1", 0.1), ("2", 0.2)],
                [],
                ["1", "2"],
            ),
            # FTS only
            (
                [],
                [("3", 0.9), ("4", 0.8)],
                ["3", "4"],
            ),
            # Empty both
            (
                [],
                [],
                [],
            ),
        ]
    )
    def test_reciprocal_rank_fusion(self, vector_results, fts_results, expected_order):
        result = self.tool._reciprocal_rank_fusion(vector_results, fts_results)
        self.assertEqual(result, expected_order)

    def test_rrf_overlapping_results_ranked_higher(self):
        """Items appearing in both result sets should rank higher."""
        vector_results = [("1", 0.1), ("2", 0.2), ("3", 0.3)]
        fts_results = [("1", 0.9), ("4", 0.8), ("5", 0.7)]

        result = self.tool._reciprocal_rank_fusion(vector_results, fts_results)

        # "1" appears in both, so it must be ranked first
        self.assertEqual(result[0], "1")
        # All IDs should be present
        self.assertEqual(set(result), {"1", "2", "3", "4", "5"})

    def test_rrf_all_overlapping(self):
        """When all items overlap, order depends on combined rank positions."""
        # Vector: 1 at rank 1, 2 at rank 2, 3 at rank 3
        vector_results = [("1", 0.1), ("2", 0.2), ("3", 0.3)]
        # FTS: 1 at rank 1, 2 at rank 2, 3 at rank 3
        fts_results = [("1", 0.9), ("2", 0.8), ("3", 0.7)]

        result = self.tool._reciprocal_rank_fusion(vector_results, fts_results)

        # All items overlap, check all are present
        self.assertEqual(set(result), {"1", "2", "3"})
        # "1" appears at rank 1 in both → highest combined score
        # "2" appears at rank 2 in both → second highest
        # "3" appears at rank 3 in both → lowest
        # 1's score: 1/(60+1) + 1/(60+1) = 2/61 ≈ 0.0328
        # 2's score: 1/(60+2) + 1/(60+2) = 2/62 ≈ 0.0323
        # 3's score: 1/(60+3) + 1/(60+3) = 2/63 ≈ 0.0317
        self.assertEqual(result, ["1", "2", "3"])

    def test_rrf_scoring_formula(self):
        """Verify the RRF formula: score = sum(1/(k + rank)) for each retriever."""
        # Doc appears at rank 1 in vector, rank 2 in FTS
        vector_results = [("doc1", 0.1), ("doc2", 0.2)]
        fts_results = [("doc3", 0.9), ("doc1", 0.8)]

        result = self.tool._reciprocal_rank_fusion(vector_results, fts_results)

        # With k=60:
        # doc1: 1/(60+1) + 1/(60+2) = 0.01639 + 0.01613 = 0.03252
        # doc3: 1/(60+1) = 0.01639
        # doc2: 1/(60+2) = 0.01613
        # Expected order: doc1, doc3, doc2
        self.assertEqual(result[0], "doc1")

    @patch("ee.hogai.tools.full_text_search.hybrid_action_search.settings")
    async def test_vector_search_disabled_when_no_credentials(self, mock_settings):
        mock_settings.AZURE_INFERENCE_ENDPOINT = None
        mock_settings.AZURE_INFERENCE_CREDENTIAL = None

        result = await self.tool._vector_search("test query")
        self.assertEqual(result, [])

    @patch("ee.hogai.tools.full_text_search.hybrid_action_search.database_sync_to_async")
    @patch("ee.hogai.tools.full_text_search.hybrid_action_search.get_async_azure_embeddings_client")
    @patch("ee.hogai.tools.full_text_search.hybrid_action_search.aembed_search_query")
    @patch("ee.hogai.tools.full_text_search.hybrid_action_search.settings")
    async def test_vector_search_returns_results(self, mock_settings, mock_embed, mock_get_client, mock_db_sync):
        mock_settings.AZURE_INFERENCE_ENDPOINT = "https://test.endpoint"
        mock_settings.AZURE_INFERENCE_CREDENTIAL = "test-credential"

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_get_client.return_value = mock_client
        mock_embed.return_value = [0.1] * 1024

        mock_response = CachedVectorSearchQueryResponse(
            results=[
                VectorSearchResponseItem(id="1", distance=0.1),
                VectorSearchResponseItem(id="2", distance=0.2),
            ],
            cache_key="test_cache_key",
            is_cached=False,
            last_refresh="2024-01-01T00:00:00Z",
            next_allowed_client_refresh="2024-01-01T00:01:00Z",
            timezone="UTC",
        )

        # Mock database_sync_to_async to return an async function that returns mock_response
        async def mock_run(*args, **kwargs):
            return mock_response

        mock_db_sync.return_value = mock_run

        result = await self.tool._vector_search("test query")

        self.assertEqual(result, [("1", 0.1), ("2", 0.2)])
        mock_client.__aexit__.assert_called_once()

    @patch("ee.hogai.tools.full_text_search.hybrid_action_search.search_entities")
    async def test_fts_search_returns_results(self, mock_search):
        mock_search.return_value = (
            [
                {"result_id": "1", "rank": 0.9},
                {"result_id": "2", "rank": 0.8},
            ],
            {"action": 2},
        )

        result = await self.tool._fts_search("test query")

        self.assertEqual(result, [("1", 0.9), ("2", 0.8)])

    async def test_fetch_actions_preserves_order(self):
        action1 = await Action.objects.acreate(team=self.team, name="First Action", created_by=self.user)
        action2 = await Action.objects.acreate(team=self.team, name="Second Action", created_by=self.user)
        action3 = await Action.objects.acreate(team=self.team, name="Third Action", created_by=self.user)

        # Request in specific order (reversed)
        action_ids = [str(action3.id), str(action1.id), str(action2.id)]

        result = await self.tool._fetch_actions(action_ids)

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0].id, action3.id)
        self.assertEqual(result[1].id, action1.id)
        self.assertEqual(result[2].id, action2.id)

    async def test_fetch_actions_excludes_deleted(self):
        active = await Action.objects.acreate(team=self.team, name="Active", deleted=False, created_by=self.user)
        deleted = await Action.objects.acreate(team=self.team, name="Deleted", deleted=True, created_by=self.user)

        result = await self.tool._fetch_actions([str(active.id), str(deleted.id)])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, active.id)

    @patch("ee.hogai.tools.full_text_search.hybrid_action_search.HybridActionSearchTool._vector_search")
    @patch("ee.hogai.tools.full_text_search.hybrid_action_search.HybridActionSearchTool._fts_search")
    async def test_execute_combines_results(self, mock_fts, mock_vector):
        action1 = await Action.objects.acreate(
            team=self.team, name="Signup Action", description="User signup", created_by=self.user
        )
        action2 = await Action.objects.acreate(
            team=self.team, name="Login Action", description="User login", created_by=self.user
        )

        mock_vector.return_value = [(str(action1.id), 0.1)]
        mock_fts.return_value = [(str(action2.id), 0.9), (str(action1.id), 0.8)]

        result = await self.tool.execute("signup")

        self.assertEqual(len(result), 2)
        # action1 should be first (appears in both)
        self.assertEqual(result[0]["id"], str(action1.id))
        self.assertEqual(result[0]["name"], "Signup Action")
        self.assertIn("vector", result[0]["sources"])
        self.assertIn("fts", result[0]["sources"])

        self.assertEqual(result[1]["id"], str(action2.id))
        self.assertIn("fts", result[1]["sources"])
        self.assertNotIn("vector", result[1]["sources"])

    @patch("ee.hogai.tools.full_text_search.hybrid_action_search.HybridActionSearchTool._vector_search")
    @patch("ee.hogai.tools.full_text_search.hybrid_action_search.HybridActionSearchTool._fts_search")
    async def test_execute_handles_vector_failure_gracefully(self, mock_fts, mock_vector):
        action = await Action.objects.acreate(team=self.team, name="Test Action", created_by=self.user)

        mock_vector.side_effect = Exception("Embedding service unavailable")
        mock_fts.return_value = [(str(action.id), 0.9)]

        result = await self.tool.execute("test")

        # Should still return FTS results
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], str(action.id))

    @patch("ee.hogai.tools.full_text_search.hybrid_action_search.HybridActionSearchTool._vector_search")
    @patch("ee.hogai.tools.full_text_search.hybrid_action_search.HybridActionSearchTool._fts_search")
    async def test_execute_handles_fts_failure_gracefully(self, mock_fts, mock_vector):
        action = await Action.objects.acreate(team=self.team, name="Test Action", created_by=self.user)

        mock_vector.return_value = [(str(action.id), 0.1)]
        mock_fts.side_effect = Exception("Database unavailable")

        result = await self.tool.execute("test")

        # Should still return vector results
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], str(action.id))

    @patch("ee.hogai.tools.full_text_search.hybrid_action_search.HybridActionSearchTool._vector_search")
    @patch("ee.hogai.tools.full_text_search.hybrid_action_search.HybridActionSearchTool._fts_search")
    async def test_execute_returns_empty_when_both_fail(self, mock_fts, mock_vector):
        mock_vector.side_effect = Exception("Embedding service unavailable")
        mock_fts.side_effect = Exception("Database unavailable")

        result = await self.tool.execute("test")

        self.assertEqual(result, [])

    @patch("ee.hogai.tools.full_text_search.hybrid_action_search.HybridActionSearchTool._vector_search")
    @patch("ee.hogai.tools.full_text_search.hybrid_action_search.HybridActionSearchTool._fts_search")
    async def test_execute_respects_max_results(self, mock_fts, mock_vector):
        # Create more actions than MAX_RESULTS
        actions = []
        for i in range(15):
            action = await Action.objects.acreate(team=self.team, name=f"Action {i}", created_by=self.user)
            actions.append(action)

        mock_vector.return_value = [(str(a.id), i * 0.1) for i, a in enumerate(actions[:10])]
        mock_fts.return_value = [(str(a.id), 1 - i * 0.1) for i, a in enumerate(actions[5:])]

        result = await self.tool.execute("test")

        self.assertLessEqual(len(result), self.tool.MAX_RESULTS)
