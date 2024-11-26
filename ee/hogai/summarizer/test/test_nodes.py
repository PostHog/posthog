from unittest.mock import patch

from django.test import override_settings
from langchain_core.runnables import RunnableLambda
from langchain_core.messages import (
    HumanMessage as LangchainHumanMessage,
)
from ee.hogai.summarizer.nodes import SummarizerNode
from ee.hogai.summarizer.prompts import SUMMARIZER_INSTRUCTION_PROMPT, SUMMARIZER_SYSTEM_PROMPT
from posthog.schema import (
    AssistantMessage,
    AssistantTrendsEventsNode,
    AssistantTrendsQuery,
    FailureMessage,
    HumanMessage,
    VisualizationMessage,
)
from rest_framework.exceptions import ValidationError
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from posthog.api.services.query import process_query_dict


@override_settings(IN_UNIT_TESTING=True)
class TestSummarizerNode(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    @patch("ee.hogai.summarizer.nodes.process_query_dict", side_effect=process_query_dict)
    def test_node_runs(self, mock_process_query_dict):
        node = SummarizerNode(self.team)
        with patch.object(SummarizerNode, "_model") as generator_model_mock:
            generator_model_mock.return_value = RunnableLambda(
                lambda _: LangchainHumanMessage(content="The results indicate foobar.")
            )
            new_state = node.run(
                {
                    "messages": [
                        HumanMessage(content="Text"),
                        VisualizationMessage(
                            answer=AssistantTrendsQuery(series=[AssistantTrendsEventsNode()]),
                            plan="Plan",
                            done=True,
                        ),
                    ],
                    "plan": "Plan",
                },
                {},
            )
            mock_process_query_dict.assert_called_once()  # Query processing started
            self.assertEqual(
                new_state,
                {
                    "messages": [
                        AssistantMessage(content="The results indicate foobar.", done=True),
                    ],
                },
            )

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
                {
                    "messages": [
                        HumanMessage(content="Text"),
                        VisualizationMessage(
                            answer=AssistantTrendsQuery(series=[AssistantTrendsEventsNode()]),
                            plan="Plan",
                            done=True,
                        ),
                    ],
                    "plan": "Plan",
                },
                {},
            )
            mock_process_query_dict.assert_called_once()  # Query processing started
            self.assertEqual(
                new_state,
                {
                    "messages": [
                        FailureMessage(content="There was an unknown error running this query."),
                    ],
                },
            )

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
                {
                    "messages": [
                        HumanMessage(content="Text"),
                        VisualizationMessage(
                            answer=AssistantTrendsQuery(series=[AssistantTrendsEventsNode()]),
                            plan="Plan",
                            done=True,
                        ),
                    ],
                    "plan": "Plan",
                },
                {},
            )
            mock_process_query_dict.assert_called_once()  # Query processing started
            self.assertEqual(
                new_state,
                {
                    "messages": [
                        FailureMessage(
                            content=(
                                "There was an error running this query: This query exceeds the capabilities of our picolator. "
                                "Try de-brolling its flim-flam."
                            )
                        ),
                    ],
                },
            )

    def test_node_requires_a_viz_message_in_state(self):
        node = SummarizerNode(self.team)

        with self.assertRaisesMessage(
            ValueError, "Can only run summarization with a visualization message as the last one in the state"
        ):
            node.run(
                {
                    "messages": [
                        HumanMessage(content="Text"),
                    ],
                    "plan": "Plan",
                },
                {},
            )

    def test_node_requires_viz_message_in_state_to_have_query(self):
        node = SummarizerNode(self.team)

        with self.assertRaisesMessage(ValueError, "Did not found query in the visualization message"):
            node.run(
                {
                    "messages": [
                        VisualizationMessage(
                            answer=None,
                            plan="Plan",
                            done=True,
                        ),
                    ],
                    "plan": "Plan",
                },
                {},
            )

    def test_agent_reconstructs_conversation(self):
        self.project.product_description = "Dating app for lonely hedgehogs."
        self.project.save()
        node = SummarizerNode(self.team)

        history = node._construct_messages(
            {
                "messages": [
                    HumanMessage(content="What's the trends in signups?"),
                    VisualizationMessage(
                        answer=AssistantTrendsQuery(series=[AssistantTrendsEventsNode()]),
                        plan="Plan",
                        done=True,
                    ),
                ]
            }
        )
        self.assertEqual(
            history,
            [
                ("system", SUMMARIZER_SYSTEM_PROMPT),
                ("human", "What's the trends in signups?"),
                ("human", SUMMARIZER_INSTRUCTION_PROMPT),
            ],
        )
