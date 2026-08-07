import pytest

from pydantic import ValidationError

from posthog.schema import (
    EventsNode,
    ResultCustomizationByPosition,
    ResultCustomizationByValue,
    TrendsFilter,
    TrendsQuery,
)


@pytest.mark.parametrize("token", ["preset-1", "preset-15", "preset-16", "preset-100"])
def test_result_customization_accepts_any_preset_token(token: str) -> None:
    # Custom color themes can define more than 15 colors, so the token is a
    # `preset-<n>` pattern rather than a closed enum — anything past preset-15
    # used to be rejected and made the insight unsaveable.
    assert ResultCustomizationByValue(color=token).color == token
    assert ResultCustomizationByPosition(color=token).color == token


@pytest.mark.parametrize("token", ["", "nonsense", "preset-", "preset-abc", "preset-1x"])
def test_result_customization_rejects_non_preset_token(token: str) -> None:
    with pytest.raises(ValidationError):
        ResultCustomizationByValue(color=token)


def test_trends_query_accepts_recoloring_beyond_preset_15() -> None:
    # Mirrors the save payload from the bug: recoloring a series with the 16th theme
    # color writes `preset-16` into trendsFilter.resultCustomizations. The by-value
    # entry must resolve to the by-value variant, not fall through to by-position and
    # surface a confusing `assignmentBy` error.
    query = TrendsQuery(
        series=[EventsNode(event="$pageview")],
        trendsFilter=TrendsFilter(
            resultCustomizations={'{"series":0}': {"assignmentBy": "value", "color": "preset-16"}}
        ),
    )
    assert query.trendsFilter is not None
    customizations = query.trendsFilter.resultCustomizations
    assert isinstance(customizations, dict)
    customization = customizations['{"series":0}']
    assert isinstance(customization, ResultCustomizationByValue)
    assert customization.color == "preset-16"
