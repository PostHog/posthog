import pytest

from posthog.schema import Breakdown, BreakdownFilter, BreakdownType

from posthog.hogql_queries.insights.utils.breakdowns import (
    has_breakdown_filter,
    has_multi_breakdown,
    has_single_breakdown,
    humanize_breakdown_label,
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


@pytest.mark.parametrize(
    "label, expected",
    [
        ("$$_posthog_breakdown_other_$$", "Other (i.e. all remaining values)"),
        ("$$_posthog_breakdown_null_$$", "None (i.e. no value)"),
        # both sentinels in one label are each replaced
        (
            "$$_posthog_breakdown_other_$$ and $$_posthog_breakdown_null_$$",
            "Other (i.e. all remaining values) and None (i.e. no value)",
        ),
        # compound label shapes survive: action-prefixed and "::"-joined multi-breakdown
        ("signed_up - $$_posthog_breakdown_other_$$", "signed_up - Other (i.e. all remaining values)"),
        ("$$_posthog_breakdown_other_$$::US", "Other (i.e. all remaining values)::US"),
        ("Chrome", "Chrome"),
        # a normal label containing " - " must pass through untouched (no fragile splitting)
        ("Signed up - paid", "Signed up - paid"),
    ],
)
def test_humanize_breakdown_label(label: str, expected: str) -> None:
    assert humanize_breakdown_label(label) == expected
