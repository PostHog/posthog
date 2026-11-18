from datetime import timedelta

from parameterized import parameterized

from posthog.scheduling.jitter import deterministic_offset


@parameterized.expand(
    [
        ("whole_window", timedelta(minutes=10), timedelta(0), timedelta(minutes=2, seconds=53)),
        ("after_floor", timedelta(minutes=12), timedelta(minutes=2), timedelta(minutes=12, seconds=53)),
        ("empty_window", timedelta(0), timedelta(minutes=2), timedelta(minutes=2)),
    ]
)
def test_deterministic_offset(_name: str, window: timedelta, floor: timedelta, expected: timedelta) -> None:
    assert deterministic_offset("alert-1", window, floor=floor) == expected

    offsets = [deterministic_offset(f"alert-{index}", window, floor=floor) for index in range(500)]
    assert min(offsets) >= floor
    assert max(offsets) <= floor + max(window - timedelta(seconds=1), timedelta(0))
