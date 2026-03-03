from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.schema import EventsNode, ExperimentMeanMetric, ExperimentMetricMathType, ExperimentQuery

from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
from posthog.models.experiment import Experiment
from posthog.models.feature_flag.feature_flag import FeatureFlag


class TestResolvePhaseDateRange(APIBaseTest):
    def _create_experiment_with_phases(self, phases: list | None = None) -> Experiment:
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            key="phase-date-range-test",
            filters={
                "groups": [{"rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                },
            },
            created_by=self.user,
        )
        return Experiment.objects.create(
            team=self.team,
            name="Phase Date Range Test",
            feature_flag=feature_flag,
            start_date="2025-01-01T00:00:00+00:00",
            end_date="2025-06-01T00:00:00+00:00",
            phases=phases or [],
        )

    def _create_query_runner(self, experiment: Experiment, phase_index: int | None = None) -> ExperimentQueryRunner:
        metric = ExperimentMeanMetric(
            source=EventsNode(event="$pageview", math=ExperimentMetricMathType.TOTAL),
        )
        query = ExperimentQuery(
            kind="ExperimentQuery",
            experiment_id=experiment.id,
            metric=metric,
            phase_index=phase_index,
        )
        return ExperimentQueryRunner(query=query, team=self.team)

    @parameterized.expand(
        [
            (
                "no_phases_no_index",
                [],
                None,
                "2025-01-01",
                "2025-06-01",
            ),
            (
                "no_phases_with_index",
                [],
                0,
                "2025-01-01",
                "2025-06-01",
            ),
            (
                "phases_no_index",
                [
                    {
                        "start_date": "2025-01-01T00:00:00+00:00",
                        "end_date": "2025-03-01T00:00:00+00:00",
                    },
                    {"start_date": "2025-03-01T00:00:00+00:00", "end_date": None},
                ],
                None,
                "2025-01-01",
                "2025-06-01",
            ),
            (
                "phase_index_0",
                [
                    {
                        "start_date": "2025-01-01T00:00:00+00:00",
                        "end_date": "2025-03-01T00:00:00+00:00",
                    },
                    {"start_date": "2025-03-01T00:00:00+00:00", "end_date": None},
                ],
                0,
                "2025-01-01",
                "2025-03-01",
            ),
            (
                "phase_index_1",
                [
                    {
                        "start_date": "2025-01-01T00:00:00+00:00",
                        "end_date": "2025-03-01T00:00:00+00:00",
                    },
                    {
                        "start_date": "2025-03-01T00:00:00+00:00",
                        "end_date": "2025-05-01T00:00:00+00:00",
                    },
                ],
                1,
                "2025-03-01",
                "2025-05-01",
            ),
            (
                "out_of_bounds_index",
                [
                    {
                        "start_date": "2025-01-01T00:00:00+00:00",
                        "end_date": "2025-03-01T00:00:00+00:00",
                    },
                ],
                5,
                "2025-01-01",
                "2025-06-01",
            ),
            (
                "negative_index",
                [
                    {
                        "start_date": "2025-01-01T00:00:00+00:00",
                        "end_date": "2025-03-01T00:00:00+00:00",
                    },
                ],
                -1,
                "2025-01-01",
                "2025-06-01",
            ),
        ]
    )
    def test_resolve_date_range(self, _name, phases, phase_index, expected_from_prefix, expected_to_prefix):
        experiment = self._create_experiment_with_phases(phases)
        runner = self._create_query_runner(experiment, phase_index)

        date_range = runner.date_range
        self.assertIsNotNone(date_range.date_from)
        self.assertTrue(date_range.date_from.startswith(expected_from_prefix))

        if expected_to_prefix:
            self.assertIsNotNone(date_range.date_to)
            self.assertTrue(date_range.date_to.startswith(expected_to_prefix))

    def test_open_phase_has_no_end_date(self):
        experiment = self._create_experiment_with_phases(
            [
                {
                    "start_date": "2025-01-01T00:00:00+00:00",
                    "end_date": "2025-03-01T00:00:00+00:00",
                },
                {"start_date": "2025-03-01T00:00:00+00:00", "end_date": None},
            ]
        )
        # Remove experiment end_date to simulate a running experiment
        experiment.end_date = None
        experiment.save()

        runner = self._create_query_runner(experiment, phase_index=1)
        date_range = runner.date_range

        self.assertTrue(date_range.date_from.startswith("2025-03-01"))
        self.assertIsNone(date_range.date_to)
