from ee.hogai.utils.helpers import filter_messages
from posthog.schema import (
    AssistantMessage,
    AssistantTrendsQuery,
    FailureMessage,
    HumanMessage,
    RouterMessage,
    VisualizationMessage,
)
from posthog.test.base import BaseTest


class TestTrendsUtils(BaseTest):
    def test_filters_and_merges_human_messages(self):
        conversation = [
            HumanMessage(content="Text"),
            FailureMessage(content="Error"),
            HumanMessage(content="Text"),
            VisualizationMessage(answer=AssistantTrendsQuery(series=[]), plan="plan"),
            HumanMessage(content="Text2"),
            VisualizationMessage(answer=None, plan="plan"),
        ]
        messages = filter_messages(conversation)
        self.assertEqual(len(messages), 4)
        self.assertEqual(
            [
                HumanMessage(content="Text\nText"),
                VisualizationMessage(answer=AssistantTrendsQuery(series=[]), plan="plan"),
                HumanMessage(content="Text2"),
                VisualizationMessage(answer=None, plan="plan"),
            ],
            messages,
        )

    def test_filters_typical_conversation(self):
        messages = filter_messages(
            [
                HumanMessage(content="Question 1"),
                RouterMessage(content="trends"),
                VisualizationMessage(answer=AssistantTrendsQuery(series=[]), plan="Plan 1"),
                AssistantMessage(content="Summary 1"),
                HumanMessage(content="Question 2"),
                RouterMessage(content="funnel"),
                VisualizationMessage(answer=AssistantTrendsQuery(series=[]), plan="Plan 2"),
                AssistantMessage(content="Summary 2"),
            ]
        )
        self.assertEqual(len(messages), 6)
        self.assertEqual(
            messages,
            [
                HumanMessage(content="Question 1"),
                VisualizationMessage(answer=AssistantTrendsQuery(series=[]), plan="Plan 1"),
                AssistantMessage(content="Summary 1"),
                HumanMessage(content="Question 2"),
                VisualizationMessage(answer=AssistantTrendsQuery(series=[]), plan="Plan 2"),
                AssistantMessage(content="Summary 2"),
            ],
        )

    def test_joins_human_messages(self):
        messages = filter_messages(
            [
                HumanMessage(content="Question 1"),
                HumanMessage(content="Question 2"),
            ]
        )
        self.assertEqual(len(messages), 1)
        self.assertEqual(
            messages,
            [
                HumanMessage(content="Question 1\nQuestion 2"),
            ],
        )
