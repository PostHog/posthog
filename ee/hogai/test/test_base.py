from posthog.test.base import BaseTest

from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, HumanMessage

from ee.hogai.graph.base import AssistantNode
from ee.hogai.utils.types.base import AssistantState, PartialAssistantState


class DummyNode(AssistantNode):
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        return None


class TestAssistantBase(BaseTest):
    def test_is_first_turn_true(self):
        """Test _is_first_turn returns True when last message is the start message"""
        node = DummyNode(self.team, self.user)

        # Create state where the last message is the first human message
        state = AssistantState(
            messages=[
                HumanMessage(content="First message", id="1"),
            ]
        )

        result = node._is_first_turn(state)
        self.assertTrue(result)

    def test_is_first_turn_false_with_conversation(self):
        """Test _is_first_turn returns False when there's been conversation"""
        node = DummyNode(self.team, self.user)

        # Create state with conversation history
        state = AssistantState(
            messages=[
                HumanMessage(content="First message", id="1"),
                AssistantMessage(content="Response", id="2"),
                HumanMessage(content="Second message", id="3"),
            ]
        )

        result = node._is_first_turn(state)
        self.assertFalse(result)

    def test_is_first_turn_false_with_assistant_message_last(self):
        """Test _is_first_turn returns False when last message is not human"""
        node = DummyNode(self.team, self.user)

        # Create state where last message is assistant message
        state = AssistantState(
            messages=[
                HumanMessage(content="First message", id="1"),
                AssistantMessage(content="Response", id="2"),
            ]
        )

        result = node._is_first_turn(state)
        self.assertFalse(result)

    def test_is_first_turn_with_start_id(self):
        """Test _is_first_turn respects start_id parameter"""
        node = DummyNode(self.team, self.user)

        # With start_id set, the conversation start is message id="3", not id="1"
        state = AssistantState(
            messages=[
                HumanMessage(content="Old message", id="1"),
                AssistantMessage(content="Old response", id="2"),
                HumanMessage(content="New start", id="3"),
            ],
            start_id="3",
        )

        result = node._is_first_turn(state)
        self.assertTrue(result)

        # Add more messages after the start - should be False
        state_with_conversation = AssistantState(
            messages=[
                HumanMessage(content="Old message", id="1"),
                AssistantMessage(content="Old response", id="2"),
                HumanMessage(content="New start", id="3"),
                AssistantMessage(content="New response", id="4"),
                HumanMessage(content="Follow-up", id="5"),
            ],
            start_id="3",
        )

        result = node._is_first_turn(state_with_conversation)
        self.assertFalse(result)
