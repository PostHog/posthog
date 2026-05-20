from datetime import datetime
from zoneinfo import ZoneInfo

from freezegun import freeze_time
from posthog.test.base import _create_event, _create_person, flush_persons_and_events, snapshot_clickhouse_queries

from django.forms.models import model_to_dict
from django.test import override_settings

from parameterized import parameterized

from posthog.schema import ActionsNode, ExperimentEventExposureConfig, ExperimentExposureQuery

from posthog.hogql_queries.experiments import MULTIPLE_VARIANT_KEY
from posthog.hogql_queries.experiments.experiment_exposures_query_runner import ExperimentExposuresQueryRunner
from posthog.hogql_queries.experiments.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest
from posthog.hogql_queries.experiments.test.experiment_query_runner.utils import create_standard_group_test_events
from posthog.models.action.action import Action
from posthog.models.feature_flag import FeatureFlag
from posthog.test.test_journeys import journeys_for


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentExposuresQueryRunner(ExperimentQueryRunnerBaseTest):
    snapshot_replace_all_numbers = True

    def setUp(self):
        super().setUp()
        self.feature_flag = self.create_feature_flag()
        self.experiment = self.create_experiment(
            feature_flag=self.feature_flag,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 7),
        )

    @parameterized.expand([("direct", False), ("precomputed", True)])
    @freeze_time("2024-01-07T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_exposure_query_returns_correct_timeseries(self, _name, use_precomputation):
        self._setup_precomputation_test(use_precomputation)
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

        self._save_experiment_with_precomputation(self.experiment, use_precomputation)

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

    @parameterized.expand([("direct", False), ("precomputed", True)])
    @freeze_time("2024-01-07T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_exposure_query_counts_users_only_on_first_exposure(self, _name, use_precomputation):
        self._setup_precomputation_test(use_precomputation)
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

        self._save_experiment_with_precomputation(self.experiment, use_precomputation)

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

    @parameterized.expand([("direct", False), ("precomputed", True)])
    @freeze_time("2024-01-07T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_exposure_query_filters_test_accounts(self, _name, use_precomputation):
        self._setup_precomputation_test(use_precomputation)
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
        if use_precomputation:
            self._enable_precomputation()
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
        if use_precomputation:
            self._clean_preaggregation_data()
            self._enable_precomputation()
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
            ("pageview_direct", "$pageview", False),
            ("pageview_precomputed", "$pageview", True),
            ("feature_flag_called_direct", "$feature_flag_called", False),
            ("feature_flag_called_precomputed", "$feature_flag_called", True),
        ]
    )
    @freeze_time("2024-01-07T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_exposure_query_with_custom_exposure(self, _name, exposure_event, use_precomputation):
        self._setup_precomputation_test(use_precomputation)
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
        if use_precomputation:
            self._enable_precomputation()
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

    @parameterized.expand([("direct", False), ("precomputed", True)])
    @freeze_time("2024-01-07T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_exposure_query_without_feature_flag_property(self, _name, use_precomputation):
        self._setup_precomputation_test(use_precomputation)
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

        self._save_experiment_with_precomputation(self.experiment, use_precomputation)

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

    @parameterized.expand([("direct", False), ("precomputed", True)])
    @freeze_time("2024-01-07T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_exposure_query_with_multiple_variant_exposures(self, _name, use_precomputation):
        self._setup_precomputation_test(use_precomputation)
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

        self._save_experiment_with_precomputation(self.experiment, use_precomputation)

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

    @parameterized.expand([("direct", False), ("precomputed", True)])
    @freeze_time("2024-01-07T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_exposure_query_using_group_aggregation(self, _name, use_precomputation):
        self._setup_precomputation_test(use_precomputation)
        self.experiment.start_date = datetime(2024, 1, 1).replace(tzinfo=ZoneInfo("UTC"))
        self.experiment.end_date = datetime(2024, 1, 28).replace(tzinfo=ZoneInfo("UTC"))
        if use_precomputation:
            self._enable_precomputation()
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

    @parameterized.expand([("direct", False), ("precomputed", True)])
    @freeze_time("2024-01-07T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_exposure_query_multiple_variant_handling_first_seen(self, _name, use_precomputation):
        self._setup_precomputation_test(use_precomputation)
        ff_property = f"$feature/{self.feature_flag.key}"

        # Set the experiment to use first_seen handling for multiple variants
        self.experiment.exposure_criteria = {"multiple_variant_handling": "first_seen"}
        if use_precomputation:
            self._enable_precomputation()
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

    @parameterized.expand([("direct", False), ("precomputed", True)])
    @freeze_time("2024-01-07T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_exposure_query_with_action_as_exposure_criteria(self, _name, use_precomputation):
        self._setup_precomputation_test(use_precomputation)
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
        if use_precomputation:
            self._enable_precomputation()
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

    @parameterized.expand([("direct", False), ("precomputed", True)])
    @freeze_time("2024-01-07T12:00:00Z")
    def test_srm_calculation_with_balanced_distribution(self, _name, use_precomputation):
        self._setup_precomputation_test(use_precomputation)
        ff_property = f"$feature/{self.feature_flag.key}"

        # Create balanced exposures (50 control, 50 test for 50/50 split)
        journeys = {}
        for i in range(50):
            journeys[f"user_control_{i}"] = [
                {
                    "event": "$feature_flag_called",
                    "timestamp": "2024-01-02",
                    "properties": {
                        "$feature_flag_response": "control",
                        ff_property: "control",
                        "$feature_flag": self.feature_flag.key,
                    },
                },
            ]
            journeys[f"user_test_{i}"] = [
                {
                    "event": "$feature_flag_called",
                    "timestamp": "2024-01-02",
                    "properties": {
                        "$feature_flag_response": "test",
                        ff_property: "test",
                        "$feature_flag": self.feature_flag.key,
                    },
                },
            ]

        journeys_for(journeys, self.team)
        flush_persons_and_events()

        self._save_experiment_with_precomputation(self.experiment, use_precomputation)

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

        self.assertIsNotNone(response.sample_ratio_mismatch)

        # With perfectly balanced distribution, p-value should be 1.0
        self.assertEqual(response.sample_ratio_mismatch.p_value, 1.0)

        # Expected counts should match observed for 50/50 split
        self.assertEqual(response.sample_ratio_mismatch.expected["control"], 50.0)
        self.assertEqual(response.sample_ratio_mismatch.expected["test"], 50.0)

    @parameterized.expand([("direct", False), ("precomputed", True)])
    @freeze_time("2024-01-07T12:00:00Z")
    def test_srm_calculation_detects_significant_mismatch(self, _name, use_precomputation):
        self._setup_precomputation_test(use_precomputation)
        ff_property = f"$feature/{self.feature_flag.key}"

        # Create highly imbalanced exposures (90 control, 10 test for 50/50 split)
        # This should trigger SRM detection
        journeys = {}
        for i in range(90):
            journeys[f"user_control_{i}"] = [
                {
                    "event": "$feature_flag_called",
                    "timestamp": "2024-01-02",
                    "properties": {
                        "$feature_flag_response": "control",
                        ff_property: "control",
                        "$feature_flag": self.feature_flag.key,
                    },
                },
            ]

        for i in range(10):
            journeys[f"user_test_{i}"] = [
                {
                    "event": "$feature_flag_called",
                    "timestamp": "2024-01-02",
                    "properties": {
                        "$feature_flag_response": "test",
                        ff_property: "test",
                        "$feature_flag": self.feature_flag.key,
                    },
                },
            ]

        journeys_for(journeys, self.team)
        flush_persons_and_events()

        self._save_experiment_with_precomputation(self.experiment, use_precomputation)

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

        self.assertIsNotNone(response.sample_ratio_mismatch)

        # With 90/10 split on a 50/50 expected, p-value should be very low
        # (well below the 0.001 threshold for SRM detection)
        self.assertLess(response.sample_ratio_mismatch.p_value, 0.001)

        # Expected counts should be 50/50 of total (100)
        self.assertEqual(response.sample_ratio_mismatch.expected["control"], 50.0)
        self.assertEqual(response.sample_ratio_mismatch.expected["test"], 50.0)

    @parameterized.expand([("direct", False), ("precomputed", True)])
    @freeze_time("2024-01-07T12:00:00Z")
    def test_srm_returns_none_when_insufficient_samples(self, _name, use_precomputation):
        self._setup_precomputation_test(use_precomputation)
        ff_property = f"$feature/{self.feature_flag.key}"

        journeys = {}
        for i in range(40):
            journeys[f"user_control_{i}"] = [
                {
                    "event": "$feature_flag_called",
                    "timestamp": "2024-01-02",
                    "properties": {
                        "$feature_flag_response": "control",
                        ff_property: "control",
                        "$feature_flag": self.feature_flag.key,
                    },
                },
            ]
            journeys[f"user_test_{i}"] = [
                {
                    "event": "$feature_flag_called",
                    "timestamp": "2024-01-02",
                    "properties": {
                        "$feature_flag_response": "test",
                        ff_property: "test",
                        "$feature_flag": self.feature_flag.key,
                    },
                },
            ]

        journeys_for(journeys, self.team)
        flush_persons_and_events()

        self._save_experiment_with_precomputation(self.experiment, use_precomputation)

        query = ExperimentExposureQuery(
            kind="ExperimentExposureQuery",
            experiment_id=self.experiment.id,
            experiment_name=self.experiment.name,
            feature_flag=model_to_dict(self.feature_flag),
            start_date=self.experiment.start_date.isoformat(),
            end_date=self.experiment.end_date.isoformat(),
            exposure_criteria=self.experiment.exposure_criteria,
        )

        response = ExperimentExposuresQueryRunner(team=self.team, query=query).calculate()

        # 80 total exposures < 100 minimum
        self.assertEqual(response.total_exposures["control"], 40)
        self.assertEqual(response.total_exposures["test"], 40)
        self.assertIsNone(response.sample_ratio_mismatch)

    def test_srm_calculation_adjusts_for_holdout(self):
        """SRM calculation should adjust expected percentages when holdout is present"""
        holdout_dict = {
            "id": 123,
            "name": "Test Holdout",
            "filters": [{"properties": [], "rollout_percentage": 20}],
        }

        query = ExperimentExposureQuery(
            kind="ExperimentExposureQuery",
            experiment_id=self.experiment.id,
            experiment_name=self.experiment.name,
            feature_flag=model_to_dict(self.feature_flag),
            holdout=holdout_dict,
            start_date=self.experiment.start_date.isoformat(),
            end_date=self.experiment.end_date.isoformat(),
            exposure_criteria=self.experiment.exposure_criteria,
        )

        runner = ExperimentExposuresQueryRunner(team=self.team, query=query)

        # Note: holdout.id is a float in schema, so key becomes "holdout-123.0"
        assert query.holdout is not None
        holdout_key = f"holdout-{query.holdout.id}"

        # Directly test _calculate_srm with holdout-adjusted data
        # 20% holdout means control/test share remaining 80% → 40% each
        total_exposures = {holdout_key: 20, "control": 40, "test": 40}

        result = runner._calculate_srm(total_exposures)

        assert result is not None
        # With 20% holdout, expected is: holdout=20, control=40, test=40 of 100
        self.assertEqual(result.expected[holdout_key], 20.0)
        self.assertEqual(result.expected["control"], 40.0)
        self.assertEqual(result.expected["test"], 40.0)
        # Perfectly balanced should have p-value = 1.0
        self.assertEqual(result.p_value, 1.0)

    def test_srm_excludes_variant_with_zero_rollout_percentage(self):
        """SRM should exclude variants with 0% rollout from calculation"""
        # Create feature flag with 3 variants: control 50%, test 50%, disabled 0%
        feature_flag_with_disabled = FeatureFlag.objects.create(
            name="Test flag with disabled variant",
            key="test-flag-disabled",
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                        {"key": "disabled", "rollout_percentage": 0},
                    ]
                },
            },
            created_by=self.user,
        )

        query = ExperimentExposureQuery(
            kind="ExperimentExposureQuery",
            experiment_id=self.experiment.id,
            experiment_name=self.experiment.name,
            feature_flag=model_to_dict(feature_flag_with_disabled),
            start_date=self.experiment.start_date.isoformat(),
            end_date=self.experiment.end_date.isoformat(),
            exposure_criteria=self.experiment.exposure_criteria,
        )

        runner = ExperimentExposuresQueryRunner(team=self.team, query=query)
        # disabled variant has 0% rollout, so in practice would have 0 samples
        total_exposures = {"control": 50, "test": 50}

        result = runner._calculate_srm(total_exposures)

        assert result is not None
        # Only control and test should be in expected
        self.assertEqual(len(result.expected), 2)
        self.assertIn("control", result.expected)
        self.assertIn("test", result.expected)
        # Balanced 50/50 should have p-value = 1.0
        self.assertEqual(result.p_value, 1.0)

    def test_srm_with_zero_observed_samples(self):
        """SRM should handle variant with 0 observed samples but >0 expected"""
        query = ExperimentExposureQuery(
            kind="ExperimentExposureQuery",
            experiment_id=self.experiment.id,
            experiment_name=self.experiment.name,
            feature_flag=model_to_dict(self.feature_flag),
            start_date=self.experiment.start_date.isoformat(),
            end_date=self.experiment.end_date.isoformat(),
            exposure_criteria=self.experiment.exposure_criteria,
        )

        runner = ExperimentExposuresQueryRunner(team=self.team, query=query)
        # test variant has 0 samples but 50% expected rollout
        total_exposures = {"control": 100, "test": 0}

        result = runner._calculate_srm(total_exposures)

        assert result is not None
        # Should detect severe mismatch (100/0 vs expected 50/50)
        self.assertLess(result.p_value, 0.001)

    def test_srm_handles_zero_rollout_variant_with_observed_samples(self):
        """
        Test that SRM calculation handles the case where a 0% rollout variant
        has observed samples in the data (edge case/data quality issue).

        This reproduces the bug where scipy.chisquare() fails due to
        sum(observed) ≠ sum(expected) tolerance error.
        """
        # Create feature flag with a disabled variant (0% rollout)
        feature_flag = FeatureFlag.objects.create(
            name="Test flag with disabled variant",
            key="test-flag-with-disabled",
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                        {"key": "disabled", "rollout_percentage": 0},  # 0% rollout
                    ]
                },
            },
            created_by=self.user,
        )

        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 10),
        )

        query = ExperimentExposureQuery(
            kind="ExperimentExposureQuery",
            experiment_id=experiment.id,
            experiment_name=experiment.name,
            feature_flag=model_to_dict(feature_flag),
            start_date=experiment.start_date.isoformat(),
            end_date=experiment.end_date.isoformat(),
            exposure_criteria=experiment.exposure_criteria,
        )

        runner = ExperimentExposuresQueryRunner(team=self.team, query=query)

        # THE BUG SCENARIO:
        # Disabled variant has 0% rollout but somehow has observed samples
        # This can happen due to:
        # - Race conditions during feature flag updates
        # - Data quality issues
        # - Bucketing edge cases
        total_exposures = {
            "control": 50,
            "test": 50,
            "disabled": 1,  # 0% rollout variant with 1 sample!
        }

        # Without fix: This raises ValueError from scipy.chisquare
        # With fix: Should handle gracefully by excluding disabled from total
        result = runner._calculate_srm(total_exposures)

        # Should successfully calculate SRM for control and test only
        self.assertIsNotNone(result)
        assert result is not None  # for mypy
        self.assertIsNotNone(result.p_value)

        # Expected counts should only include control and test
        self.assertEqual(len(result.expected), 2)
        self.assertIn("control", result.expected)
        self.assertIn("test", result.expected)
        self.assertNotIn("disabled", result.expected)

        # Expected should be calculated from 100 total (excluding disabled)
        # Not 101 total (including disabled)
        self.assertAlmostEqual(result.expected["control"], 50.0, places=1)
        self.assertAlmostEqual(result.expected["test"], 50.0, places=1)

        # P-value should be 1.0 (perfect match after excluding disabled)
        self.assertAlmostEqual(result.p_value, 1.0, places=2)

    def test_srm_handles_variant_with_zero_exposures_missing_from_total(self):
        """
        Test that SRM calculation handles the case where a variant with non-zero
        rollout percentage has zero exposures and is therefore missing from
        total_exposures entirely.

        This reproduces the bug where scipy.chisquare() fails with:
        ValueError: sum of observed frequencies must agree with sum of expected frequencies
        """
        # Create feature flag with 3 variants
        feature_flag = FeatureFlag.objects.create(
            name="Test flag with 3 variants",
            key="test-flag-three-variants",
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 45},
                        {"key": "test", "rollout_percentage": 45},
                        {"key": "variant_c", "rollout_percentage": 10},
                    ]
                },
            },
            created_by=self.user,
        )

        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 10),
        )

        query = ExperimentExposureQuery(
            kind="ExperimentExposureQuery",
            experiment_id=experiment.id,
            experiment_name=experiment.name,
            feature_flag=model_to_dict(feature_flag),
            start_date=experiment.start_date.isoformat(),
            end_date=experiment.end_date.isoformat(),
            exposure_criteria=experiment.exposure_criteria,
        )

        runner = ExperimentExposuresQueryRunner(team=self.team, query=query)

        # THE BUG SCENARIO:
        # variant_c has 10% rollout but 0 exposures, so it's missing from total_exposures
        # Without fix: sum(observed)=150, sum(expected)=135 → 11.1% mismatch → ValueError
        total_exposures = {
            "control": 80,
            "test": 70,
            # "variant_c" is missing because it has 0 exposures!
        }

        result = runner._calculate_srm(total_exposures)

        self.assertIsNotNone(result)
        assert result is not None  # for mypy

        # All 3 variants should be in expected (including variant_c with 0 observed)
        self.assertEqual(len(result.expected), 3)
        self.assertIn("control", result.expected)
        self.assertIn("test", result.expected)
        self.assertIn("variant_c", result.expected)

        # Expected should be based on 150 total (80+70+0) distributed by rollout %
        self.assertAlmostEqual(result.expected["control"], 150 * 0.45, places=1)  # 67.5
        self.assertAlmostEqual(result.expected["test"], 150 * 0.45, places=1)  # 67.5
        self.assertAlmostEqual(result.expected["variant_c"], 150 * 0.10, places=1)  # 15.0

        # Should detect mismatch since variant_c has 0 observed but 15 expected
        self.assertLess(result.p_value, 0.01)

    def test_bias_risk_skipped_when_experiment_has_ended(self):
        # Shipping a variant rewrites the flag to 100/0 — that uneven post-ship split
        # plus historical $multiple exposures would otherwise produce a false positive.
        feature_flag = FeatureFlag.objects.create(
            name="Test flag (post-ship)",
            key="test-bias-stopped",
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 100},
                        {"key": "test", "rollout_percentage": 0},
                    ]
                },
            },
            created_by=self.user,
        )
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 7),
        )

        total_exposures = {"control": 800, "test": 200, MULTIPLE_VARIANT_KEY: 20}

        ended_query = ExperimentExposureQuery(
            kind="ExperimentExposureQuery",
            experiment_id=experiment.id,
            experiment_name=experiment.name,
            feature_flag=model_to_dict(feature_flag),
            start_date=experiment.start_date.isoformat(),
            end_date=experiment.end_date.isoformat(),
            exposure_criteria=experiment.exposure_criteria,
        )
        ended_runner = ExperimentExposuresQueryRunner(team=self.team, query=ended_query)
        self.assertIsNone(ended_runner._evaluate_bias_risk(total_exposures))

        running_query = ExperimentExposureQuery(
            kind="ExperimentExposureQuery",
            experiment_id=experiment.id,
            experiment_name=experiment.name,
            feature_flag=model_to_dict(feature_flag),
            start_date=experiment.start_date.isoformat(),
            end_date=None,
            exposure_criteria=experiment.exposure_criteria,
        )
        running_runner = ExperimentExposuresQueryRunner(team=self.team, query=running_query)
        risk = running_runner._evaluate_bias_risk(total_exposures)
        assert risk is not None
        self.assertGreater(risk.multiple_variant_percentage, 0)
