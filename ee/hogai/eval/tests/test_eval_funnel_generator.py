from typing import cast

from langgraph.graph.state import CompiledStateGraph

from ee.hogai.assistant import AssistantGraph
from ee.hogai.eval.utils import EvalBaseTest
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from posthog.schema import AssistantFunnelsQuery, HumanMessage, VisualizationMessage


class TestEvalFunnelGenerator(EvalBaseTest):
    def _call_node(self, query: str, plan: str) -> AssistantFunnelsQuery:
        graph: CompiledStateGraph = (
            AssistantGraph(self.team)
            .add_edge(AssistantNodeName.START, AssistantNodeName.FUNNEL_GENERATOR)
            .add_funnel_generator(AssistantNodeName.END)
            .compile()
        )
        state = graph.invoke(
            AssistantState(messages=[HumanMessage(content=query)], plan=plan),
            self._get_config(),
        )
        return cast(VisualizationMessage, AssistantState.model_validate(state).messages[-1]).answer

    def test_node_replaces_equals_with_contains(self):
        query = "what is the conversion rate from a page view to sign up for users with name John?"
        plan = """Sequence:
        1. $pageview
        - property filter 1
            - person
            - name
            - equals
            - John
        2. signed_up
        """
        actual_output = self._call_node(query, plan).model_dump_json(exclude_none=True)
        assert "exact" not in actual_output
        assert "icontains" in actual_output
        assert "John" not in actual_output
        assert "john" in actual_output
