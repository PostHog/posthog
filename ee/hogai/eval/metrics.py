from datetime import datetime

from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCaseParams


def time_and_interval_correctness(insight_type: str):
    return GEval(
        name="Time Period and Time Interval Correctness",
        criteria=f"You will be given expected and actual generated plans to provide a taxonomy to answer a user's question with a {insight_type} insight. Compare the plans to determine whether the taxonomy of the actual plan matches the expected plan. Do not apply general knowledge about {insight_type} insights. Today is {datetime.now().strftime('%Y-%m-%d')}",
        evaluation_steps=[
            "If the expected plan includes a time period or time interval, the actual plan must include the similar time period or time interval. Example: if today is 2025-03-14, then the time period `yesterday` can be written as `2025-03-13`, `yesterday`, `2025-03-13 - 2025-03-13`, `previous day`.",
            "Plans must not include property filters either for time or time intervals. For example, a property filter such as `timestamp` is not allowed.",
        ],
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.EXPECTED_OUTPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
        ],
        threshold=0.7,
    )
