from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from langchain_core.runnables import RunnableConfig, RunnableLambda

from posthog.schema import ArtifactContentType, ArtifactSource, AssistantToolCallMessage, HumanMessage

from products.posthog_ai.backend.models.assistant import Conversation

from ee.hogai.chat_agent.schema_generator.nodes import SchemaGenerationException
from ee.hogai.chat_agent.sql.nodes import SQLGeneratorNode
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import ArtifactRefMessage


class TestSQLGeneratorNode(NonAtomicBaseTest):
    maxDiff = None

    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)

    async def test_node_runs(self):
        node = SQLGeneratorNode(self.team, self.user)
        config = RunnableConfig(configurable={"thread_id": str(self.conversation.id)})
        # The model should return a dict with query, name, and description
        answer = {"query": "SELECT 1", "name": "", "description": ""}

        with patch.object(SQLGeneratorNode, "_model") as generator_model_mock:
            generator_model_mock.return_value = RunnableLambda(lambda _: answer)
            # Call through __call__ to ensure config is set before context_manager is created
            new_state = await node(
                AssistantState(
                    messages=[HumanMessage(content="Text")],
                    plan="Plan",
                    root_tool_insight_plan="question",
                ),
                config,
            )

            # Verify node output contains ArtifactRefMessage pointing to database artifact
            assert new_state is not None
            self.assertEqual(len(new_state.messages), 1)
            msg = new_state.messages[0]
            self.assertIsInstance(msg, ArtifactRefMessage)
            assert isinstance(msg, ArtifactRefMessage)
            self.assertEqual(msg.content_type, ArtifactContentType.VISUALIZATION)
            self.assertEqual(msg.source, ArtifactSource.ARTIFACT)
            self.assertIsNotNone(msg.artifact_id)

            # Verify node clears these state fields
            self.assertIsNone(new_state.intermediate_steps)
            self.assertIsNone(new_state.plan)
            self.assertIsNone(new_state.rag_context)

    async def test_node_handles_retry_exhaustion_gracefully(self):
        node = SQLGeneratorNode(self.team, self.user)
        config = RunnableConfig(configurable={"thread_id": str(self.conversation.id)})

        async def _raise(*args, **kwargs):
            raise SchemaGenerationException(
                "WITH date_end AS toDate(now()) SELECT 1",
                "HogQL parsing error: this query isn't valid HogQL.",
            )

        with patch("ee.hogai.chat_agent.schema_generator.nodes.SchemaGeneratorNode._run_with_prompt", new=_raise):
            new_state = await node(
                AssistantState(
                    messages=[HumanMessage(content="Text")],
                    plan="Plan",
                    root_tool_call_id="tool_123",
                    root_tool_insight_plan="question",
                ),
                config,
            )

        assert new_state is not None
        self.assertEqual(len(new_state.messages), 1)
        msg = new_state.messages[0]
        self.assertIsInstance(msg, AssistantToolCallMessage)
        assert isinstance(msg, AssistantToolCallMessage)
        self.assertEqual(msg.tool_call_id, "tool_123")
        self.assertIn("valid SQL query", msg.content)
        # Node ends gracefully and clears the tool call so the run terminates
        self.assertIsNone(new_state.root_tool_call_id)
        self.assertIsNone(new_state.intermediate_steps)
