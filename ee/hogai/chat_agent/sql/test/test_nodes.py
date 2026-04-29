from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from langchain_core.runnables import RunnableConfig, RunnableLambda

from posthog.schema import ArtifactContentType, ArtifactSource, HumanMessage

from ee.hogai.chat_agent.sql.nodes import SQLGeneratorNode
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import ArtifactRefMessage
from ee.models.assistant import Conversation


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
            assert len(new_state.messages) == 1
            msg = new_state.messages[0]
            assert isinstance(msg, ArtifactRefMessage)
            assert isinstance(msg, ArtifactRefMessage)
            assert msg.content_type == ArtifactContentType.VISUALIZATION
            assert msg.source == ArtifactSource.ARTIFACT
            assert msg.artifact_id is not None

            # Verify node clears these state fields
            assert new_state.intermediate_steps is None
            assert new_state.plan is None
            assert new_state.rag_context is None
