import pytest
from deepeval import assert_test
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCaseParams
from langgraph.graph.state import CompiledStateGraph

from ee.hogai.assistant import AssistantGraph
from ee.hogai.utils import AssistantNodeName
from posthog.schema import HumanMessage
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from .utils import load_dataset

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
@pytest.mark.parametrize("dataset", load_dataset(AssistantNodeName.ROUTER, load_filter="all"))
class TestRouterEval(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()

    def test_router_switches_insight_type(self, dataset):
        graph: CompiledStateGraph = AssistantGraph(self.team).compile_full_graph()
        res = graph.invoke({"messages": [HumanMessage(content=dataset.input)]})
        dataset.actual_output = res["messages"][-1].content
        assert_test(dataset, [router_correctness_metric])
