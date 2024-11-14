import pytest
from deepeval import assert_test
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCaseParams

from ee.hogai.utils import AssistantNodeName

from .utils import load_dataset


@pytest.mark.parametrize("dataset", load_dataset(AssistantNodeName.TRENDS_PLANNER))
def test_trends_planner(dataset):
    plan_correctness_metric = GEval(
        name="Correctness",
        criteria="You will be given expected and actual generated plans generated to provide a taxonomy to answer a user's question with a trends insight. Determine whether the taxonomy of actual plan matches the expected plan by only comparing the plans.",
        # NOTE: you can only provide either criteria or evaluation_steps, and not both
        evaluation_steps=[
            # This line avoids LLM's necesity to segment the data.
            "Do not apply general knowledge about trends insights.",
            "A plan must define at least one event and a math type, but it is not required to define any filters, breakdowns, or formulas.",
            "Compare events, properties, math types, and property values of 'expected output' and 'actual output', and ",
            "Check if the combination of events, properties, and property values in 'actual output' can answer the user's question according to the 'expected output'.",
            # Aggregation types should be more specific because there isn't a way to bypass.
            "Check if math types in 'actual output' match the math types in 'expected output'. If the aggregation type is specified by a property, user, or group in 'expected output', the same property, user, or group must be used in 'actual output'.",
            "If 'expected output' contains a breakdown, check if 'actual output' contains a similar breakdown, and heavily penalize if the breakdown is not present or different.",
            "If 'expected output' contains a formula, check if 'actual output' contains a similar formula, and heavily penalize if the formula is not present or different.",
            # We don't want to see in the output unnecessary property filters. The assistant tries to use them all the time.
            "Heavily penalize if the 'actual output' contains any excessive output that is not present in the 'expected output'. For example, the `is set` operator in filters should not be used unless the user explicitly asks for it.",
        ],
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.EXPECTED_OUTPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        threshold=0.7,
    )

    assert_test(dataset, [plan_correctness_metric])
