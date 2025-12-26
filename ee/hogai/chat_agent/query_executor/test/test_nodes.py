from typing import cast
from uuid import uuid4

from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest
from unittest.mock import patch

from rest_framework.exceptions import ValidationError

from posthog.schema import (
    ArtifactContentType,
    ArtifactSource,
    AssistantFunnelsFilter,
    AssistantFunnelsQuery,
    AssistantMessage,
    AssistantRetentionEventsNode,
    AssistantRetentionFilter,
    AssistantRetentionQuery,
    AssistantToolCall,
    AssistantToolCallMessage,
    AssistantTrendsEventsNode,
    AssistantTrendsQuery,
    FunnelVizType,
    HumanMessage,
    QueryStatus,
    VisualizationArtifactContent,
    VisualizationMessage,
)

from posthog.api.services.query import process_query_dict

from ee.hogai.artifacts.manager import ArtifactManager
from ee.hogai.chat_agent.query_executor.nodes import QueryExecutorNode
from ee.hogai.context.insight.prompts import (
    FUNNEL_STEPS_EXAMPLE_PROMPT,
    FUNNEL_TIME_TO_CONVERT_EXAMPLE_PROMPT,
    FUNNEL_TRENDS_EXAMPLE_PROMPT,
    RETENTION_EXAMPLE_PROMPT,
    TRENDS_EXAMPLE_PROMPT,
)
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import ArtifactRefMessage, PartialAssistantState
from ee.models import AgentArtifact, Conversation


