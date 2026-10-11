from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

import numpy as np
from parameterized import parameterized

from posthog.schema import (
    BreakdownFilter,
    ChartDisplayType,
    CompareFilter,
    DateRange,
    EventsNode,
    IntervalType,
    TrendsFilter,
    TrendsQuery,
)

from products.alerts.backend.anomaly_scoring.config import default_detector_config, effective_config
from products.alerts.backend.anomaly_scoring.emit import FLAG_METRIC, SCORE_METRIC, VALUE_METRIC, gauge_samples
from products.alerts.backend.anomaly_scoring.scoring import (
    InsightScores,
    ScoredPoint,
    ScoredSeries,
    UnsupportedInsightError,
    build_scoring_query,
    score_series,
)

NEW_YORK = ZoneInfo("America/New_York")


def _daily_buckets(count: int) -> list[datetime]:
    start = datetime(2026, 1, 1, tzinfo=NEW_YORK)
    return [start + timedelta(days=i) for i in range(count)]


class TestScoreSeries(SimpleTestCase):
    @parameterized.expand([("spike", 400.0), ("drop", 5.0)])
    def test_flags_the_outlier_and_returns_only_new_completed_buckets(self, _name: str, outlier: float) -> None:
        values = list(np.random.default_rng(0).normal(100, 5, size=60))
        spike_index = 58
        values[spike_index] = outlier
        buckets = _daily_buckets(60)
        # Midway through the last bucket, so it is still ongoing.
        now = buckets[-1] + timedelta(hours=12)
        after = buckets[49]

        points = score_series(
            values,
            buckets,
            detector_config=default_detector_config(),
            interval=IntervalType.DAY,
            now=now,
            after=after,
        )

        assert [p.bucket for p in points] == [b.astimezone(UTC) for b in buckets[50:59]]
        spike = points[-1]
        assert spike.value == outlier
        assert spike.flag
        assert spike.score == max(p.score for p in points if p.score is not None)

    def test_no_completed_bucket_returns_nothing(self) -> None:
        buckets = _daily_buckets(1)

        points = score_series(
            [1.0],
            buckets,
            detector_config=default_detector_config(),
            interval=IntervalType.DAY,
            now=buckets[0] + timedelta(hours=1),
        )

        assert points == []


class TestBuildScoringQuery(SimpleTestCase):
    def test_fetches_lookback_without_compare_and_caps_breakdowns(self) -> None:
        query = TrendsQuery(
            series=[EventsNode(event="$pageview")],
            interval=IntervalType.DAY,
            dateRange=DateRange(date_from="-7d", date_to="-1d"),
            compareFilter=CompareFilter(compare=True),
            breakdownFilter=BreakdownFilter(breakdown="$browser", breakdown_limit=50),
        )

        scoring = build_scoring_query(query, effective_config(None))

        assert scoring.dateRange == DateRange(date_from="-120d")
        assert scoring.compareFilter is None
        assert scoring.breakdownFilter is not None
        assert scoring.breakdownFilter.breakdown == "$browser"
        assert scoring.breakdownFilter.breakdown_limit == 10
        assert scoring.breakdownFilter.breakdown_hide_other_aggregation is True
        assert scoring.series == query.series

    @parameterized.expand(
        [
            ("single_value", IntervalType.DAY, ChartDisplayType.BOLD_NUMBER),
            ("month_interval", IntervalType.MONTH, ChartDisplayType.ACTIONS_LINE_GRAPH),
        ]
    )
    def test_unsupported_shapes_are_skipped(
        self, _name: str, interval: IntervalType, display: ChartDisplayType
    ) -> None:
        query = TrendsQuery(
            series=[EventsNode(event="$pageview")], interval=interval, trendsFilter=TrendsFilter(display=display)
        )

        with self.assertRaises(UnsupportedInsightError):
            build_scoring_query(query, effective_config(None))


class TestGaugeSamples(SimpleTestCase):
    @parameterized.expand([("bucket_close", False, timedelta(days=1)), ("bucket_start", True, timedelta(0))])
    def test_stamps_buckets_and_skips_score_while_training(
        self, _name: str, stamp_bucket_start: bool, offset: timedelta
    ) -> None:
        day = datetime(2026, 10, 1, tzinfo=UTC)
        scores = InsightScores(
            interval=IntervalType.DAY,
            detector_type="zscore",
            detector_version="abc123",
            series=[
                ScoredSeries(
                    series_index=0,
                    label="$pageview",
                    breakdown_value="Chrome",
                    points=[
                        ScoredPoint(bucket=day, value=5.0, score=None, flag=False),
                        ScoredPoint(bucket=day + timedelta(days=1), value=50.0, score=0.97, flag=True),
                    ],
                )
            ],
        )

        samples = gauge_samples(7, scores, stamp_bucket_start=stamp_bucket_start)

        second = day + timedelta(days=1)
        assert [(s.name, s.timestamp, s.value) for s in samples] == [
            (VALUE_METRIC, day + offset, 5.0),
            (VALUE_METRIC, second + offset, 50.0),
            (SCORE_METRIC, second + offset, 0.97),
            (FLAG_METRIC, second + offset, 1.0),
        ]
        assert samples[0].labels == {
            "insight_id": "7",
            "series": "0",
            "series_label": "$pageview",
            "interval": "day",
            "detector_type": "zscore",
            "detector_version": "abc123",
            "breakdown_value": "Chrome",
        }
