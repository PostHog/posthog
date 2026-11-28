from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.ai.anomaly_investigation.ingestion_freshness import (
    describe_ingestion_freshness,
    render_ingestion_freshness,
)
from posthog.temporal.ai.anomaly_investigation.prompts import build_anomaly_context

MEASURED_AT = datetime(2026, 11, 25, 11, 37, tzinfo=UTC)


@parameterized.expand(
    [
        ("lagging", timedelta(minutes=28), True),
        ("on_time", timedelta(minutes=1), False),
    ]
)
def test_states_lag_only_when_the_newest_event_is_old(_name: str, age: timedelta, lagging: bool) -> None:
    block = render_ingestion_freshness(
        event="$pageview",
        measured_at=MEASURED_AT,
        newest=MEASURED_AT - age,
        counts={datetime(2026, 11, 25, 11, 0, tzinfo=UTC): 10},
        evaluation_delay_intervals=0,
    )

    assert f"{int(age.total_seconds() // 60)} minute" in block
    assert ("Ingestion is behind" in block) is lagging


def test_shows_the_empty_buckets_up_to_the_measurement() -> None:
    block = render_ingestion_freshness(
        event=None,
        measured_at=MEASURED_AT,
        newest=datetime(2026, 11, 25, 11, 9, tzinfo=UTC),
        counts={
            datetime(2026, 11, 25, 10, 55, tzinfo=UTC): 1200,
            datetime(2026, 11, 25, 11, 5, tzinfo=UTC): 300,
        },
        evaluation_delay_intervals=0,
    )

    assert (
        "Events per 5 minutes, oldest first: 10:55 1,200, 11:00 0, 11:05 300, 11:10 0, 11:15 0, "
        "11:20 0, 11:25 0, 11:30 0, 11:35 0." in block
    )


@patch("posthog.temporal.ai.anomaly_investigation.ingestion_freshness.execute_hogql_query")
def test_says_nothing_rather_than_failing_the_investigation(mock_query: MagicMock) -> None:
    mock_query.side_effect = RuntimeError("ClickHouse is down")

    assert describe_ingestion_freshness(team=MagicMock(), event="$pageview", evaluation_delay_intervals=0) == ""


def test_context_carries_the_freshness_block() -> None:
    context = build_anomaly_context(
        alert_name="Replay active users",
        metric_description="Replay active users",
        detector_type="zscore",
        triggered_dates=["2026-11-25 10:00:00"],
        triggered_metadata=None,
        calculated_value=978.0,
        interval="hour",
        metric_definition="Metric definition — ...",
        ingestion_freshness='Ingestion freshness for event "$pageview"',
    )

    assert 'Ingestion freshness for event "$pageview"' in context


class TestIngestionFreshnessAgainstClickHouse(ClickhouseTestMixin, BaseTest):
    def test_measures_the_newest_event_of_the_alerted_event_only(self) -> None:
        now = datetime.now(UTC)
        _create_person(team_id=self.team.pk, distinct_ids=["person"])
        for minutes_ago in (40, 30):
            _create_event(
                team=self.team, event="$pageview", distinct_id="person", timestamp=now - timedelta(minutes=minutes_ago)
            )
        _create_event(team=self.team, event="$autocapture", distinct_id="person", timestamp=now)
        flush_persons_and_events()

        pageviews = describe_ingestion_freshness(team=self.team, event="$pageview", evaluation_delay_intervals=1)
        all_events = describe_ingestion_freshness(team=self.team, event=None, evaluation_delay_intervals=1)

        assert "30 minutes before the measurement" in pageviews
        assert "Ingestion is behind" in pageviews
        assert "Alert evaluation delay: 1 interval(s)." in pageviews
        assert "Ingestion is behind" not in all_events
