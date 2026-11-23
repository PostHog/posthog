from datetime import UTC, datetime, timedelta

from parameterized import parameterized

from products.ai_observability.backend.logic.traces.events_fallback import AI_EVENTS_RETENTION_DAYS, FallbackWindow

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
A_DAY_SHORT_OF_RETENTION = timedelta(days=AI_EVENTS_RETENTION_DAYS - 1)


@parameterized.expand(
    [
        ("a minute past a day short of retention", A_DAY_SHORT_OF_RETENTION + timedelta(minutes=1), True),
        ("exactly a day short of retention", A_DAY_SHORT_OF_RETENTION, False),
        ("two days short of retention", A_DAY_SHORT_OF_RETENTION - timedelta(days=1), False),
    ]
)
def test_may_hold_aged_out_events(_name: str, start_age: timedelta, expected: bool) -> None:
    window = FallbackWindow(start=NOW - start_age, end=NOW)

    assert window.may_hold_aged_out_events(NOW) is expected