class TestQueryExecutorNode(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False
    maxDiff = None

    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(user=self.user, team=self.team)
        self.artifact_manager = ArtifactManager(self.team, self.user)

    @patch("ee.hogai.context.insight.query_executor.process_query_dict", side_effect=process_query_dict)
    async def test_node_legacy_viz_message_runs(self, mock_process_query_dict):
        node = QueryExecutorNode(self.team, self.user)
        new_state = await node.arun(
            AssistantState(
                messages=[
                    HumanMessage(content="Text", id="test"),
                    AssistantMessage(
                        content="Text",
                        id="test2",
                        tool_calls=[
                            AssistantToolCall(
                                id="tool1",
                                name="create_and_query_insight",
                                args={"query_kind": "trends", "query_description": "test query"},
                            )
                        ],
                    ),
                    VisualizationMessage(
                        answer=AssistantTrendsQuery(series=[AssistantTrendsEventsNode()]),
                        plan="Plan",
                        id="test3",
                        initiator="test",
                    ),
                ],
                plan="Plan",
                start_id="test",
                root_tool_call_id="tool1",
                root_tool_insight_plan="test query",
                root_tool_insight_type="trends",
            ),
            {},
        )
        new_state = cast(PartialAssistantState, new_state)
        mock_process_query_dict.assert_called_once()  # Query processing started
        msg = cast(AssistantToolCallMessage, new_state.messages[0])
        self.assertIn(
            "Here is the results table of the TrendsQuery created to answer your latest question:", msg.content
        )
        self.assertEqual(msg.type, "tool")
        self.assertEqual(msg.tool_call_id, "tool1")
        self.assertIsNotNone(msg.id)
        self.assertFalse(new_state.root_tool_call_id)
        self.assertFalse(new_state.root_tool_insight_plan)
        self.assertFalse(new_state.root_tool_insight_type)

    @patch("ee.hogai.context.insight.query_executor.process_query_dict", side_effect=process_query_dict)
    async def test_node_runs(self, mock_process_query_dict):
        node = QueryExecutorNode(self.team, self.user)

        insight = await AgentArtifact.objects.acreate(
            name="test insight",
            type=AgentArtifact.Type.VISUALIZATION,
            data=VisualizationArtifactContent(
                query=AssistantTrendsQuery(series=[]), name="test insight", description="test description"
            ).model_dump(),
            conversation=self.conversation,
            team=self.team,
        )
        new_state = await node.arun(
            AssistantState(
                messages=[
                    HumanMessage(content="Text", id="test"),
                    AssistantMessage(
                        content="Text",
                        id="test2",
                        tool_calls=[
                            AssistantToolCall(
                                id="tool1",
                                name="create_and_query_insight",
                                args={"query_kind": "trends", "query_description": "test query"},
                            )
                        ],
                    ),
                    ArtifactRefMessage(
                        content_type=ArtifactContentType.VISUALIZATION,
                        source=ArtifactSource.ARTIFACT,
                        artifact_id=str(insight.short_id),
                        id=str(uuid4()),
                    ),
                ],
                plan="Plan",
                start_id="test",
                root_tool_call_id="tool1",
                root_tool_insight_plan="test query",
                root_tool_insight_type="trends",
            ),
            {},
        )
        new_state = cast(PartialAssistantState, new_state)
        mock_process_query_dict.assert_called_once()  # Query processing started
        msg = cast(AssistantToolCallMessage, new_state.messages[0])
        self.assertIn(
            "Here is the results table of the TrendsQuery created to answer your latest question:", msg.content
        )
        self.assertIn(f"Insight ID: {insight.short_id}", msg.content)
        self.assertIn("Name: test insight", msg.content)
        self.assertIn("Description: test description", msg.content)
        self.assertEqual(msg.type, "tool")
        self.assertEqual(msg.tool_call_id, "tool1")
        self.assertIsNotNone(msg.id)
        self.assertFalse(new_state.root_tool_call_id)
        self.assertFalse(new_state.root_tool_insight_plan)
        self.assertFalse(new_state.root_tool_insight_type)

    @patch(
        "ee.hogai.context.insight.query_executor.process_query_dict",
        side_effect=ValueError("You have not glibbled the glorp before running this."),
    )
    async def test_node_handles_internal_error(self, mock_process_query_dict):
        node = QueryExecutorNode(self.team, self.user)
        artifact = await AgentArtifact.objects.acreate(
            name="test insight",
            type=AgentArtifact.Type.VISUALIZATION,
            data=VisualizationArtifactContent(
                query=AssistantTrendsQuery(series=[]), name="test insight", description="test description"
            ).model_dump(),
            conversation=self.conversation,
            team=self.team,
        )
        artifact_message = ArtifactRefMessage(
            content_type=ArtifactContentType.VISUALIZATION,
            source=ArtifactSource.ARTIFACT,
            artifact_id=artifact.short_id,
            id="123",
        )
        new_state = await node.arun(
            AssistantState(
                messages=[
                    HumanMessage(content="Text", id="test"),
                    artifact_message,
                ],
                plan="Plan",
                start_id="test",
                root_tool_call_id="tool1",
                root_tool_insight_plan="test query",
                root_tool_insight_type="trends",
            ),
            {},
        )
        new_state = cast(PartialAssistantState, new_state)
        mock_process_query_dict.assert_called_once()  # Query processing started
        msg = cast(AssistantMessage, new_state.messages[0])
        self.assertEqual(
            msg.content,
            "There was an error running this query: Error executing query: There was an unknown error running this query.",
        )
        self.assertEqual(msg.type, "ai")
        self.assertIsNotNone(msg.id)

    @patch(
        "ee.hogai.context.insight.query_executor.process_query_dict",
        side_effect=ValidationError(
            "This query exceeds the capabilities of our picolator. Try de-brolling its flim-flam."
        ),
    )
    async def test_node_handles_exposed_error(self, mock_process_query_dict):
        node = QueryExecutorNode(self.team, self.user)
        insight = await AgentArtifact.objects.acreate(
            name="test insight",
            type=AgentArtifact.Type.VISUALIZATION,
            data=VisualizationArtifactContent(
                query=AssistantTrendsQuery(series=[]), name="test insight", description="test description"
            ).model_dump(),
            conversation=self.conversation,
            team=self.team,
        )
        new_state = await node.arun(
            AssistantState(
                messages=[
                    HumanMessage(content="Text", id="test"),
                    ArtifactRefMessage(
                        content_type=ArtifactContentType.VISUALIZATION,
                        source=ArtifactSource.ARTIFACT,
                        artifact_id=str(insight.short_id),
                        id=str(uuid4()),
                    ),
                ],
                plan="Plan",
                start_id="test",
                root_tool_call_id="tool1",
                root_tool_insight_plan="test query",
                root_tool_insight_type="trends",
            ),
            {},
        )
        new_state = cast(PartialAssistantState, new_state)
        mock_process_query_dict.assert_called_once()  # Query processing started
        msg = new_state.messages[0]
        assert isinstance(msg, AssistantMessage)
        self.assertEqual(
            msg.content,
            "There was an error running this query: Error executing query: This query exceeds the capabilities of our picolator. Try de-brolling its flim-flam.",
        )
        self.assertEqual(msg.type, "ai")
        self.assertIsNotNone(msg.id)

    async def test_node_requires_a_viz_message_in_state(self):
        node = QueryExecutorNode(self.team, self.user)

        with self.assertRaisesMessage(
            ValueError, "Expected an ArtifactRefMessage, found <class 'posthog.schema.HumanMessage'>"
        ):
            await node.arun(
                AssistantState(
                    messages=[
                        HumanMessage(content="Text"),
                    ],
                    plan="Plan",
                    start_id="test",
                    root_tool_call_id="tool1",
                    root_tool_insight_plan="test query",
                    root_tool_insight_type="trends",
                ),
                {},
            )

    async def test_fallback_to_json(self):
        node = QueryExecutorNode(self.team, self.user)
        with patch("ee.hogai.context.insight.query_executor.process_query_dict") as mock_process_query_dict:
            mock_process_query_dict.return_value = QueryStatus(
                id="test", team_id=self.team.pk, query_async=True, complete=True, results=[{"test": "test"}]
            )

            artifact = await AgentArtifact.objects.acreate(
                name="test insight",
                type=AgentArtifact.Type.VISUALIZATION,
                data=VisualizationArtifactContent(
                    query=AssistantTrendsQuery(series=[]), name="test insight", description="test description"
                ).model_dump(),
                conversation=self.conversation,
                team=self.team,
            )
            artifact_message = ArtifactRefMessage(
                content_type=ArtifactContentType.VISUALIZATION,
                source=ArtifactSource.ARTIFACT,
                artifact_id=artifact.short_id,
                id="123",
            )
            new_state = await node.arun(
                AssistantState(
                    messages=[
                        HumanMessage(content="Text", id="test"),
                        artifact_message,
                    ],
                    plan="Plan",
                    start_id="test",
                    root_tool_call_id="tool1",
                    root_tool_insight_plan="test query",
                    root_tool_insight_type="trends",
                ),
                {},
            )
            new_state = cast(PartialAssistantState, new_state)
            mock_process_query_dict.assert_called_once()  # Query processing started
            msg = cast(AssistantMessage, new_state.messages[0])
            self.assertIn(
                "Here is the results table of the TrendsQuery created to answer your latest question:", msg.content
            )
            self.assertEqual(msg.type, "tool")
            self.assertIsNotNone(msg.id)

    def test_get_example_prompt(self):
        from ee.hogai.context.insight.query_executor import get_example_prompt

        # Test Trends Query
        trends_query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode()])
        self.assertEqual(get_example_prompt(trends_query), TRENDS_EXAMPLE_PROMPT)

        # Test Funnel Query - Steps (default)
        funnel_steps_query = AssistantFunnelsQuery(series=[])
        self.assertEqual(get_example_prompt(funnel_steps_query), FUNNEL_STEPS_EXAMPLE_PROMPT)

        # Test Funnel Query - Time to Convert
        funnel_time_query = AssistantFunnelsQuery(
            series=[],
            funnelsFilter=AssistantFunnelsFilter(funnelVizType=FunnelVizType.TIME_TO_CONVERT),
        )
        self.assertEqual(get_example_prompt(funnel_time_query), FUNNEL_TIME_TO_CONVERT_EXAMPLE_PROMPT)

        # Test Funnel Query - Trends
        funnel_trends_query = AssistantFunnelsQuery(
            series=[],
            funnelsFilter=AssistantFunnelsFilter(funnelVizType=FunnelVizType.TRENDS),
        )
        self.assertEqual(get_example_prompt(funnel_trends_query), FUNNEL_TRENDS_EXAMPLE_PROMPT)

        # Test Retention Query
        retention_query = AssistantRetentionQuery(
            retentionFilter=AssistantRetentionFilter(
                targetEntity=AssistantRetentionEventsNode(name="event"),
                returningEntity=AssistantRetentionEventsNode(name="event"),
            )
        )
        self.assertEqual(get_example_prompt(retention_query), RETENTION_EXAMPLE_PROMPT)
