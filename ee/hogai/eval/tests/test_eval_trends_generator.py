from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from ee.hogai.assistant import AssistantGraph
from ee.hogai.eval.utils import EvalBaseTest
from ee.hogai.utils import AssistantNodeName
from posthog.schema import HumanMessage


class TestEvalTrendsGenerator(EvalBaseTest):
    def _call_node(self, query: str, plan: str) -> BaseModel:
        graph: CompiledStateGraph = (
            AssistantGraph(self.team)
            .add_edge(AssistantNodeName.START, AssistantNodeName.TRENDS_GENERATOR)
            .add_trends_generator(AssistantNodeName.END)
            .compile()
        )
        state = graph.invoke({"messages": [HumanMessage(content=query)], "plan": plan})
        return state["messages"][-1].answer

    def test_node_replaces_equals_with_contains(self):
        query = "what is pageview trend for users with name John?"
        plan = """Events:
        - $pageview
            - math operation: total count
            - property filter 1
                - person
                - name
                - equals
                - John
        """
        actual_output = self._call_node(query, plan).model_dump_json(exclude_none=True)
        assert "exact" not in actual_output
        assert "icontains" in actual_output
        assert "John" not in actual_output
        assert "john" in actual_output
