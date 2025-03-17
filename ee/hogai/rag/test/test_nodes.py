from unittest.mock import MagicMock, patch

import cohere
from django.utils import timezone

from ee.hogai.rag.nodes import InsightRagContextNode
from ee.hogai.utils.types import AssistantState
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Action
from posthog.models.ai.utils import PgEmbeddingRow, bulk_create_pg_embeddings
from posthog.schema import TeamTaxonomyQuery
from posthog.test.base import BaseTest, ClickhouseTestMixin


@patch(
    "cohere.ClientV2.embed",
    return_value=cohere.EmbeddingsByTypeEmbedResponse(embeddings={"float_": [[2, 4]]}, texts=["test"], id="test"),
)
@patch("ee.hogai.rag.nodes.get_cohere_client", return_value=cohere.ClientV2(api_key="test"))
class TestInsightRagContextNode(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.action = Action.objects.create(
            team=self.team,
            name="Action",
            description="Description",
            summary="Summary",
            last_summarized_at=timezone.now(),
            embedding_last_synced_at=timezone.now(),
        )
        bulk_create_pg_embeddings(
            [PgEmbeddingRow(domain="action", team_id=self.team.id, id=str(self.action.id), vector=[2, 4], text="test")]
        )

    @patch("ee.hogai.rag.nodes.TeamTaxonomyQueryRunner")
    def test_prewarm_queries(self, mock_team_taxonomy_query_runner, cohere_mock, embed_mock):
        # Arrange
        team = MagicMock()
        retriever = InsightRagContextNode(team=team)

        mock_runner_instance = MagicMock()
        mock_team_taxonomy_query_runner.return_value = mock_runner_instance

        # Act
        retriever._prewarm_queries()

        # Assert
        mock_team_taxonomy_query_runner.assert_called_once()
        # Check TeamTaxonomyQueryRunner was instantiated with correct parameters
        args, kwargs = mock_team_taxonomy_query_runner.call_args
        assert isinstance(args[0], TeamTaxonomyQuery)
        assert args[1] == team

        # Check run was called with the correct execution mode
        mock_runner_instance.run.assert_called_once_with(ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE)

    def test_injects_action(self, cohere_mock, embed_mock):
        retriever = InsightRagContextNode(team=self.team)
        response = retriever.run(AssistantState(root_tool_insight_plan="Plan", messages=[]), {})
        self.assertIn("Action", response.rag_context)
        self.assertIn("Description", response.rag_context)
        self.assertIn(str(self.action.id), response.rag_context)
        self.assertEqual(embed_mock.call_count, 1)
