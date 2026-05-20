from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from langchain_core.runnables import RunnableConfig, RunnableLambda

from posthog.schema import ArtifactContentType, ArtifactSource, DataVisualizationNode, HumanMessage

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

    async def test_node_threads_show_values_on_series_into_chart_settings(self):
        """When the LLM returns show_values_on_series, it must flow into the persisted chartSettings."""
        node = SQLGeneratorNode(self.team, self.user)
        config = RunnableConfig(configurable={"thread_id": str(self.conversation.id)})
        answer = {
            "query": "SELECT browser, count() AS sessions FROM events GROUP BY browser",
            "display": "ActionsBar",
            "x_axis": "browser",
            "y_axis": ["sessions"],
            "series_breakdown_column": None,
            "y_axis_format": "short",
            "y_axis_decimal_places": 0,
            "y_axis_prefix": None,
            "y_axis_suffix": None,
            "show_legend": False,
            "show_values_on_series": True,
            "show_percent_stack_view": False,
            "name": "",
            "description": "",
        }

        with patch.object(SQLGeneratorNode, "_model") as generator_model_mock:
            generator_model_mock.return_value = RunnableLambda(lambda _: answer)
            new_state = await node(
                AssistantState(
                    messages=[HumanMessage(content="Add labels to the bar chart")],
                    plan="Plan",
                    root_tool_insight_plan="question",
                ),
                config,
            )

        assert new_state is not None
        msg = new_state.messages[0]
        assert isinstance(msg, ArtifactRefMessage)
        content = await node.context_manager.artifacts.aget(msg.artifact_id)
        query = content.query
        assert isinstance(query, DataVisualizationNode)
        assert query.chartSettings is not None
        self.assertTrue(query.chartSettings.showValuesOnSeries)
        self.assertIsNone(query.chartSettings.stackBars100)
