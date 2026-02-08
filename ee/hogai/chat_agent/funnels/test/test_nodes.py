from posthog.test.base import BaseTest
from unittest.mock import patch

from langchain_core.runnables import RunnableConfig, RunnableLambda

from posthog.schema import (
    ArtifactContentType,
    ArtifactSource,
    AssistantFunnelsFilter,
    AssistantFunnelsQuery,
    HumanMessage,
)

from ee.hogai.chat_agent.funnels.nodes import FunnelGeneratorNode, FunnelsSchemaGeneratorOutput
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import ArtifactRefMessage
from ee.models.assistant import Conversation


class TestFunnelsGeneratorNode(BaseTest):
    def setUp(self):
        super().setUp()
        self.schema = AssistantFunnelsQuery(series=[])
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)

    async def test_node_runs(self):
        node = FunnelGeneratorNode(self.team, self.user)
        config = RunnableConfig(configurable={"thread_id": str(self.conversation.id)})

        with patch.object(FunnelGeneratorNode, "_model") as generator_model_mock:
            generator_model_mock.return_value = RunnableLambda(
                lambda _: FunnelsSchemaGeneratorOutput(query=self.schema, name="", description="").model_dump()
            )
            # Call through __call__ to ensure config is set before context_manager is created
            new_state = await node(
                AssistantState(messages=[HumanMessage(content="Text")], plan="Plan", root_tool_insight_plan="question"),
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

    def test_schema_does_not_require_aggregation_by_hogql(self):
        """Catches the regression where the schema set funnelAggregateByHogQL."""
        schema = AssistantFunnelsQuery(series=[], funnelsFilter=AssistantFunnelsFilter())
        assert schema.funnelsFilter is not None
        self.assertIsNone(schema.funnelsFilter.funnelAggregateByHogQL)
