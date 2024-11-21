from langgraph.graph.state import CompiledStateGraph

from ee.hogai.assistant import AssistantGraph
from ee.hogai.eval.utils import EvalBaseTest
from ee.hogai.utils import AssistantNodeName
from posthog.schema import HumanMessage


class TestEvalFunnelGenerator(EvalBaseTest):
    def _call_node(self, query: str, plan: str):
        graph: CompiledStateGraph = (
            AssistantGraph(self.team)
            .add_edge(AssistantNodeName.START, AssistantNodeName.FUNNEL_GENERATOR)
            .add_funnel_generator(AssistantNodeName.END)
            .compile()
        )
        state = graph.invoke({"messages": [HumanMessage(content=query)]})
        return state["plan"]
