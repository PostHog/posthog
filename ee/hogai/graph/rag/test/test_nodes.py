from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.utils import timezone

from azure.ai.inference import EmbeddingsClient
from azure.ai.inference.models import EmbeddingItem, EmbeddingsResult, EmbeddingsUsage
from azure.core.credentials import AzureKeyCredential

from posthog.schema import MaxActionContext, MaxUIContext, TeamTaxonomyQuery

from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Action
from posthog.models.ai.utils import PgEmbeddingRow, bulk_create_pg_embeddings

from ee.hogai.graph.rag.nodes import InsightRagContextNode
from ee.hogai.utils.types import AssistantState


@patch(
    "azure.ai.inference.EmbeddingsClient.embed",
    return_value=EmbeddingsResult(
        id="test",
        model="test",
        usage=EmbeddingsUsage(prompt_tokens=1, total_tokens=1),
        data=[EmbeddingItem(embedding=[2, 4], index=0)],
    ),
)
@patch(
    "ee.hogai.graph.rag.nodes.get_azure_embeddings_client",
    return_value=EmbeddingsClient(
        endpoint="https://test.services.ai.azure.com/models", credential=AzureKeyCredential("test")
    ),
)
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

    @patch("ee.hogai.graph.rag.nodes.TeamTaxonomyQueryRunner")
    def test_prewarm_queries(self, mock_team_taxonomy_query_runner, cohere_mock, embed_mock):
        # Arrange
        team = MagicMock()
        retriever = InsightRagContextNode(team=team, user=self.user)

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
        retriever = InsightRagContextNode(team=self.team, user=self.user)
        response = retriever.run(AssistantState(root_tool_insight_plan="Plan", messages=[]), {})
        assert response is not None
        assert response.rag_context is not None
        self.assertIn("Action", response.rag_context)
        self.assertIn("Description", response.rag_context)
        self.assertIn(str(self.action.id), response.rag_context)
        self.assertEqual(embed_mock.call_count, 1)

    @patch.object(InsightRagContextNode, "_get_ui_context")
    def test_injects_actions_from_context(self, mock_get_ui_context, cohere_mock, embed_mock):
        # Create a second action that will come from UI context
        context_action = Action.objects.create(
            team=self.team,
            name="Context Action",
            description="From UI Context",
            summary="Context Summary",
            last_summarized_at=timezone.now(),
            embedding_last_synced_at=timezone.now(),
        )

        # Mock UI context with actions
        mock_ui_context = MaxUIContext(
            actions=[MaxActionContext(id=context_action.id, name="Context Action", description="From UI Context")]
        )
        mock_get_ui_context.return_value = mock_ui_context

        retriever = InsightRagContextNode(team=self.team, user=self.user)
        response = retriever.run(AssistantState(root_tool_insight_plan="Plan", messages=[]), {})

        assert response is not None
        assert response.rag_context is not None
        # Should include both the vector-searched action and the context action
        self.assertIn("Action", response.rag_context)  # Original action from vector search
        self.assertIn("Context Action", response.rag_context)  # Action from UI context
        self.assertIn("From UI Context", response.rag_context)
        self.assertIn(str(context_action.id), response.rag_context)
        self.assertEqual(embed_mock.call_count, 1)

    @patch.object(InsightRagContextNode, "_get_ui_context")
    def test_handles_actions_context_when_embedding_fails(self, mock_get_ui_context, cohere_mock, embed_mock):
        # Make embedding fail
        embed_mock.side_effect = ValueError("Embedding failed")

        context_action = Action.objects.create(
            team=self.team,
            name="Context Only Action",
            description="Only from context",
        )

        mock_ui_context = MaxUIContext(
            actions=[
                MaxActionContext(id=context_action.id, name="Context Only Action", description="Only from context")
            ]
        )
        mock_get_ui_context.return_value = mock_ui_context

        retriever = InsightRagContextNode(team=self.team, user=self.user)
        response = retriever.run(AssistantState(root_tool_insight_plan="Plan", messages=[]), {})

        assert response is not None
        assert response.rag_context is not None
        # Should still include actions from context even when embedding fails
        self.assertIn("Context Only Action", response.rag_context)
        self.assertIn("Only from context", response.rag_context)
        self.assertIn(str(context_action.id), response.rag_context)
