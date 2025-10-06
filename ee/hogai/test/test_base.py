from posthog.test.base import BaseTest

from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, HumanMessage

from ee.hogai.graph.base import AssistantNode
from ee.hogai.utils.types.base import AssistantNodeName, AssistantState, PartialAssistantState
from ee.hogai.utils.types.composed import MaxNodeName


class DummyNode(AssistantNode):
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        return None

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.ROOT


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
