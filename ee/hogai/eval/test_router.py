import pytest
from deepeval import assert_test
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams
from langgraph.graph.state import CompiledStateGraph

from ee.hogai.assistant import AssistantGraph
from ee.hogai.utils import AssistantNodeName
from posthog.schema import HumanMessage
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

router_correctness_metric = GEval(
    name="Classification Correctness (message)",
    criteria="Determine if the detected visualization type in 'actual output' matches the expected visualization type in 'expected output'. Output is a single string of visualization type.",
    evaluation_steps=[
        "Do not apply general knowledge about analytics insights.",
        "Compare 'actual output' and 'expected output'. Heavily penalize if they don't match.",
    ],
    evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.EXPECTED_OUTPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
    threshold=0.7,
)


@pytest.mark.django_db(transaction=True)
# @pytest.mark.parametrize("dataset", load_dataset(AssistantNodeName.ROUTER, load_filter="all"))
class TestRouterEval(ClickhouseTestMixin, APIBaseTest):
    def _call_node(self, query):
        graph: CompiledStateGraph = (
            AssistantGraph(self.team)
            .add_start()
            .add_router(path_map={"trends": AssistantNodeName.END, "funnel": AssistantNodeName.END})
            .compile()
        )
        state = graph.invoke({"messages": [HumanMessage(content=query)]})
        return state["messages"][-1].content

    def test_router_switches_insight_type(self):
        query = "how many users upgraded their plan to personal pro?"
        test_case = LLMTestCase(
            input=query,
            expected_output="trends",
            actual_output=self._call_node(query),
        )
        assert_test(test_case, [router_correctness_metric])
