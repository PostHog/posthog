from posthog.hogql_queries.experiment_result_query_runner import ExperimentResultQueryRunner
from posthog.schema import (
    BreakdownFilter,
    EventsNode,
    ExperimentResultQuery,
    FunnelsQuery,
    TrendsQuery,
    ExperimentResultFunnelQueryResponse,
    ExperimentResultTrendQueryResponse,
)
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from freezegun import freeze_time
from typing import cast


class TestExperimentResultQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()

    def test_experiment_result_query_runner_FUNNEL(self):
        feature_flag_property = f"$feature/test-experiment"

        with freeze_time("2020-01-10 12:00:00"):
            for variant, purchase_count in [("control", 6), ("test", 8)]:
                for i in range(10):
                    _create_person(distinct_ids=[f"user_{variant}_{i}"], team_id=self.team.pk)
                    _create_event(
                        team=self.team,
                        event="$pageview",
                        distinct_id=f"user_{variant}_{i}",
                        timestamp="2020-01-02T12:00:00Z",
                        properties={feature_flag_property: variant},
                    )
                    if i < purchase_count:
                        _create_event(
                            team=self.team,
                            event="purchase",
                            distinct_id=f"user_{variant}_{i}",
                            timestamp="2020-01-02T12:01:00Z",
                            properties={feature_flag_property: variant},
                        )

        flush_persons_and_events()

        funnels_query = FunnelsQuery(
            series=[EventsNode(event="$pageview"), EventsNode(event="purchase")],
            dateRange={"date_from": "2020-01-01", "date_to": "2020-01-14"},
            breakdownFilter=BreakdownFilter(breakdown=feature_flag_property),
        )
        experiment_query = ExperimentResultQuery(
            kind="ExperimentResultQuery", source=funnels_query, variants=["control", "test"]
        )

        runner = ExperimentResultQueryRunner(query=experiment_query, team=self.team)
        result = runner.calculate()

        self.assertEqual(result.insight, "FUNNELS")
        self.assertEqual(len(result.results), 2)

        funnel_result = cast(ExperimentResultFunnelQueryResponse, result)

        self.assertIn("control", funnel_result.results)
        self.assertIn("test", funnel_result.results)

        control_result = funnel_result.results["control"]
        test_result = funnel_result.results["test"]

        self.assertEqual(control_result.success_count, 6)
        self.assertEqual(control_result.failure_count, 4)
        self.assertEqual(test_result.success_count, 8)
        self.assertEqual(test_result.failure_count, 2)

    def test_experiment_result_query_runner_TRENDS(self):
        feature_flag_property = f"$feature/test-experiment"

        for variant, count in [("control", 11), ("test", 15)]:
            for i in range(count):
                with freeze_time("2020-01-10 12:00:00"):
                    _create_event(
                        team=self.team,
                        event="$pageview",
                        distinct_id=f"user_{variant}_{i}",
                        properties={feature_flag_property: variant},
                    )
        flush_persons_and_events()

        trends_query = TrendsQuery(
            kind="TrendsQuery",
            series=[EventsNode(event="$pageview")],
            dateRange={"date_from": "2020-01-01", "date_to": "2020-01-14"},
            breakdownFilter=BreakdownFilter(breakdown=feature_flag_property),
        )
        experiment_query = ExperimentResultQuery(
            kind="ExperimentResultQuery", source=trends_query, variants=["control", "test"]
        )

        runner = ExperimentResultQueryRunner(query=experiment_query, team=self.team)
        result = runner.calculate()

        self.assertEqual(result.insight, "TRENDS")
        self.assertEqual(len(result.results), 2)

        trend_result = cast(ExperimentResultTrendQueryResponse, result)

        self.assertIn("control", trend_result.results)
        self.assertIn("test", trend_result.results)

        control_result = trend_result.results["control"]
        test_result = trend_result.results["test"]

        self.assertEqual(control_result.count, 11)
        self.assertEqual(test_result.count, 15)
