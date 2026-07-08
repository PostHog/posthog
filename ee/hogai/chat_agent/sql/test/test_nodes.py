from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from langchain_core.runnables import RunnableConfig, RunnableLambda
from parameterized import parameterized

from posthog.schema import ArtifactContentType, ArtifactSource, AssistantToolCallMessage, FailureMessage, HumanMessage

from products.posthog_ai.backend.models.assistant import Conversation

from ee.hogai.chat_agent.schema_generator.nodes import SchemaGenerationException
from ee.hogai.chat_agent.sql.nodes import SQLGeneratorNode
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import ArtifactRefMessage


class TestSQLGeneratorNode(NonAtomicBaseTest):
    maxDiff = None
    # NonAtomicBaseTest truncates all tables (RESTART IDENTITY) after each test, so class-level
    # test data created once in setUpClass is gone by the second test. Recreate it per test.
    CLASS_DATA_LEVEL_SETUP = False

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

    @parameterized.expand(
        [
            ("with_tool_call", "tool_123", AssistantToolCallMessage),
            ("without_tool_call", None, FailureMessage),
        ]
    )
    async def test_node_handles_retry_exhaustion_gracefully(self, _name, root_tool_call_id, expected_message_type):
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
                    root_tool_call_id=root_tool_call_id,
                    root_tool_insight_plan="question",
                ),
                config,
            )

        assert new_state is not None
        self.assertEqual(len(new_state.messages), 1)
        msg = new_state.messages[0]
        self.assertIsInstance(msg, expected_message_type)
        assert isinstance(msg, AssistantToolCallMessage | FailureMessage)
        assert msg.content is not None
        self.assertIn("valid SQL query", msg.content)
        if isinstance(msg, AssistantToolCallMessage):
            self.assertEqual(msg.tool_call_id, root_tool_call_id)
        # Node ends gracefully and clears the tool call so the run terminates
        self.assertIsNone(new_state.root_tool_call_id)
        self.assertIsNone(new_state.intermediate_steps)
