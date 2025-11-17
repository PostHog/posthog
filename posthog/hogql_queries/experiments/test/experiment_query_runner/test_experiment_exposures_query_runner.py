from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)

from django.forms.models import model_to_dict
from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.schema import ExperimentEventExposureConfig, ExperimentExposureQuery

from posthog.hogql_queries.experiments import MULTIPLE_VARIANT_KEY
from posthog.hogql_queries.experiments.experiment_exposures_query_runner import ExperimentExposuresQueryRunner
from posthog.hogql_queries.experiments.test.experiment_query_runner.utils import create_standard_group_test_events
from posthog.models.experiment import Experiment
from posthog.models.feature_flag import FeatureFlag
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
            experiment_name=self.experiment.name,
            feature_flag=model_to_dict(self.feature_flag),
            holdout=model_to_dict(self.experiment.holdout) if self.experiment.holdout else None,
            start_date=self.experiment.start_date.isoformat() if self.experiment.start_date else None,
            end_date=self.experiment.end_date.isoformat() if self.experiment.end_date else None,
            exposure_criteria=self.experiment.exposure_criteria,
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
            experiment_name=self.experiment.name,
            feature_flag=model_to_dict(self.feature_flag),
            holdout=model_to_dict(self.experiment.holdout) if self.experiment.holdout else None,
            start_date=self.experiment.start_date.isoformat() if self.experiment.start_date else None,
            end_date=self.experiment.end_date.isoformat() if self.experiment.end_date else None,
            exposure_criteria=self.experiment.exposure_criteria,
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
            experiment_name=self.experiment.name,
            feature_flag=model_to_dict(self.feature_flag),
            holdout=model_to_dict(self.experiment.holdout) if self.experiment.holdout else None,
            start_date=self.experiment.start_date.isoformat() if self.experiment.start_date else None,
            end_date=self.experiment.end_date.isoformat() if self.experiment.end_date else None,
            exposure_criteria=self.experiment.exposure_criteria,
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
            experiment_name=self.experiment.name,
            feature_flag=model_to_dict(self.feature_flag),
            holdout=model_to_dict(self.experiment.holdout) if self.experiment.holdout else None,
            start_date=self.experiment.start_date.isoformat() if self.experiment.start_date else None,
            end_date=self.experiment.end_date.isoformat() if self.experiment.end_date else None,
            exposure_criteria=self.experiment.exposure_criteria,
        )
        query_runner = ExperimentExposuresQueryRunner(
            team=self.team,
            query=query,
        )
        response = query_runner.calculate()

        self.assertEqual(len(response.timeseries), 2)
        self.assertEqual(response.total_exposures["control"], 4)
        self.assertEqual(response.total_exposures["test"], 6)

    @parameterized.expand(
        [
            "$pageview",
            "$feature_flag_called",
        ]
    )
    @freeze_time("2024-01-07T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_exposure_query_with_custom_exposure(self, exposure_event):
        if exposure_event == "$feature_flag_called":
            ff_property = f"$feature_flag_response"
            add_feature_flag_property = True
        else:
            ff_property = f"$feature/{self.feature_flag.key}"
            add_feature_flag_property = False

        def _generate_properties(variant: str):
            properties = {ff_property: variant}
            if add_feature_flag_property:
                properties["$feature_flag"] = self.feature_flag.key
            return properties

        # Create test data using journeys
        journeys_for(
            {
                "user_control_1": [
                    {
                        "event": exposure_event,
                        "timestamp": "2024-01-02",
                        "properties": _generate_properties("control"),
                    },
                ],
                "user_control_2": [
                    {
                        "event": exposure_event,
                        "timestamp": "2024-01-02",
                        "properties": _generate_properties("control"),
                    },
                ],
                "user_control_3": [
                    {
                        "event": exposure_event,
                        "timestamp": "2024-01-03",
                        "properties": _generate_properties("control"),
                    },
                ],
                "user_control_4": [
                    {
                        "event": exposure_event,
                        "timestamp": "2024-01-03",
                        "properties": _generate_properties("control"),
                    },
                ],
                "user_test_1": [
                    {
                        "event": exposure_event,
                        "timestamp": "2024-01-02",
                        "properties": _generate_properties("test"),
                    },
                ],
                "user_test_2": [
                    {
                        "event": exposure_event,
                        "timestamp": "2024-01-02",
                        "properties": _generate_properties("test"),
                    },
                ],
                "user_test_3": [
                    {
                        "event": exposure_event,
                        "timestamp": "2024-01-02",
                        "properties": _generate_properties("test"),
                    },
                ],
                "user_test_4": [
                    {
                        "event": exposure_event,
                        "timestamp": "2024-01-03",
                        "properties": _generate_properties("test"),
                    },
                ],
                "user_test_5": [
                    {
                        "event": exposure_event,
                        "timestamp": "2024-01-03",
                        "properties": _generate_properties("test"),
                    },
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        exposure_config = ExperimentEventExposureConfig(
            event=exposure_event,
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
            experiment_name=self.experiment.name,
            feature_flag=model_to_dict(self.feature_flag),
            holdout=model_to_dict(self.experiment.holdout) if self.experiment.holdout else None,
            start_date=self.experiment.start_date.isoformat() if self.experiment.start_date else None,
            end_date=self.experiment.end_date.isoformat() if self.experiment.end_date else None,
            exposure_criteria=self.experiment.exposure_criteria,
        )
        query_runner = ExperimentExposuresQueryRunner(
            team=self.team,
            query=query,
        )
        response = query_runner.calculate()

        self.assertEqual(len(response.timeseries), 2)

        self.assertEqual(response.total_exposures["control"], 4)
        self.assertEqual(response.total_exposures["test"], 5)

    @freeze_time("2024-01-07T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_exposure_query_without_feature_flag_property(self):
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
                            ff_property: "",  # Intentionally empty, should still be included as some SDKs don't include this
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
            experiment_name=self.experiment.name,
            feature_flag=model_to_dict(self.feature_flag),
            holdout=model_to_dict(self.experiment.holdout) if self.experiment.holdout else None,
            start_date=self.experiment.start_date.isoformat() if self.experiment.start_date else None,
            end_date=self.experiment.end_date.isoformat() if self.experiment.end_date else None,
            exposure_criteria=self.experiment.exposure_criteria,
        )
        query_runner = ExperimentExposuresQueryRunner(
            team=self.team,
            query=query,
        )
        response = query_runner.calculate()

        self.assertEqual(len(response.timeseries), 2)

        self.assertEqual(response.total_exposures["control"], 4)
        self.assertEqual(response.total_exposures["test"], 5)

    @freeze_time("2024-01-07T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_exposure_query_with_multiple_variant_exposures(self):
        ff_property = f"$feature/{self.feature_flag.key}"

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
                # user_test_2 is exposed to both variants and should be put in the multiple variant group
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
            },
            self.team,
        )

        flush_persons_and_events()

        query = ExperimentExposureQuery(
            kind="ExperimentExposureQuery",
            experiment_id=self.experiment.id,
            experiment_name=self.experiment.name,
            feature_flag=model_to_dict(self.feature_flag),
            holdout=model_to_dict(self.experiment.holdout) if self.experiment.holdout else None,
            start_date=self.experiment.start_date.isoformat() if self.experiment.start_date else None,
            end_date=self.experiment.end_date.isoformat() if self.experiment.end_date else None,
            exposure_criteria=self.experiment.exposure_criteria,
        )
        query_runner = ExperimentExposuresQueryRunner(
            team=self.team,
            query=query,
        )
        response = query_runner.calculate()

        self.assertEqual(len(response.timeseries), 3)

        self.assertEqual(response.total_exposures["control"], 2)
        self.assertEqual(response.total_exposures["test"], 1)
        self.assertEqual(response.total_exposures[MULTIPLE_VARIANT_KEY], 1)

    @freeze_time("2024-01-07T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_exposure_query_using_group_aggregation(self):
        self.experiment.start_date = datetime(2024, 1, 1).replace(tzinfo=ZoneInfo("UTC"))
        self.experiment.end_date = datetime(2024, 1, 28).replace(tzinfo=ZoneInfo("UTC"))
        self.experiment.save()

        group_type_index = 0
        self.feature_flag.filters["aggregation_group_type_index"] = group_type_index
        self.feature_flag.save()

        create_standard_group_test_events(self.team, self.feature_flag)

        flush_persons_and_events()

        query = ExperimentExposureQuery(
            kind="ExperimentExposureQuery",
            experiment_id=self.experiment.id,
            experiment_name=self.experiment.name,
            feature_flag=model_to_dict(self.feature_flag),
            holdout=model_to_dict(self.experiment.holdout) if self.experiment.holdout else None,
            start_date=self.experiment.start_date.isoformat() if self.experiment.start_date else None,
            end_date=self.experiment.end_date.isoformat() if self.experiment.end_date else None,
            exposure_criteria=self.experiment.exposure_criteria,
        )
        query_runner = ExperimentExposuresQueryRunner(
            team=self.team,
            query=query,
        )
        response = query_runner.calculate()

        self.assertEqual(response.total_exposures["control"], 2)
        self.assertEqual(response.total_exposures["test"], 3)

    @freeze_time("2024-01-07T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_exposure_query_multiple_variant_handling_first_seen(self):
        ff_property = f"$feature/{self.feature_flag.key}"

        # Set the experiment to use first_seen handling for multiple variants
        self.experiment.exposure_criteria = {"multiple_variant_handling": "first_seen"}
        self.experiment.save()

        journeys_for(
            {
                "user_control_only": [
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
                "user_test_only": [
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
                # User who sees control first, then test (should be counted as control)
                "user_multiple_control_first": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": self.feature_flag.key,
                        },
                    },
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
                # User who sees test first, then control (should be counted as test)
                "user_multiple_test_first": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
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
                            "$feature_flag_response": "control",
                            ff_property: "control",
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
            experiment_name=self.experiment.name,
            feature_flag=model_to_dict(self.feature_flag),
            holdout=model_to_dict(self.experiment.holdout) if self.experiment.holdout else None,
            start_date=self.experiment.start_date.isoformat() if self.experiment.start_date else None,
            end_date=self.experiment.end_date.isoformat() if self.experiment.end_date else None,
            exposure_criteria=self.experiment.exposure_criteria,
        )
        query_runner = ExperimentExposuresQueryRunner(
            team=self.team,
            query=query,
        )
        response = query_runner.calculate()

        # With first_seen handling:
        # - user_control_only: counted in control
        # - user_test_only: counted in test
        # - user_multiple_control_first: counted in control (first seen variant)
        # - user_multiple_test_first: counted in test (first seen variant)
        self.assertEqual(response.total_exposures["control"], 2)  # user_control_only + user_multiple_control_first
        self.assertEqual(response.total_exposures["test"], 2)  # user_test_only + user_multiple_test_first

        # Verify no MULTIPLE_VARIANT_KEY appears in total_exposures for first_seen handling
        self.assertNotIn(MULTIPLE_VARIANT_KEY, response.total_exposures)

    @freeze_time("2024-01-07T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_exposure_query_with_action_as_exposure_criteria(self):
        from posthog.schema import ActionsNode

        from posthog.models.action.action import Action

        # Create an action for purchase events with specific properties
        action = Action.objects.create(
            name="Qualified Purchase",
            team=self.team,
            steps_json=[{"event": "purchase", "properties": [{"key": "plan", "value": "premium", "type": "event"}]}],
        )

        ff_property = f"$feature/{self.feature_flag.key}"

        # Create test data - only premium purchases should count as exposures
        journeys_for(
            {
                "user_control_1": [
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-02",
                        "properties": {ff_property: "control", "plan": "premium"},
                    },
                ],
                "user_control_2": [
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-02",
                        "properties": {ff_property: "control", "plan": "premium"},
                    },
                ],
                "user_control_3": [
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-03",
                        "properties": {ff_property: "control", "plan": "basic"},  # Should NOT count
                    },
                ],
                "user_test_1": [
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-02",
                        "properties": {ff_property: "test", "plan": "premium"},
                    },
                ],
                "user_test_2": [
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-02",
                        "properties": {ff_property: "test", "plan": "premium"},
                    },
                ],
                "user_test_3": [
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-02",
                        "properties": {ff_property: "test", "plan": "premium"},
                    },
                ],
                "user_test_4": [
                    {
                        "event": "purchase",
                        "timestamp": "2024-01-03",
                        "properties": {ff_property: "test", "plan": "basic"},  # Should NOT count
                    },
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        # Set exposure criteria to use the action
        self.experiment.exposure_criteria = {"exposure_config": ActionsNode(id=action.id).model_dump(mode="json")}
        self.experiment.save()

        query = ExperimentExposureQuery(
            kind="ExperimentExposureQuery",
            experiment_id=self.experiment.id,
            experiment_name=self.experiment.name,
            feature_flag=model_to_dict(self.feature_flag),
            start_date=self.experiment.start_date.isoformat(),
            end_date=self.experiment.end_date.isoformat(),
            exposure_criteria=self.experiment.exposure_criteria,
        )

        query_runner = ExperimentExposuresQueryRunner(
            team=self.team,
            query=query,
        )

        response = query_runner.calculate()

        # Only premium purchases should be counted as exposures
        # Control: user_control_1 and user_control_2 (user_control_3 has basic plan)
        # Test: user_test_1, user_test_2, user_test_3 (user_test_4 has basic plan)
        self.assertEqual(response.total_exposures["control"], 2)
        self.assertEqual(response.total_exposures["test"], 3)

        # Verify timeseries data
        control_series = next((s for s in response.timeseries if s.variant == "control"), None)
        test_series = next((s for s in response.timeseries if s.variant == "test"), None)

        assert control_series is not None
        assert test_series is not None

        # All control exposures on 2024-01-02
        self.assertEqual(control_series.exposure_counts[-1], 2)
        # All test exposures on 2024-01-02
        self.assertEqual(test_series.exposure_counts[-1], 3)
