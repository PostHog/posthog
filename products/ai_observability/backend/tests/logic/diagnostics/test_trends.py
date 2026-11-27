from parameterized import parameterized

from products.ai_observability.backend.logic.diagnostics.trends import (
    Trend,
    change_label,
    error_change_tone,
    paired_with_range,
)
from products.ai_observability.backend.logic.traces.trace_metrics import ChangeTone


@parameterized.expand(
    [
        ("rise", 412, 251, "+64%"),
        ("fall_with_a_minus_sign", 121, 125, "−3%"),
        ("rise_just_under_the_increase_minimum", 1195, 1000, "+19%"),
        ("rise_of_exactly_the_increase_minimum", 12, 10, "+20%"),
        ("fall_of_exactly_the_decrease_minimum", 8, 10, "−20%"),
        ("fall_just_under_the_decrease_minimum", 805, 1000, "−19%"),
        ("from_zero", 84, 0, "was 0"),
        ("no_previous_window", 5, None, None),
        ("nothing_in_either_period", 0, 0, "0%"),
    ]
)
def test_change_label(_name: str, current: int, previous: int | None, expected: str | None) -> None:
    assert change_label(current, previous) == expected


@parameterized.expand(
    [
        ("increasing", Trend.INCREASING, ChangeTone.BAD),
        ("decreasing", Trend.DECREASING, ChangeTone.GOOD),
        ("steady", Trend.STEADY, ChangeTone.NEUTRAL),
    ]
)
def test_error_change_tone(_name: str, trend: Trend, expected: ChangeTone) -> None:
    assert error_change_tone(trend) == expected


@parameterized.expand(
    [
        ("previous_has_a_bucket_more", (1, 2, 3, 4), 3, (1, 2, 3)),
        ("previous_has_a_bucket_fewer", (1, 2), 3, (1, 2, 0)),
        ("same_length", (1, 2, 3), 3, (1, 2, 3)),
        ("no_previous_period", (), 3, ()),
    ]
)
def test_paired_with_range(_name: str, previous: tuple[int, ...], bucket_count: int, expected: tuple[int, ...]) -> None:
    assert paired_with_range(previous, bucket_count) == expected
