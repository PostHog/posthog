from posthog.hogql_queries.experiment_funnel_query_runner import ExperimentFunnelQueryRunner
from posthog.models.experiment import Experiment
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.schema import (
    BreakdownFilter,
    EventsNode,
    ExperimentFunnelQuery,
    ExperimentFunnelQueryResponse,
    FunnelsQuery,
)
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from freezegun import freeze_time
from typing import cast


class TestExperimentFunnelQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def test_query_runner(self):
        feature_flag = FeatureFlag.objects.create(
            name="Test experiment flag",
            key="test-experiment",
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {
                            "key": "control",
                            "name": "Control",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "test",
                            "name": "Test",
                            "rollout_percentage": 50,
                        },
                    ]
                },
            },
            created_by=self.user,
        )
        experiment = Experiment.objects.create(
            name="test-experiment",
            team=self.team,
            feature_flag=feature_flag,
        )

        feature_flag_property = f"$feature/{feature_flag.key}"

        funnels_query = FunnelsQuery(
            series=[EventsNode(event="$pageview"), EventsNode(event="purchase")],
            dateRange={"date_from": "2020-01-01", "date_to": "2020-01-14"},
            breakdownFilter=BreakdownFilter(breakdown=feature_flag_property),
        )
        experiment_query = ExperimentFunnelQuery(
            experiment_id=experiment.id,
            kind="ExperimentFunnelQuery",
            source=funnels_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

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

        query_runner = ExperimentFunnelQueryRunner(
            query=ExperimentFunnelQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        result = query_runner.calculate()

        self.assertEqual(result.insight, "FUNNELS")
        self.assertEqual(len(result.results), 2)

        funnel_result = cast(ExperimentFunnelQueryResponse, result)

        self.assertIn("control", funnel_result.results)
        self.assertIn("test", funnel_result.results)

        control_result = funnel_result.results["control"]
        test_result = funnel_result.results["test"]

        self.assertEqual(control_result.success_count, 6)
        self.assertEqual(control_result.failure_count, 4)
        self.assertEqual(test_result.success_count, 8)
        self.assertEqual(test_result.failure_count, 2)
