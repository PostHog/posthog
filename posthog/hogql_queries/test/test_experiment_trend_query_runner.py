from django.test import override_settings
from posthog.hogql_queries.experiment_trend_query_runner import ExperimentTrendQueryRunner
from posthog.schema import (
    BreakdownFilter,
    EventsNode,
    ExperimentTrendQuery,
    ExperimentTrendQueryResponse,
    TrendsQuery,
)
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from freezegun import freeze_time
from typing import cast


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentTrendQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def test_query_runner(self):
        feature_flag_property = f"$feature/test-experiment"

        with freeze_time("2020-01-10 12:00:00"):
            # Populate experiment events
            for variant, count in [("control", 11), ("test", 15)]:
                for i in range(count):
                    _create_event(
                        team=self.team,
                        event="$pageview",
                        distinct_id=f"user_{variant}_{i}",
                        properties={feature_flag_property: variant},
                    )

            # Populate exposure events
            for variant, count in [("control", 7), ("test", 9)]:
                for i in range(count):
                    _create_event(
                        team=self.team,
                        event="$feature_flag_called",
                        distinct_id=f"user_{variant}_{i}",
                        properties={feature_flag_property: variant},
                    )

        flush_persons_and_events()

        count_query = TrendsQuery(
            kind="TrendsQuery",
            series=[EventsNode(event="$pageview")],
            dateRange={"date_from": "2020-01-01", "date_to": "2020-01-14"},
            breakdownFilter=BreakdownFilter(breakdown=feature_flag_property),
        )
        exposure_query = TrendsQuery(
            kind="TrendsQuery",
            series=[EventsNode(event="$feature_flag_called")],
            dateRange={"date_from": "2020-01-01", "date_to": "2020-01-14"},
            breakdownFilter=BreakdownFilter(breakdown=feature_flag_property),
        )

        experiment_query = ExperimentTrendQuery(
            kind="ExperimentTrendQuery",
            count_source=count_query,
            exposure_source=exposure_query,
            variants=["control", "test"],
        )

        runner = ExperimentTrendQueryRunner(query=experiment_query, team=self.team)
        result = runner.calculate()

        self.assertEqual(result.insight, "TRENDS")
        self.assertEqual(len(result.results), 2)

        trend_result = cast(ExperimentTrendQueryResponse, result)

        self.assertIn("control", trend_result.results)
        self.assertIn("test", trend_result.results)

        control_result = trend_result.results["control"]
        test_result = trend_result.results["test"]

        self.assertEqual(control_result.count, 11)
        self.assertEqual(test_result.count, 15)

        self.assertEqual(control_result.exposure, 7)
        self.assertEqual(test_result.exposure, 9)
