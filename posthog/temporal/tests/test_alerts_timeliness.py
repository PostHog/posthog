from datetime import UTC, datetime, timedelta

import pytest

from posthog.schema import AlertCalculationInterval

from posthog.slo.types import SloOutcome
from posthog.temporal.alerts.timeliness import alert_timeliness_threshold_ms, build_alert_timeliness_completion


@pytest.mark.parametrize(
    "calculation_interval,expected_ms",
    [
        ("every_minute", 60_000),
        (AlertCalculationInterval.EVERY_15_MINUTES.value, 60_000),
        (AlertCalculationInterval.HOURLY.value, 120_000),
        (AlertCalculationInterval.DAILY.value, 120_000),
        (AlertCalculationInterval.WEEKLY.value, 120_000),
        (AlertCalculationInterval.MONTHLY.value, 120_000),
        ("unexpected_interval", 120_000),
        (None, 120_000),
    ],
)
def test_alert_timeliness_threshold_is_five_percent_clamped(calculation_interval: str | None, expected_ms: int) -> None:
    assert alert_timeliness_threshold_ms(calculation_interval) == expected_ms


def test_timeliness_completion_succeeds_at_threshold() -> None:
    scheduled = datetime(2024, 6, 3, 10, 0, tzinfo=UTC)

    outcome, props = build_alert_timeliness_completion(
        calculation_interval=AlertCalculationInterval.EVERY_15_MINUTES.value,
        scheduled_check_at=scheduled.isoformat(),
        actual_check_start_at=scheduled + timedelta(seconds=60),
    )

    assert outcome == SloOutcome.SUCCESS
    assert props["evaluation_lag_ms"] == 60_000
    assert props["timeliness_threshold_ms"] == 60_000
    assert props["is_late"] is False


def test_timeliness_completion_fails_when_late_even_if_execution_can_succeed() -> None:
    scheduled = datetime(2024, 6, 3, 10, 0, tzinfo=UTC)

    outcome, props = build_alert_timeliness_completion(
        calculation_interval=AlertCalculationInterval.HOURLY.value,
        scheduled_check_at=scheduled.isoformat(),
        actual_check_start_at=scheduled + timedelta(seconds=121),
    )

    assert outcome == SloOutcome.FAILURE
    assert props["evaluation_lag_ms"] == 121_000
    assert props["timeliness_threshold_ms"] == 120_000
    assert props["is_late"] is True


@pytest.mark.parametrize(
    "scheduled_check_at",
    [
        "2024-06-03T10:00:00Z",
        "2024-06-03T10:00:00+00:00",
        "2024-06-03T12:00:00+02:00",
        "2024-06-03T10:00:00",
    ],
)
def test_timeliness_completion_parses_supported_timestamp_shapes(scheduled_check_at: str) -> None:
    outcome, props = build_alert_timeliness_completion(
        calculation_interval=AlertCalculationInterval.HOURLY.value,
        scheduled_check_at=scheduled_check_at,
        actual_check_start_at=datetime(2024, 6, 3, 10, 1, tzinfo=UTC),
    )

    assert outcome == SloOutcome.SUCCESS
    assert props["scheduled_due_at"] == "2024-06-03T10:00:00+00:00"
    assert props["evaluation_lag_ms"] == 60_000
