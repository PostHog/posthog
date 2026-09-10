from datetime import UTC, date, datetime

from parameterized import parameterized

from posthog.temporal.billing_usage_rollup.workflow import next_rollup_day


@parameterized.expand(
    [
        (
            "rollup waits for a full correction window",
            datetime(2026, 6, 2, 5, tzinfo=UTC),
            date(2026, 5, 3),
            date(2026, 5, 4),
        ),
        (
            "rollup catches up from its oldest missing day",
            datetime(2026, 6, 2, 5, tzinfo=UTC),
            date(2026, 5, 1),
            date(2026, 5, 2),
        ),
        ("rollup does not repeat a completed day", datetime(2026, 6, 2, 5, tzinfo=UTC), date(2026, 5, 4), None),
    ]
)
def test_next_rollup_day(_case: str, now: datetime, last_completed_day: date, expected: date | None) -> None:
    assert next_rollup_day(last_completed_day, now) == expected
