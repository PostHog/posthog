from langgraph.graph import StateGraph
from pydantic import Field

from ee.hogai.utils.types import AssistantBaseState, AssistantNodeName
from posthog.test.base import BaseTest


class TestAssistantGraph(BaseTest):
    async def test_pydantic_state_resets_with_none(self):
        """When a None field is set, it should be reset to None."""

        class State(AssistantBaseState):
            resettable_field: str | None = Field(default=None)

        def runnable(state: State) -> State:
            return State(resettable_field=None)

        graph = StateGraph(State)
        compiled_graph = (
            graph.add_node(AssistantNodeName.ROOT, runnable)
            .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
            .add_edge(AssistantNodeName.ROOT, AssistantNodeName.END)
            .compile(checkpointer=None)
        )
        state = await compiled_graph.ainvoke(State(resettable_field="test"))
        self.assertEqual(state["resettable_field"], None)
