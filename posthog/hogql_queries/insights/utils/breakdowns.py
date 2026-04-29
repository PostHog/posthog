from posthog.schema import BreakdownFilter

BREAKDOWN_OTHER_STRING_LABEL = "$$_posthog_breakdown_other_$$"
BREAKDOWN_NULL_STRING_LABEL = "$$_posthog_breakdown_null_$$"
BREAKDOWN_OTHER_DISPLAY = "Other (i.e. all remaining values)"
BREAKDOWN_NULL_DISPLAY = "None (i.e. no value)"
BREAKDOWN_NUMERIC_ALL_VALUES_PLACEHOLDER = '["",""]'

ALL_USERS_COHORT_ID = 0
# Keep in sync with NOT_IN_COHORT_ID in frontend/src/scenes/insights/utils.tsx
NOT_IN_COHORT_ID = 2**52


def has_single_breakdown(breakdown_filter: BreakdownFilter | None) -> bool:
    """Return whether the single-field `breakdown` representation is populated."""
    return breakdown_filter is not None and breakdown_filter.breakdown is not None


def has_multi_breakdown(breakdown_filter: BreakdownFilter | None) -> bool:
    """Return whether the multi-field `breakdowns` representation is populated."""
    return (
        breakdown_filter is not None
        and breakdown_filter.breakdowns is not None
        and len(breakdown_filter.breakdowns) > 0
    )


def has_breakdown_filter(breakdown_filter: BreakdownFilter | None) -> bool:
    """Return whether a breakdown is configured via either supported representation."""
    return has_single_breakdown(breakdown_filter) or has_multi_breakdown(breakdown_filter)
