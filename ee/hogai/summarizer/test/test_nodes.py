from unittest.mock import patch

from django.test import override_settings
from langchain_core.runnables import RunnableLambda
from langchain_core.messages import HumanMessage as LangchainHumanMessage
from ee.hogai.summarizer.nodes import SummarizerNode
from posthog.schema import (
    AssistantMessage,
    AssistantTrendsEventsNode,
    AssistantTrendsQuery,
    HumanMessage,
    VisualizationMessage,
)
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from posthog.api.services.query import process_query_dict


@override_settings(IN_UNIT_TESTING=True)
class TestSummarizerNode(ClickhouseTestMixin, APIBaseTest):
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
                            reasoning_steps=["step"],
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

    def test_agent_reconstructs_conversation(self):
        pass

    # TODO: Test with erroneous query
