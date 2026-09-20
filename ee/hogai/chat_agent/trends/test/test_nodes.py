from posthog.test.base import BaseTest
from unittest.mock import patch

from langchain_core.agents import AgentAction
from langchain_core.runnables import RunnableConfig, RunnableLambda

from posthog.schema import (
    ArtifactContentType,
    ArtifactSource,
    AssistantTrendsEventsNode,
    AssistantTrendsQuery,
    HumanMessage,
)

from products.posthog_ai.backend.models.assistant import Conversation

from ee.hogai.chat_agent.trends.nodes import TrendsGeneratorNode, TrendsSchemaGeneratorOutput
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import ArtifactRefMessage


class TestTrendsGeneratorNode(BaseTest):
    maxDiff = None

    def setUp(self):
        super().setUp()
        self.schema = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(event="$pageview", math="dau")])
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)

    async def _run_node(self, schema, intermediate_steps=None):
        node = TrendsGeneratorNode(self.team, self.user)
        config = RunnableConfig(configurable={"thread_id": str(self.conversation.id)})
        with patch.object(TrendsGeneratorNode, "_model") as generator_model_mock:
            generator_model_mock.return_value = RunnableLambda(
                lambda _: TrendsSchemaGeneratorOutput(query=schema, name="", description="").model_dump()
            )
            # Call through __call__ to ensure config is set before context_manager is created
            return await node(
                AssistantState(
                    messages=[HumanMessage(content="Text")],
                    plan="Plan",
                    root_tool_insight_plan="question",
                    intermediate_steps=intermediate_steps,
                ),
                config,
            )

    async def test_node_runs(self):
        new_state = await self._run_node(self.schema)

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

    async def test_node_retries_when_the_query_reports_a_wrong_number(self):
        # `avg` without `math_property` silently counts events instead of averaging
        unsound_schema = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(event="$pageview", math="avg")])

        new_state = await self._run_node(unsound_schema)

        assert new_state is not None
        assert new_state.intermediate_steps is not None
        self.assertEqual(len(new_state.intermediate_steps), 1)
        self.assertIn("math_property", new_state.intermediate_steps[0][0].log)
        self.assertEqual(new_state.query_generation_retry_count, 1)

    async def test_node_presents_the_query_once_the_retries_run_out(self):
        unsound_schema = AssistantTrendsQuery(series=[AssistantTrendsEventsNode(event="$pageview", math="avg")])
        exhausted_steps = [(AgentAction("handle_incorrect_response", "", ""), None)] * 2

        new_state = await self._run_node(unsound_schema, intermediate_steps=exhausted_steps)

        assert new_state is not None
        self.assertEqual(len(new_state.messages), 1)
        self.assertIsNone(new_state.intermediate_steps)
