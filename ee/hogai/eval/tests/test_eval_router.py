from typing import cast

from langgraph.graph.state import CompiledStateGraph

from ee.hogai.assistant import AssistantGraph
from ee.hogai.eval.utils import EvalBaseTest
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from posthog.schema import HumanMessage, RouterMessage


class TestEvalRouter(EvalBaseTest):
    def _call_node(self, query: str | list):
        graph: CompiledStateGraph = (
            AssistantGraph(self.team)
            .add_start()
            .add_router(path_map={"trends": AssistantNodeName.END, "funnel": AssistantNodeName.END})
            .compile()
        )
        messages = [HumanMessage(content=query)] if isinstance(query, str) else query
        state = graph.invoke(
            AssistantState(messages=messages),
            self._get_config(),
        )
        return cast(RouterMessage, AssistantState.model_validate(state).messages[-1]).content

    def test_outputs_basic_trends_insight(self):
        query = "Show the $pageview trend"
        res = self._call_node(query)
        self.assertEqual(res, "trends")

    def test_outputs_basic_funnel_insight(self):
        query = "What is the conversion rate of users who uploaded a file to users who paid for a plan?"
        res = self._call_node(query)
        self.assertEqual(res, "funnel")

    def test_converts_trends_to_funnel(self):
        conversation = [
            HumanMessage(content="Show trends of $pageview and $identify"),
            RouterMessage(content="trends"),
            HumanMessage(content="Convert this insight to a funnel"),
        ]
        res = self._call_node(conversation[:1])
        self.assertEqual(res, "trends")
        res = self._call_node(conversation)
        self.assertEqual(res, "funnel")

    def test_converts_funnel_to_trends(self):
        conversation = [
            HumanMessage(content="What is the conversion from a page view to a sign up?"),
            RouterMessage(content="funnel"),
            HumanMessage(content="Convert this insight to a trends"),
        ]
        res = self._call_node(conversation[:1])
        self.assertEqual(res, "funnel")
        res = self._call_node(conversation)
        self.assertEqual(res, "trends")

    def test_outputs_single_trends_insight(self):
        """
        Must display a trends insight because it's not possible to build a funnel with a single series.
        """
        query = "how many users upgraded their plan to personal pro?"
        res = self._call_node(query)
        self.assertEqual(res, "trends")

    def test_classifies_funnel_with_single_series(self):
        query = "What's our sign-up funnel?"
        res = self._call_node(query)
        self.assertEqual(res, "funnel")
