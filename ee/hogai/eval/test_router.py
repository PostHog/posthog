import pytest
from deepeval import assert_test
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCaseParams

from ee.hogai.utils import AssistantNodeName

from .utils import load_dataset


@pytest.mark.parametrize("dataset", load_dataset(AssistantNodeName.ROUTER, load_filter="all"))
def test_router_correctness(dataset):
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

    assert_test(dataset, [router_correctness_metric])
