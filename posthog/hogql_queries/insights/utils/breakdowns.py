from posthog.schema import BreakdownFilter


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
