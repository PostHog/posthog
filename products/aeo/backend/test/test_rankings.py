from parameterized import parameterized

from products.aeo.backend.rankings import comparable_previous_share


@parameterized.expand(
    [
        ("comparable_window", [100, 40], [80, 20], 0.25),
        ("tracking_started_late", [4000, 1800], [90, 40], None),
        ("at_the_threshold", [100, 40], [25, 5], 0.2),
        ("no_answers_before", [10, 4], [0, 0], None),
    ]
)
def test_comparable_previous_share(_name: str, current: list[int], previous: list[int], expected: float | None) -> None:
    assert comparable_previous_share(current, previous) == expected
