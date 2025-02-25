from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.test import override_settings
from freezegun import freeze_time
from django.utils import timezone

from posthog.hogql_queries.experiments.experiment_exposures_query_runner import ExperimentExposuresQueryRunner
from posthog.models.experiment import Experiment
from posthog.models.feature_flag import FeatureFlag
from posthog.schema import ExperimentEventExposureConfig, ExperimentExposureQuery
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
from posthog.test.test_journeys import journeys_for


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentExposuresQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def create_feature_flag(self, key="test-experiment"):
        return FeatureFlag.objects.create(
            name=f"Test experiment flag: {key}",
            key=key,
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

    def create_experiment(
        self,
        name="test-experiment",
        feature_flag=None,
        start_date=None,
        end_date=None,
    ):
        if feature_flag is None:
            feature_flag = self.create_feature_flag(name)
        if start_date is None:
            start_date = timezone.now()
        if end_date is None:
            end_date = timezone.now() + timedelta(days=14)

        # Only make timezone aware if not already aware
        if timezone.is_naive(start_date):
            start_date = timezone.make_aware(start_date)
        if timezone.is_naive(end_date):
            end_date = timezone.make_aware(end_date)

        return Experiment.objects.create(
            name=name,
            team=self.team,
            feature_flag=feature_flag,
            start_date=start_date,
            end_date=end_date,
            exposure_criteria=None,
        )

    def setUp(self):
        super().setUp()
        self.feature_flag = self.create_feature_flag()
        self.experiment = self.create_experiment(
            feature_flag=self.feature_flag,
            start_date=datetime(2024, 1, 1).replace(tzinfo=ZoneInfo("UTC")),
            end_date=datetime(2024, 1, 7).replace(tzinfo=ZoneInfo("UTC")),
        )

    @freeze_time("2024-01-07T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_exposure_query_returns_correct_timeseries(self):
        ff_property = f"$feature/{self.feature_flag.key}"

        # Create test data using journeys
        journeys_for(
            {
                "user_control_1": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
                "user_control_2": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
                "user_control_3": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-03",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
                "user_control_4": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-03",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
                "user_test_1": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
                "user_test_2": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
                "user_test_3": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
                "user_test_4": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-03",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
                "user_test_5": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-03",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        query = ExperimentExposureQuery(
            kind="ExperimentExposureQuery",
            experiment_id=self.experiment.id,
        )

        query_runner = ExperimentExposuresQueryRunner(
            team=self.team,
            query=query,
        )

        response = query_runner.calculate()

        self.assertEqual(len(response.timeseries), 2)  # Two variants with data

        control_series = next(series for series in response.timeseries if series.variant == "control")
        test_series = next(series for series in response.timeseries if series.variant == "test")

        # Daily cumulative exposures for control variant:
        # Day 0 (Jan 1): 0 exposures
        # Day 1 (Jan 2): 2 new users exposed
        # Day 2 (Jan 3): 2 more users exposed, total 4
        # Days 3-6: No new exposures, remains at 4
        self.assertEqual(control_series.exposure_counts, [0, 2, 4, 4, 4, 4, 4])
        self.assertEqual(len(control_series.days), 7)

        # Daily cumulative exposures for test variant:
        # Day 0 (Jan 1): 0 exposures
        # Day 1 (Jan 2): 3 new users exposed
        # Day 2 (Jan 3): 2 more users exposed, total 5
        # Days 3-6: No new exposures, remains at 5
        self.assertEqual(test_series.exposure_counts, [0, 3, 5, 5, 5, 5, 5])
        self.assertEqual(len(test_series.days), 7)

        self.assertEqual(response.total_exposures["control"], 4)
        self.assertEqual(response.total_exposures["test"], 5)

    @freeze_time("2024-01-07T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_exposure_query_counts_users_only_on_first_exposure(self):
        ff_property = f"$feature/{self.feature_flag.key}"

        journeys_for(
            {
                "user_control_1": [
                    # First exposure on Jan 2
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                    # Second exposure on Jan 3 - should not be counted
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-03",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
                "user_test_1": [
                    # First exposure on Jan 2
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                    # Later exposures on Jan 3 and 4 - should not be counted
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-03",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-04",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
                "user_test_2": [
                    # Only exposure on Jan 3
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-03",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        query = ExperimentExposureQuery(
            kind="ExperimentExposureQuery",
            experiment_id=self.experiment.id,
        )

        query_runner = ExperimentExposuresQueryRunner(
            team=self.team,
            query=query,
        )

        response = query_runner.calculate()

        control_series = next(series for series in response.timeseries if series.variant == "control")
        test_series = next(series for series in response.timeseries if series.variant == "test")

        # Daily cumulative exposures for control variant:
        # Day 0 (Jan 1): 0 exposures
        # Day 1 (Jan 2): 1 new user exposed
        # Days 2-6: No new exposures (second exposure of user_control_1 not counted)
        self.assertEqual(control_series.exposure_counts, [0, 1, 1, 1, 1, 1, 1])

        # Daily cumulative exposures for test variant:
        # Day 0 (Jan 1): 0 exposures
        # Day 1 (Jan 2): 1 new user exposed
        # Day 2 (Jan 3): 1 more user exposed (user_test_2), total 2
        # Days 3-6: No new exposures (additional exposures of user_test_1 not counted)
        self.assertEqual(test_series.exposure_counts, [0, 1, 2, 2, 2, 2, 2])

        self.assertEqual(response.total_exposures["control"], 1)
        self.assertEqual(response.total_exposures["test"], 2)

    @freeze_time("2024-01-07T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_exposure_query_filters_test_accounts(self):
        ff_property = f"$feature/{self.feature_flag.key}"

        _create_person(
            distinct_ids=["user_internal_1"],
            properties={
                "email": "test@posthog.com",
            },
            team=self.team,
        )

        # Extraneous event that's filtered by the internal filter
        _create_event(
            distinct_id="user_internal_1",
            event="$feature_flag_called",
            timestamp="2024-01-05",
            properties={
                "$feature_flag_response": "test",
                ff_property: "test",
                "$feature_flag": self.feature_flag.key,
            },
            team=self.team,
        )

        # Create test data using journeys
        journeys_for(
            {
                "user_control_1": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
                "user_control_2": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
                "user_control_3": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-03",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
                "user_control_4": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-03",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
                "user_test_1": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
                "user_test_2": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
                "user_test_3": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
                "user_test_4": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-03",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
                "user_test_5": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-03",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        self.experiment.exposure_criteria = {"filterTestAccounts": True}
        self.experiment.save()

        self.team.test_account_filters = [
            {
                "key": "email",
                "value": "@posthog.com",
                "operator": "not_icontains",
                "type": "person",
            }
        ]
        self.team.save()

        query = ExperimentExposureQuery(
            kind="ExperimentExposureQuery",
            experiment_id=self.experiment.id,
        )
        query_runner = ExperimentExposuresQueryRunner(
            team=self.team,
            query=query,
        )
        response = query_runner.calculate()

        self.assertEqual(len(response.timeseries), 2)

        self.assertEqual(response.total_exposures["control"], 4)
        self.assertEqual(response.total_exposures["test"], 5)

        # Run again with filterTestAccounts set to False
        self.experiment.exposure_criteria = {"filterTestAccounts": False}
        self.experiment.save()

        query = ExperimentExposureQuery(
            kind="ExperimentExposureQuery",
            experiment_id=self.experiment.id,
        )
        query_runner = ExperimentExposuresQueryRunner(
            team=self.team,
            query=query,
        )
        response = query_runner.calculate()

        self.assertEqual(len(response.timeseries), 2)
        self.assertEqual(response.total_exposures["control"], 4)
        self.assertEqual(response.total_exposures["test"], 6)

    @freeze_time("2024-01-07T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_exposure_query_with_custom_exposure(self):
        ff_property = f"$feature/{self.feature_flag.key}"

        # Create test data using journeys
        journeys_for(
            {
                "user_control_1": [
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-02",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                ],
                "user_control_2": [
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-02",
                        "properties": {
                            ff_property: "control",
                        },
                    },
                ],
                "user_control_3": [
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-03",
                        "properties": {ff_property: "control", "plan": "pro"},
                    },
                ],
                "user_control_4": [
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-03",
                        "properties": {ff_property: "control", "plan": "free"},
                    },
                ],
                "user_test_1": [
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-02",
                        "properties": {
                            ff_property: "test",
                        },
                    },
                ],
                "user_test_2": [
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-02",
                        "properties": {
                            ff_property: "test",
                        },
                    },
                ],
                "user_test_3": [
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-02",
                        "properties": {
                            ff_property: "test",
                        },
                    },
                ],
                "user_test_4": [
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-03",
                        "properties": {
                            ff_property: "test",
                        },
                    },
                ],
                "user_test_5": [
                    {
                        "event": "$pageview",
                        "timestamp": "2024-01-03",
                        "properties": {
                            ff_property: "test",
                        },
                    },
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        exposure_config = ExperimentEventExposureConfig(
            event="$pageview",
            properties=[
                {"key": "plan", "operator": "is_not", "value": "free", "type": "event"},
            ],
        )
        self.experiment.exposure_criteria = {
            "exposure_config": exposure_config.model_dump(mode="json"),
        }
        self.experiment.save()

        query = ExperimentExposureQuery(
            kind="ExperimentExposureQuery",
            experiment_id=self.experiment.id,
        )
        query_runner = ExperimentExposuresQueryRunner(
            team=self.team,
            query=query,
        )
        response = query_runner.calculate()

        self.assertEqual(len(response.timeseries), 2)

        self.assertEqual(response.total_exposures["control"], 3)
        self.assertEqual(response.total_exposures["test"], 5)

    @freeze_time("2024-01-07T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_exposure_query_invalid_feature_flag_property(self):
        ff_property = f"$feature/{self.feature_flag.key}"

        # Create test data using journeys
        journeys_for(
            {
                "user_control_1": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
                "user_control_2": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
                "user_control_3": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-03",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "",  # Intentionally empty
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
                "user_control_4": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-03",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
                "user_test_1": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
                "user_test_2": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
                "user_test_3": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
                "user_test_4": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-03",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
                "user_test_5": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-03",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        query = ExperimentExposureQuery(
            kind="ExperimentExposureQuery",
            experiment_id=self.experiment.id,
        )
        query_runner = ExperimentExposuresQueryRunner(
            team=self.team,
            query=query,
        )
        response = query_runner.calculate()

        self.assertEqual(len(response.timeseries), 2)

        self.assertEqual(response.total_exposures["control"], 3)
        self.assertEqual(response.total_exposures["test"], 5)
