from unittest.mock import Mock, patch

from langchain_core.messages import AIMessage as LangchainAIMessage

from ee.hogai.graph.title_generator.nodes import TitleGeneratorNode
from ee.hogai.utils.tests import FakeChatOpenAI
from ee.hogai.utils.types import AssistantState
from ee.models.assistant import Conversation
from posthog.schema import HumanMessage
from posthog.test.base import BaseTest


class TestTitleGenerator(BaseTest):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(user=self.user, team=self.team)

    def test_saves_a_title(self):
        """Test that a title is generated and saved for a conversation without a title."""
        with patch(
            "ee.hogai.graph.title_generator.nodes.TitleGeneratorNode._model",
            return_value=FakeChatOpenAI(responses=[LangchainAIMessage(content="Test Title")]),
        ):
            node = TitleGeneratorNode(self.team, self.user)
            new_state = node.run(
                AssistantState(messages=[HumanMessage(content="Test Message")]),
                {"configurable": {"thread_id": self.conversation.id}},
            )
            self.assertIsNone(new_state)
            # Refresh from DB to ensure we get latest value
            self.conversation.refresh_from_db()
            self.assertEqual(self.conversation.title, "Test Title")

    def test_title_already_set_should_stay_the_same(self):
        """Test that existing conversation titles are not overwritten."""
        self.conversation.title = "Existing Title"
        self.conversation.save()

        with patch(
            "ee.hogai.graph.title_generator.nodes.TitleGeneratorNode._model",
            return_value=FakeChatOpenAI(responses=[LangchainAIMessage(content="New Title")]),
        ):
            node = TitleGeneratorNode(self.team, self.user)
            new_state = node.run(
                AssistantState(messages=[HumanMessage(content="Test Message")]),
                {"configurable": {"thread_id": self.conversation.id}},
            )
            self.assertIsNone(new_state)
            # Refresh from DB to ensure we get latest value
            self.conversation.refresh_from_db()
            self.assertEqual(self.conversation.title, "Existing Title")

    def test_two_messages_in_conversation_no_title_should_set_title(self):
        """Test that a title is generated when there are multiple messages in the conversation."""
        mock_model = FakeChatOpenAI(responses=[LangchainAIMessage(content="Conversation Title")])

        with patch.object(TitleGeneratorNode, "_model", new=Mock(return_value=mock_model)):
            node = TitleGeneratorNode(self.team, self.user)
            new_state = node.run(
                AssistantState(
                    messages=[
                        HumanMessage(content="First message"),
                        HumanMessage(content="Second message"),
                    ]
                ),
                {"configurable": {"thread_id": self.conversation.id}},
            )
            self.assertIsNone(new_state)
            # Refresh from DB to ensure we get latest value
            self.conversation.refresh_from_db()
            self.assertEqual(self.conversation.title, "Conversation Title")

    def test_no_messages_should_skip(self):
        """Test that title generation is skipped when there are no messages in the conversation."""
        node = TitleGeneratorNode(self.team, self.user)
        new_state = node.run(
            AssistantState(messages=[]),
            {"configurable": {"thread_id": self.conversation.id}},
        )
        self.assertIsNone(new_state)
        # Refresh from DB to ensure we get latest value
        self.conversation.refresh_from_db()
        self.assertIsNone(self.conversation.title)
