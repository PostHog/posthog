from unittest.mock import patch

from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
    HumanMessage as LangchainHumanMessage,
)
from langchain_core.runnables import RunnableLambda
from rest_framework.exceptions import ValidationError

from ee.hogai.summarizer.nodes import SummarizerNode
from ee.hogai.summarizer.prompts import SUMMARIZER_INSTRUCTION_PROMPT, SUMMARIZER_SYSTEM_PROMPT
from ee.hogai.utils.types import AssistantState
from posthog.api.services.query import process_query_dict
from posthog.schema import (
    AssistantTrendsEventsNode,
    AssistantTrendsQuery,
    HumanMessage,
    QueryStatus,
    VisualizationMessage,
)
from posthog.test.base import BaseTest, ClickhouseTestMixin


class TestSummarizerNode(ClickhouseTestMixin, BaseTest):
    maxDiff = None

    @patch("ee.hogai.summarizer.nodes.process_query_dict", side_effect=process_query_dict)
    def test_node_runs(self, mock_process_query_dict):
        node = SummarizerNode(self.team)
        with patch.object(SummarizerNode, "_model") as generator_model_mock:
            generator_model_mock.return_value = RunnableLambda(
                lambda _: LangchainHumanMessage(content="The results indicate foobar.")
            )
            new_state = node.run(
                AssistantState(
                    messages=[
                        HumanMessage(content="Text", id="test"),
                        VisualizationMessage(
                            answer=AssistantTrendsQuery(series=[AssistantTrendsEventsNode()]),
                            plan="Plan",
                            id="test2",
                            initiator="test",
                        ),
                    ],
                    plan="Plan",
                    start_id="test",
                ),
                {},
            )
            mock_process_query_dict.assert_called_once()  # Query processing started
            msg = new_state.messages[0]
            self.assertEqual(msg.content, "The results indicate foobar.")
            self.assertEqual(msg.type, "ai")
            self.assertIsNotNone(msg.id)

    @patch(
        "ee.hogai.summarizer.nodes.process_query_dict",
        side_effect=ValueError("You have not glibbled the glorp before running this."),
    )
    def test_node_handles_internal_error(self, mock_process_query_dict):
        node = SummarizerNode(self.team)
        with patch.object(SummarizerNode, "_model") as generator_model_mock:
            generator_model_mock.return_value = RunnableLambda(
                lambda _: LangchainHumanMessage(content="The results indicate foobar.")
            )
            new_state = node.run(
                AssistantState(
                    messages=[
                        HumanMessage(content="Text", id="test"),
                        VisualizationMessage(
                            answer=AssistantTrendsQuery(series=[AssistantTrendsEventsNode()]),
                            plan="Plan",
                            id="test2",
                            initiator="test",
                        ),
                    ],
                    plan="Plan",
                    start_id="test",
                ),
                {},
            )
            mock_process_query_dict.assert_called_once()  # Query processing started
            msg = new_state.messages[0]
            self.assertEqual(msg.content, "There was an unknown error running this query.")
            self.assertEqual(msg.type, "ai/failure")
            self.assertIsNotNone(msg.id)

    @patch(
        "ee.hogai.summarizer.nodes.process_query_dict",
        side_effect=ValidationError(
            "This query exceeds the capabilities of our picolator. Try de-brolling its flim-flam."
        ),
    )
    def test_node_handles_exposed_error(self, mock_process_query_dict):
        node = SummarizerNode(self.team)
        with patch.object(SummarizerNode, "_model") as generator_model_mock:
            generator_model_mock.return_value = RunnableLambda(
                lambda _: LangchainHumanMessage(content="The results indicate foobar.")
            )
            new_state = node.run(
                AssistantState(
                    messages=[
                        HumanMessage(content="Text", id="test"),
                        VisualizationMessage(
                            answer=AssistantTrendsQuery(series=[AssistantTrendsEventsNode()]),
                            plan="Plan",
                            id="test2",
                            initiator="test",
                        ),
                    ],
                    plan="Plan",
                    start_id="test",
                ),
                {},
            )
            mock_process_query_dict.assert_called_once()  # Query processing started
            msg = new_state.messages[0]
            self.assertEqual(
                msg.content,
                "There was an error running this query: This query exceeds the capabilities of our picolator. Try de-brolling its flim-flam.",
            )
            self.assertEqual(msg.type, "ai/failure")
            self.assertIsNotNone(msg.id)

    def test_node_requires_a_viz_message_in_state(self):
        node = SummarizerNode(self.team)

        with self.assertRaisesMessage(
            ValueError, "Can only run summarization with a visualization message as the last one in the state"
        ):
            node.run(
                AssistantState(
                    messages=[
                        HumanMessage(content="Text"),
                    ],
                    plan="Plan",
                    start_id="test",
                ),
                {},
            )

    def test_node_requires_viz_message_in_state_to_have_query(self):
        node = SummarizerNode(self.team)

        with self.assertRaisesMessage(ValueError, "Did not found query in the visualization message"):
            node.run(
                AssistantState(
                    messages=[
                        VisualizationMessage(answer=None, plan="Plan", id="test"),
                    ],
                    plan="Plan",
                    start_id="test",
                ),
                {},
            )

    def test_agent_reconstructs_conversation(self):
        node = SummarizerNode(self.team)

        history = node._construct_messages(
            AssistantState(
                messages=[
                    HumanMessage(content="What's the trends in signups?", id="test"),
                    VisualizationMessage(
                        answer=AssistantTrendsQuery(series=[AssistantTrendsEventsNode()]),
                        plan="Plan",
                        id="test2",
                        initiator="test",
                    ),
                ],
                start_id="test",
            )
        )
        self.assertEqual(
            history,
            [
                ("system", SUMMARIZER_SYSTEM_PROMPT),
                ("human", "What's the trends in signups?"),
                ("human", SUMMARIZER_INSTRUCTION_PROMPT),
            ],
        )

    def test_fallback_to_json(self):
        node = SummarizerNode(self.team)
        with (
            patch.object(SummarizerNode, "_model") as generator_model_mock,
            patch("ee.hogai.summarizer.nodes.process_query_dict") as mock_process_query_dict,
        ):

            def assert_input(input):
                self.assertIn("JSON", input.messages[0].content)
                self.assertIn('"test"', input.messages[2].content)
                return LangchainAIMessage(content="The results indicate foobar.")

            generator_model_mock.return_value = RunnableLambda(assert_input)

            mock_process_query_dict.return_value = QueryStatus(
                id="test", team_id=self.team.pk, query_async=True, complete=True, results=[{"test": "test"}]
            )

            new_state = node.run(
                AssistantState(
                    messages=[
                        HumanMessage(content="Text", id="test"),
                        VisualizationMessage(
                            answer=AssistantTrendsQuery(series=[AssistantTrendsEventsNode()]),
                            plan="Plan",
                            id="test2",
                            initiator="test",
                        ),
                    ],
                    plan="Plan",
                    start_id="test",
                ),
                {},
            )
            mock_process_query_dict.assert_called_once()  # Query processing started
            msg = new_state.messages[0]
            self.assertEqual(msg.content, "The results indicate foobar.")
            self.assertEqual(msg.type, "ai")
            self.assertIsNotNone(msg.id)
