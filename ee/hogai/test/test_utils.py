from langchain_core.messages import HumanMessage as LangchainHumanMessage

from ee.hogai.utils import filter_visualization_conversation, merge_human_messages
from posthog.schema import AssistantTrendsQuery, FailureMessage, HumanMessage, VisualizationMessage
from posthog.test.base import BaseTest


class TestTrendsUtils(BaseTest):
    def test_merge_human_messages(self):
        res = merge_human_messages(
            [
                LangchainHumanMessage(content="Text"),
                LangchainHumanMessage(content="Text"),
                LangchainHumanMessage(content="Te"),
                LangchainHumanMessage(content="xt"),
            ]
        )
        self.assertEqual(len(res), 1)
        self.assertEqual(res, [LangchainHumanMessage(content="Text\nTe\nxt")])

    def test_filter_trends_conversation(self):
        human_messages, visualization_messages = filter_visualization_conversation(
            [
                HumanMessage(content="Text"),
                FailureMessage(content="Error"),
                HumanMessage(content="Text"),
                VisualizationMessage(answer=AssistantTrendsQuery(series=[]), plan="plan"),
                HumanMessage(content="Text2"),
                VisualizationMessage(answer=None, plan="plan"),
            ]
        )
        self.assertEqual(len(human_messages), 2)
        self.assertEqual(len(visualization_messages), 1)
        self.assertEqual(
            human_messages, [LangchainHumanMessage(content="Text"), LangchainHumanMessage(content="Text2")]
        )
        self.assertEqual(
            visualization_messages, [VisualizationMessage(answer=AssistantTrendsQuery(series=[]), plan="plan")]
        )
