from posthog.test.base import BaseTest

from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.memory import InMemorySaver

from ee.hogai.graph.base.graph import BaseAssistantGraph
from ee.hogai.utils.types import AssistantNodeName, AssistantState, PartialAssistantState


class TestAssistantGraph(BaseTest):
    async def test_pydantic_state_resets_with_none(self):
        """When a None field is set, it should be reset to None."""

        async def runnable(state: AssistantState) -> PartialAssistantState:
            return PartialAssistantState(start_id=None)

        graph = BaseAssistantGraph(self.team, self.user, state_type=AssistantState)
        compiled_graph = (
            graph.add_node(AssistantNodeName.ROOT, RunnableLambda(runnable))
            .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
            .add_edge(AssistantNodeName.ROOT, AssistantNodeName.END)
            .compile(checkpointer=InMemorySaver())
        )
        state = await compiled_graph.ainvoke(
            AssistantState(messages=[], graph_status="resumed", start_id=None),
            {"configurable": {"thread_id": "test"}},
        )
        self.assertEqual(state["start_id"], None)
        self.assertEqual(state["graph_status"], "resumed")
