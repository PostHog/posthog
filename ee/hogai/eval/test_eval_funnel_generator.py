from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from ee.hogai.assistant import AssistantGraph
from ee.hogai.eval.utils import EvalBaseTest
from ee.hogai.utils import AssistantNodeName
from posthog.schema import HumanMessage


class TestEvalFunnelGenerator(EvalBaseTest):
    def _call_node(self, query: str, plan: str) -> BaseModel:
        graph: CompiledStateGraph = (
            AssistantGraph(self.team)
            .add_edge(AssistantNodeName.START, AssistantNodeName.FUNNEL_GENERATOR)
            .add_funnel_generator(AssistantNodeName.END)
            .compile()
        )
        state = graph.invoke({"messages": [HumanMessage(content=query)], "plan": plan})
        return state["messages"][-1].answer

    def test_node_replaces_equals_with_contains(self):
        query = "what is the conversion rate from a page view to sign up for users with name john?"
        plan = """Sequence:
        1. $pageview
        - property filter 1
            - person
            - name
            - equals
            - john
        2. signed_up
        """
        actual_output = self._call_node(query, plan).model_dump_json(exclude_none=True)
        assert "equals" not in actual_output
        assert "contains" in actual_output
