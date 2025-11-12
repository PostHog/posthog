from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
from unittest.mock import patch

from posthog.schema import (
    DateRange,
    EventPropertyFilter,
    PropertyMathType,
    PropertyOperator,
    SamplingRate,
    WebAnalyticsSampling,
    WebVitalsMetric,
    WebVitalsPathBreakdownQuery,
    WebVitalsPathBreakdownResult,
    WebVitalsPathBreakdownResultItem,
)

from posthog.hogql_queries.web_analytics.web_vitals_path_breakdown import WebVitalsPathBreakdownQueryRunner


@snapshot_clickhouse_queries
class TestWebVitalsPathBreakdownQueryRunner(ClickhouseTestMixin, APIBaseTest):
    QUERY_TIMESTAMP = "2025-01-29"

    def _create_events(self, data, metric: WebVitalsMetric = WebVitalsMetric.INP):
        for distinct_id, timestamps in data:
            for timestamp, path, value in timestamps:
                _create_event(
                    team=self.team,
                    event="$web_vitals",
                    distinct_id=distinct_id,
                    timestamp=timestamp,
                    properties={
                        f"$web_vitals_{metric.value}_value": value,
                        "$pathname": path,
                    },
                )

        flush_persons_and_events()

    def _run_web_vitals_path_breakdown_query(
        self,
        date_from,
        date_to,
        thresholds: tuple[float, float],
        metric: WebVitalsMetric = WebVitalsMetric.INP,
        percentile: PropertyMathType = PropertyMathType.P75,
        properties=None,
        sampling: WebAnalyticsSampling | None = None,
    ):
        with freeze_time(self.QUERY_TIMESTAMP):
            query = WebVitalsPathBreakdownQuery(
                dateRange=DateRange(date_from=date_from, date_to=date_to),
                metric=metric,
                percentile=percentile,
                thresholds=thresholds,
                properties=properties or [],
                sampling=sampling,
            )

            runner = WebVitalsPathBreakdownQueryRunner(team=self.team, query=query)
            return runner.calculate()

    def test_no_crash_when_no_data(self):
        results = self._run_web_vitals_path_breakdown_query(
            "2025-01-08",
            "2025-01-15",
            (100, 200),
            WebVitalsMetric.INP,
            PropertyMathType.P75,
        ).results

        self.assertEqual([WebVitalsPathBreakdownResult(good=[], needs_improvements=[], poor=[])], results)

    def test_no_data_for_different_metric(self):
        self._create_events(
            [
                (
                    "distinct_id_1",
                    [
                        ("2025-01-08", "/path1", 100),
                        ("2025-01-08", "/path2", 200),
                    ],
                ),
            ],
            WebVitalsMetric.INP,
        )

        results = self._run_web_vitals_path_breakdown_query(
            "2025-01-08",
            "2025-01-15",
            (100, 200),
            WebVitalsMetric.LCP,
            PropertyMathType.P75,
        ).results

        self.assertEqual([WebVitalsPathBreakdownResult(good=[], needs_improvements=[], poor=[])], results)

    def test_no_data_for_different_period(self):
        self._create_events(
            [
                (
                    "distinct_id_1",
                    [
                        ("2024-01-12", "/path1", 100),
                        ("2024-01-12", "/path2", 200),
                    ],
                ),
            ],
            WebVitalsMetric.INP,
        )

        results = self._run_web_vitals_path_breakdown_query(
            "2025-01-08",
            "2025-01-15",
            (100, 200),
            WebVitalsMetric.INP,
            PropertyMathType.P75,
        ).results

        self.assertEqual([WebVitalsPathBreakdownResult(good=[], needs_improvements=[], poor=[])], results)

    def test_data_correctly_split_between_bands(self):
        self._create_events(
            [
                (
                    "distinct_id_1",
                    [
                        ("2025-01-05", "/path_outside_before_period", 50),
                        ("2025-01-10", "/path1", 50),
                        ("2025-01-10", "/path2", 100),
                        ("2025-01-10", "/path3", 150),
                        ("2025-01-10", "/path4", 200),
                        ("2025-01-10", "/path5", 250),
                        ("2025-01-10", "/path6", 300),
                        ("2025-01-18", "/path_outside_after_period", 50),
                    ],
                ),
            ],
            WebVitalsMetric.INP,
        )

        results = self._run_web_vitals_path_breakdown_query(
            "2025-01-08",
            "2025-01-15",
            (100, 200),
            WebVitalsMetric.INP,
            PropertyMathType.P75,
        ).results

        self.assertEqual(
            [
                WebVitalsPathBreakdownResult(
                    good=[
                        WebVitalsPathBreakdownResultItem(path="/path1", value=50),
                        WebVitalsPathBreakdownResultItem(path="/path2", value=100),
                    ],
                    needs_improvements=[
                        WebVitalsPathBreakdownResultItem(path="/path3", value=150),
                        WebVitalsPathBreakdownResultItem(path="/path4", value=200),
                    ],
                    poor=[
                        WebVitalsPathBreakdownResultItem(path="/path5", value=250),
                        WebVitalsPathBreakdownResultItem(path="/path6", value=300),
                    ],
                )
            ],
            results,
        )

    def test_limit_of_20_paths(self):
        self._create_events(
            [
                (
                    "distinct_id_1",
                    [
                        ("2025-01-10", f"/path/a/{idx}", 50)
                        for idx in range(30)  # Creating 30, but should be limited to 20
                    ],
                ),
                (
                    "distinct_id_1",
                    [
                        ("2025-01-10", f"/path/b/{idx}", 150)
                        for idx in range(25)  # Creating 25, but should be limited to 20
                    ],
                ),
                (
                    "distinct_id_1",
                    [
                        ("2025-01-10", f"/path/c/{idx}", 499)
                        for idx in range(5)  # Creating only 5, return these 5
                    ],
                ),
            ],
            WebVitalsMetric.INP,
        )

        results = self._run_web_vitals_path_breakdown_query(
            "2025-01-08",
            "2025-01-15",
            (100, 200),
            WebVitalsMetric.INP,
            PropertyMathType.P75,
        ).results

        self.assertEqual(20, len(results[0].good))
        self.assertEqual(20, len(results[0].needs_improvements))
        self.assertEqual(5, len(results[0].poor))

    def test_percentile_is_applied(self):
        self._create_events(
            [
                (
                    "distinct_id_1",
                    [
                        ("2025-01-10", "/path1", 50),
                        ("2025-01-10", "/path1", 100),
                        ("2025-01-10", "/path1", 150),
                        ("2025-01-10", "/path1", 200),
                        ("2025-01-10", "/path1", 250),
                        ("2025-01-10", "/path1", 300),
                    ],
                ),
            ],
            WebVitalsMetric.INP,
        )

        for percentile, value in [
            (PropertyMathType.P75, 237.5),
            (PropertyMathType.P90, 275.0),
            (PropertyMathType.P99, 297.5),
        ]:
            results = self._run_web_vitals_path_breakdown_query(
                "2025-01-08",
                "2025-01-15",
                (100, 200),
                WebVitalsMetric.INP,
                percentile,
            ).results

            self.assertEqual(
                [
                    WebVitalsPathBreakdownResult(
                        good=[],
                        needs_improvements=[],
                        poor=[WebVitalsPathBreakdownResultItem(path="/path1", value=value)],
                    )
                ],
                results,
            )

    def test_properties_are_applied(self):
        self._create_events(
            [
                (
                    "distinct_id_1",
                    [
                        ("2025-01-10", "/path1", 50),
                        ("2025-01-10", "/path2", 50),  # Won't be included because of the property filter below
                    ],
                ),
            ],
            WebVitalsMetric.INP,
        )

        results = self._run_web_vitals_path_breakdown_query(
            "2025-01-08",
            "2025-01-15",
            (100, 200),
            properties=[EventPropertyFilter(key="$pathname", operator=PropertyOperator.EXACT, value="/path1")],
        ).results

        self.assertEqual(
            [
                WebVitalsPathBreakdownResult(
                    good=[WebVitalsPathBreakdownResultItem(path="/path1", value=50)], needs_improvements=[], poor=[]
                )
            ],
            results,
        )

    def test_sampling_rate_is_applied(self):
        self._create_events(
            [
                (
                    "distinct_id_1",
                    [
                        ("2025-01-10", "/path1", 50),
                        ("2025-01-10", "/path2", 100),
                    ],
                ),
            ],
            WebVitalsMetric.INP,
        )

        response = self._run_web_vitals_path_breakdown_query(
            "2025-01-08",
            "2025-01-15",
            (100, 200),
            sampling=WebAnalyticsSampling(enabled=True, forceSamplingRate=SamplingRate(numerator=50)),
        )

        self.assertEqual(response.samplingRate, SamplingRate(numerator=50))

    def test_sampling_rate_auto_when_not_specified(self):
        self._create_events(
            [
                (
                    "distinct_id_1",
                    [
                        ("2025-01-10", "/path1", 50),
                    ],
                ),
            ],
            WebVitalsMetric.INP,
        )

        response = self._run_web_vitals_path_breakdown_query(
            "2025-01-08",
            "2025-01-15",
            (100, 200),
            sampling=WebAnalyticsSampling(enabled=True),
        )

        # Should use auto-sampling (no forced rate)
        self.assertIsNotNone(response.samplingRate)
        self.assertEqual(response.samplingRate.numerator, 1)

    def test_auto_sampling_no_sampling_for_low_volume(self):
        # Create minimal events (< 100k events)
        # With so few events, auto-sampling should return 100% (1/1)
        self._create_events(
            [
                (
                    "distinct_id_1",
                    [
                        ("2025-01-10", "/path1", 50),
                    ],
                ),
            ],
            WebVitalsMetric.INP,
        )

        response = self._run_web_vitals_path_breakdown_query(
            "2025-01-08",
            "2025-01-15",
            (100, 200),
            sampling=WebAnalyticsSampling(enabled=True),
        )

        # Should use 100% sampling for < 100k events
        self.assertEqual(response.samplingRate, SamplingRate(numerator=1))

    def test_auto_sampling_10_percent_for_medium_volume(self):
        # Test that when auto-sampling returns 10%, it's properly applied
        self._create_events(
            [
                (
                    "distinct_id_1",
                    [
                        ("2025-01-10", "/path1", 50),
                    ],
                ),
            ],
            WebVitalsMetric.INP,
        )

        with freeze_time(self.QUERY_TIMESTAMP):
            query = WebVitalsPathBreakdownQuery(
                dateRange=DateRange(date_from="2025-01-08", date_to="2025-01-15"),
                metric=WebVitalsMetric.INP,
                percentile=PropertyMathType.P75,
                thresholds=(100, 200),
                properties=[],
                sampling=WebAnalyticsSampling(enabled=True),
            )

            runner = WebVitalsPathBreakdownQueryRunner(team=self.team, query=query)

            # Mock the _sample_rate property to return 10% sampling
            with patch.object(
                type(runner),
                "_sample_rate",
                new_callable=lambda: property(lambda _: SamplingRate(numerator=1, denominator=10)),
            ):
                response = runner.calculate()

        # Should use 10% sampling for 100k-999k events
        self.assertEqual(response.samplingRate, SamplingRate(numerator=1, denominator=10))

    def test_auto_sampling_1_percent_for_high_volume(self):
        # Test that when auto-sampling returns 1%, it's properly applied
        self._create_events(
            [
                (
                    "distinct_id_1",
                    [
                        ("2025-01-10", "/path1", 50),
                    ],
                ),
            ],
            WebVitalsMetric.INP,
        )

        with freeze_time(self.QUERY_TIMESTAMP):
            query = WebVitalsPathBreakdownQuery(
                dateRange=DateRange(date_from="2025-01-08", date_to="2025-01-15"),
                metric=WebVitalsMetric.INP,
                percentile=PropertyMathType.P75,
                thresholds=(100, 200),
                properties=[],
                sampling=WebAnalyticsSampling(enabled=True),
            )

            runner = WebVitalsPathBreakdownQueryRunner(team=self.team, query=query)

            # Mock the _sample_rate property to return 1% sampling
            with patch.object(
                type(runner),
                "_sample_rate",
                new_callable=lambda: property(lambda _: SamplingRate(numerator=1, denominator=100)),
            ):
                response = runner.calculate()

        # Should use 1% sampling for >= 1M events
        self.assertEqual(response.samplingRate, SamplingRate(numerator=1, denominator=100))
