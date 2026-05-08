import pytest

from posthog.schema import Breakdown, BreakdownFilter, BreakdownType

from posthog.hogql_queries.insights.utils.breakdowns import (
    has_breakdown_filter,
    has_multi_breakdown,
    has_single_breakdown,
)


@pytest.mark.parametrize(
    "breakdown_filter, expected_has_breakdown, expected_has_single, expected_has_multi",
    [
        (None, False, False, False),
        (BreakdownFilter(), False, False, False),
        (BreakdownFilter(breakdown="$browser"), True, True, False),
        (BreakdownFilter(breakdown=[1, 2], breakdown_type=BreakdownType.COHORT), True, True, False),
        (
            BreakdownFilter(
                breakdowns=[Breakdown(property="$browser", type=BreakdownType.EVENT)],
            ),
            True,
            False,
            True,
        ),
        (
            BreakdownFilter(
                breakdown="$browser",
                breakdowns=[Breakdown(property="$os", type=BreakdownType.EVENT)],
            ),
            True,
            True,
            True,
        ),
    ],
)
def test_breakdown_presence_helpers(
    breakdown_filter: BreakdownFilter | None,
    expected_has_breakdown: bool,
    expected_has_single: bool,
    expected_has_multi: bool,
) -> None:
    assert has_breakdown_filter(breakdown_filter) is expected_has_breakdown
    assert has_single_breakdown(breakdown_filter) is expected_has_single
    assert has_multi_breakdown(breakdown_filter) is expected_has_multi
