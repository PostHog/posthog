import pytest
from deepeval import assert_test
from deepeval.dataset import EvaluationDataset
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams

dataset = EvaluationDataset()

dataset.add_test_cases_from_json_file(
    file_path="ee/hogai/eval/eval.json",
    input_key_name="query",
    actual_output_key_name="actual_output",
    expected_output_key_name="expected_output",
)


#
@pytest.mark.parametrize(
    "test_case",
    dataset,
)
def test_customer_chatbot(test_case: LLMTestCase):
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
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        threshold=0.7,
    )

    assert_test(test_case, [plan_correctness_metric])
