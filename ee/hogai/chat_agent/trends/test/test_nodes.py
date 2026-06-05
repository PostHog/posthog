from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from langchain_core.runnables import RunnableConfig, RunnableLambda

from posthog.schema import (
    AggregationAxisFormat,
    ArtifactContentType,
    ArtifactSource,
    AssistantTrendsFilter,
    AssistantTrendsQuery,
    HumanMessage,
)

from products.posthog_ai.backend.models.assistant import Conversation

from ee.hogai.chat_agent.trends.nodes import (
    TrendsGeneratorNode,
    TrendsSchemaGeneratorOutput,
    _strip_redundant_percentage_postfix,
)
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import ArtifactRefMessage


class TestTrendsGeneratorNode(BaseTest):
    maxDiff = None

    def setUp(self):
        super().setUp()
        self.schema = AssistantTrendsQuery(series=[])
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)

    async def test_node_runs(self):
        node = TrendsGeneratorNode(self.team, self.user)
        config = RunnableConfig(configurable={"thread_id": str(self.conversation.id)})

        with patch.object(TrendsGeneratorNode, "_model") as generator_model_mock:
            generator_model_mock.return_value = RunnableLambda(
                lambda _: TrendsSchemaGeneratorOutput(query=self.schema, name="", description="").model_dump()
            )
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


class TestStripRedundantPercentagePostfix(BaseTest):
    @parameterized.expand(
        [
            ("percentage", AggregationAxisFormat.PERCENTAGE, "%"),
            ("percentage_scaled", AggregationAxisFormat.PERCENTAGE_SCALED, "%"),
            ("percentage_with_whitespace", AggregationAxisFormat.PERCENTAGE, " % "),
        ]
    )
    def test_strips_redundant_postfix(self, _name, axis_format, postfix):
        query = AssistantTrendsQuery(
            series=[],
            trendsFilter=AssistantTrendsFilter(aggregationAxisFormat=axis_format, aggregationAxisPostfix=postfix),
        )
        _strip_redundant_percentage_postfix(query)
        assert query.trendsFilter is not None
        self.assertIsNone(query.trendsFilter.aggregationAxisPostfix)

    @parameterized.expand(
        [
            ("numeric_keeps_percent_postfix", AggregationAxisFormat.NUMERIC, "%"),
            ("percentage_keeps_unit_postfix", AggregationAxisFormat.PERCENTAGE, " clicks"),
        ]
    )
    def test_keeps_legitimate_postfix(self, _name, axis_format, postfix):
        query = AssistantTrendsQuery(
            series=[],
            trendsFilter=AssistantTrendsFilter(aggregationAxisFormat=axis_format, aggregationAxisPostfix=postfix),
        )
        _strip_redundant_percentage_postfix(query)
        assert query.trendsFilter is not None
        self.assertEqual(query.trendsFilter.aggregationAxisPostfix, postfix)

    def test_handles_missing_trends_filter(self):
        query = AssistantTrendsQuery(series=[])
        _strip_redundant_percentage_postfix(query)  # should not raise
        self.assertIsNone(query.trendsFilter)

    def test_handles_missing_postfix(self):
        query = AssistantTrendsQuery(
            series=[],
            trendsFilter=AssistantTrendsFilter(aggregationAxisFormat=AggregationAxisFormat.PERCENTAGE),
        )
        _strip_redundant_percentage_postfix(query)
        assert query.trendsFilter is not None
        self.assertIsNone(query.trendsFilter.aggregationAxisPostfix)
