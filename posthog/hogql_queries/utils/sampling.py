from typing import Optional, Union

from posthog.hogql_queries.insights.trends.math_functions import ALL_SUPPORTED_MATH_FUNCTIONS


def correct_result_for_sampling(
    value: Union[int, float],
    sampling_factor: Optional[float],
    entity_math: Optional[str] = None,
) -> Union[int, float]:
    # We don't adjust results for sampling if:
    # - There's no sampling_factor specified i.e. the query isn't sampled
    # - The value is not a number (should not happen, but being defensive, especially against HogQL aggregation)
    # - The query performs a math operation other than 'sum' because statistical math operations
    # on sampled data yield results in the correct format
    if (
        not sampling_factor
        or not isinstance(value, int | float)
        or (entity_math is not None and entity_math != "sum" and entity_math in ALL_SUPPORTED_MATH_FUNCTIONS)
    ):
        return value

    result = round(value * (1 / sampling_factor))
    return result
