from datetime import datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import _create_event, _create_person, flush_persons_and_events, snapshot_clickhouse_queries

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    ActionsNode,
    EventPropertyFilter,
    EventsNode,
    ExperimentEventExposureConfig,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentQuery,
    FunnelConversionWindowTimeUnit,
    MultipleVariantHandling,
    PropertyOperator,
)

from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
from posthog.hogql_queries.experiments.test.experiment_query_runner.base import ExperimentQueryRunnerBaseTest
from posthog.hogql_queries.experiments.test.experiment_query_runner.utils import create_standard_group_test_events
from posthog.models.action.action import Action
from posthog.models.cohort.cohort import Cohort
from posthog.models.group.util import create_group
from posthog.test.test_journeys import journeys_for
from posthog.test.test_utils import create_group_type_mapping_without_created_at


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentQueryRunner(ExperimentQueryRunnerBaseTest):
    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_includes_date_range(self, name, use_new_query_builder):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag, end_date=datetime(2020, 2, 1, 12, 0, 0))
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase"),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        self.create_standard_test_events(feature_flag)

        # These events are too early to be included
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_early_control_1",
            timestamp="2019-01-01T12:00:00Z",
            properties={
                feature_flag_property: "control",
                "$feature_flag_response": "control",
                "$feature_flag": feature_flag.key,
            },
        )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_early_control_1",
            timestamp="2019-01-02T12:00:00Z",
            properties={
                feature_flag_property: "control",
            },
        )
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_early_test_1",
            timestamp="2019-01-02T12:00:00Z",
            properties={
                feature_flag_property: "test",
                "$feature_flag_response": "test",
                "$feature_flag": feature_flag.key,
            },
        )

        # This user is too late to be included
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_late_control_1",
            timestamp="2021-01-01T12:00:00Z",
            properties={
                feature_flag_property: "control",
                "$feature_flag_response": "control",
                "$feature_flag": feature_flag.key,
            },
        )
        # This purchase event is too late to be included for user in the experiment
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_control_1",
            timestamp="2021-01-02T12:00:00Z",
            properties={
                feature_flag_property: "control",
            },
        )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_test_1",
            timestamp="2021-01-02T12:00:00Z",
            properties={
                feature_flag_property: "test",
            },
        )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)
        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        self.assertEqual(control_variant.sum, 6)
        self.assertEqual(test_variant.sum, 8)
        self.assertEqual(control_variant.number_of_samples, 10)
        self.assertEqual(test_variant.number_of_samples, 10)

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_includes_event_property_filters(self, name, use_new_query_builder):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="purchase",
                properties=[
                    EventPropertyFilter(key="plan", operator=PropertyOperator.IS_NOT, value="pro", type="event"),
                ],
            ),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        self.create_standard_test_events(feature_flag)

        # The exposure will be included but the purchase shouldn't be.
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_early_control_1",
            timestamp="2020-01-04T12:00:00Z",
            properties={
                feature_flag_property: "control",
                "$feature_flag_response": "control",
                "$feature_flag": feature_flag.key,
            },
        )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_early_control_1",
            timestamp="2020-01-05T12:00:00Z",
            properties={
                feature_flag_property: "control",
                "plan": "pro",
            },
        )
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_early_test_1",
            timestamp="2020-01-05T12:00:00Z",
            properties={
                feature_flag_property: "test",
                "$feature_flag_response": "test",
                "$feature_flag": feature_flag.key,
            },
        )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)
        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        self.assertEqual(control_variant.sum, 6)
        self.assertEqual(test_variant.sum, 8)
        self.assertEqual(control_variant.number_of_samples, 11)
        self.assertEqual(test_variant.number_of_samples, 11)

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_using_action(self, name, use_new_query_builder):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}

        action = Action.objects.create(name="purchase", team=self.team, steps_json=[{"event": "purchase"}])
        action.save()

        metric = ExperimentMeanMetric(
            source=ActionsNode(id=action.id),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        self.create_standard_test_events(feature_flag)

        # Extraneous events that shouldn't be included
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id=f"user_random_1",
            timestamp="2020-01-02T12:00:00Z",
        )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id=f"user_random_1",
            timestamp="2020-01-02T12:01:00Z",
        )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id=f"user_random_2",
            timestamp="2020-01-02T12:01:00Z",
        )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)
        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        self.assertEqual(control_variant.sum, 6)
        self.assertEqual(test_variant.sum, 8)
        self.assertEqual(control_variant.number_of_samples, 10)
        self.assertEqual(test_variant.number_of_samples, 10)

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_group_aggregation_mean_metric(self, name, use_new_query_builder):
        feature_flag = self.create_feature_flag()
        feature_flag.filters["aggregation_group_type_index"] = 0
        feature_flag.save()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}

        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase"),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        create_standard_group_test_events(self.team, feature_flag)

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)
        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        self.assertEqual(control_variant.number_of_samples, 2)
        self.assertEqual(test_variant.number_of_samples, 3)
        self.assertEqual(control_variant.sum, 6)
        self.assertEqual(test_variant.sum, 8)

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_group_aggregation_mean_property_sum_metric(self, name, use_new_query_builder):
        feature_flag = self.create_feature_flag()
        feature_flag.filters["aggregation_group_type_index"] = 0
        feature_flag.save()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}

        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase", math=ExperimentMetricMathType.SUM, math_property="amount"),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        create_standard_group_test_events(self.team, feature_flag)

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)
        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        self.assertEqual(control_variant.number_of_samples, 2)
        self.assertEqual(test_variant.number_of_samples, 3)
        self.assertEqual(control_variant.sum, 60)
        self.assertEqual(test_variant.sum, 120)

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_standard_flow_v2_stats(self, name, use_new_query_builder):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        metric = ExperimentMeanMetric(
            source=EventsNode(event="$pageview"),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        journeys_for(
            {
                "user_control_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {"event": "$pageview", "timestamp": "2020-01-03", "properties": {ff_property: "control"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": feature_flag.key,
                        },
                    },
                ],
                "user_control_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag_response": "control",
                            ff_property: "control",
                            "$feature_flag": feature_flag.key,
                        },
                    },
                ],
                "user_test_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-03", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-04", "properties": {ff_property: "test"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": feature_flag.key,
                        },
                    },
                ],
                "user_test_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-03", "properties": {ff_property: "test"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {
                            "$feature_flag_response": "test",
                            ff_property: "test",
                            "$feature_flag": feature_flag.key,
                        },
                    },
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)
        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        self.assertEqual(control_variant.sum, 3)
        self.assertEqual(test_variant.sum, 5)
        self.assertEqual(control_variant.number_of_samples, 2)
        self.assertEqual(test_variant.number_of_samples, 2)

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @snapshot_clickhouse_queries
    def test_query_runner_with_custom_exposure(self, name, use_new_query_builder):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag, start_date=datetime(2020, 1, 1), end_date=datetime(2020, 1, 31)
        )
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}

        feature_flag_property = f"$feature/{feature_flag.key}"

        for variant, purchase_count in [("control", 6), ("test", 8)]:
            for i in range(10):
                _create_person(distinct_ids=[f"user_{variant}_{i}"], team_id=self.team.pk)
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_{variant}_{i}",
                    timestamp="2020-01-02T12:00:00Z",
                    properties={
                        feature_flag_property: variant,
                    },
                )
                if i < purchase_count:
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=f"user_{variant}_{i}",
                        timestamp="2020-01-02T12:01:00Z",
                        properties={feature_flag_property: variant, "amount": 10 if i < 2 else ""},
                    )

        # Extra exposure that should be excluded
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=f"user_extra_1",
            timestamp="2020-01-02T12:00:00Z",
            properties={feature_flag_property: "control", "plan": "free"},
        )

        flush_persons_and_events()

        exposure_config = ExperimentEventExposureConfig(
            event="$pageview",
            properties=[
                EventPropertyFilter(key="plan", operator=PropertyOperator.IS_NOT, value="free", type="event"),
            ],
        )
        experiment.exposure_criteria = {
            "exposure_config": exposure_config.model_dump(mode="json"),
        }
        experiment.save()
        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=ExperimentMeanMetric(
                source=EventsNode(event="purchase"),
            ),
        )

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)
        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        self.assertEqual(control_variant.sum, 6)
        self.assertEqual(test_variant.sum, 8)
        self.assertEqual(control_variant.number_of_samples, 10)
        self.assertEqual(test_variant.number_of_samples, 10)

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @snapshot_clickhouse_queries
    def test_query_runner_with_custom_exposure_without_properties(self, name, use_new_query_builder):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag, start_date=datetime(2020, 1, 1), end_date=datetime(2020, 1, 31)
        )
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}

        feature_flag_property = f"$feature/{feature_flag.key}"

        for variant, purchase_count in [("control", 6), ("test", 8)]:
            for i in range(10):
                _create_person(distinct_ids=[f"user_{variant}_{i}"], team_id=self.team.pk)
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_{variant}_{i}",
                    timestamp="2020-01-02T12:00:00Z",
                    properties={
                        feature_flag_property: variant,
                    },
                )
                if i < purchase_count:
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=f"user_{variant}_{i}",
                        timestamp="2020-01-02T12:01:00Z",
                        properties={feature_flag_property: variant, "amount": 10 if i < 2 else ""},
                    )

        # Extra exposure that should be included
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=f"user_extra_1",
            timestamp="2020-01-02T12:00:00Z",
            properties={feature_flag_property: "control"},
        )

        flush_persons_and_events()

        exposure_config = ExperimentEventExposureConfig(
            event="$pageview",
            properties=[],
        )
        experiment.exposure_criteria = {
            "exposure_config": exposure_config.model_dump(mode="json"),
        }
        experiment.save()
        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=ExperimentMeanMetric(
                source=EventsNode(event="purchase"),
            ),
        )

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)
        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        self.assertEqual(control_variant.sum, 6)
        self.assertEqual(test_variant.sum, 8)
        self.assertEqual(control_variant.number_of_samples, 11)
        self.assertEqual(test_variant.number_of_samples, 10)

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @snapshot_clickhouse_queries
    def test_query_runner_with_custom_exposure_on_feature_flag_called_event(self, name, use_new_query_builder):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag, start_date=datetime(2020, 1, 1), end_date=datetime(2020, 1, 31)
        )
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}

        feature_flag_property = "$feature_flag_response"

        for variant, purchase_count in [("control", 6), ("test", 8)]:
            for i in range(10):
                _create_person(distinct_ids=[f"user_{variant}_{i}"], team_id=self.team.pk)
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"user_{variant}_{i}",
                    timestamp="2020-01-02T12:00:00Z",
                    properties={
                        feature_flag_property: variant,
                        "$feature_flag": feature_flag.key,
                    },
                )
                if i < purchase_count:
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=f"user_{variant}_{i}",
                        timestamp="2020-01-02T12:01:00Z",
                        properties={
                            feature_flag_property: variant,
                            "$feature_flag": feature_flag.key,
                            "amount": 10 if i < 2 else "",
                        },
                    )

        # Extra exposure that should be excluded
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id=f"user_extra_1",
            timestamp="2020-01-02T12:00:00Z",
            properties={
                feature_flag_property: "control",
                "$feature_flag": feature_flag.key,
                "plan": "free",
            },
        )

        flush_persons_and_events()

        exposure_config = ExperimentEventExposureConfig(
            event="$feature_flag_called",
            properties=[
                EventPropertyFilter(key="plan", operator=PropertyOperator.IS_NOT, value="free", type="event"),
            ],
        )
        experiment.exposure_criteria = {
            "exposure_config": exposure_config.model_dump(mode="json"),
        }
        experiment.save()
        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=ExperimentMeanMetric(
                source=EventsNode(event="purchase"),
            ),
        )

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)
        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        self.assertEqual(control_variant.sum, 6)
        self.assertEqual(test_variant.sum, 8)
        self.assertEqual(control_variant.number_of_samples, 10)
        self.assertEqual(test_variant.number_of_samples, 10)

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @snapshot_clickhouse_queries
    def test_query_runner_with_action_as_exposure_criteria(self, name, use_new_query_builder):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag, start_date=datetime(2020, 1, 1), end_date=datetime(2020, 1, 31)
        )
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Create an action for purchase events with specific properties
        action = Action.objects.create(
            name="Qualified Purchase",
            team=self.team,
            steps_json=[{"event": "purchase", "properties": [{"key": "plan", "value": "premium", "type": "event"}]}],
        )
        action.save()

        for variant, purchase_count in [("control", 6), ("test", 8)]:
            for i in range(10):
                _create_person(distinct_ids=[f"user_{variant}_{i}"], team_id=self.team.pk)
                # Create purchase event (exposure candidate)
                if i < purchase_count:
                    # Half with premium plan (matches action), half without (doesn't match)
                    plan = "premium" if i < purchase_count // 2 else "basic"
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=f"user_{variant}_{i}",
                        timestamp="2020-01-02T12:00:00Z",
                        properties={feature_flag_property: variant, "plan": plan},
                    )
                # Create metric event
                if i < purchase_count:
                    _create_event(
                        team=self.team,
                        event="conversion",
                        distinct_id=f"user_{variant}_{i}",
                        timestamp="2020-01-02T12:01:00Z",
                        properties={feature_flag_property: variant},
                    )

        # Extra user who has purchase but doesn't match action criteria (should be excluded from exposure)
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id=f"user_extra_1",
            timestamp="2020-01-02T12:00:00Z",
            properties={feature_flag_property: "control", "plan": "free"},
        )

        flush_persons_and_events()

        # Set exposure criteria to use the action
        experiment.exposure_criteria = {"exposure_config": ActionsNode(id=action.id).model_dump(mode="json")}
        experiment.save()

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=ExperimentMeanMetric(
                source=EventsNode(event="conversion"),
            ),
        )

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)
        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        # Only users with premium plan (matching action) should be counted as exposures
        # Control: 3 users with premium plan (0, 1, 2 out of 6 purchases)
        # Test: 4 users with premium plan (0, 1, 2, 3 out of 8 purchases)
        self.assertEqual(control_variant.sum, 3)
        self.assertEqual(test_variant.sum, 4)
        self.assertEqual(control_variant.number_of_samples, 3)
        self.assertEqual(test_variant.number_of_samples, 4)

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_without_feature_flag_property(self, name, use_new_query_builder):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag, end_date=datetime(2020, 2, 1, 12, 0, 0))
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase"),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        self.create_standard_test_events(feature_flag)

        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_invalid_id",
            timestamp="2020-01-15T12:00:00Z",
            properties={
                # No $feature/<key> property, should still be included as some SDKs don't include this
                "$feature_flag_response": "control",
                "$feature_flag": feature_flag.key,
            },
        )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)
        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        self.assertEqual(control_variant.sum, 6)
        self.assertEqual(test_variant.sum, 8)
        self.assertEqual(control_variant.number_of_samples, 11)
        self.assertEqual(test_variant.number_of_samples, 10)

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_no_exposures(self, name, use_new_query_builder):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}

        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase"),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)
        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        self.assertEqual(control_variant.sum, 0)
        self.assertEqual(test_variant.sum, 0)
        self.assertEqual(control_variant.number_of_samples, 0)
        self.assertEqual(test_variant.number_of_samples, 0)

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_no_variant_exposures(self, name, use_new_query_builder):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}

        feature_flag_property = f"$feature/{feature_flag.key}"

        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase"),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        # No variant events
        for variant, num_users in [("control", 10)]:
            for i in range(num_users):
                _create_person(distinct_ids=[f"user_{variant}_{i}"], team_id=self.team.pk)
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"user_{variant}_{i}",
                    timestamp="2020-01-02T12:00:00Z",
                    properties={
                        feature_flag_property: variant,
                        "$feature_flag_response": variant,
                        "$feature_flag": feature_flag.key,
                    },
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)
        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        self.assertEqual(control_variant.sum, 0)
        self.assertEqual(test_variant.sum, 0)
        self.assertEqual(control_variant.number_of_samples, 10)
        self.assertEqual(test_variant.number_of_samples, 0)

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_no_control_variant(self, name, use_new_query_builder):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}

        feature_flag_property = f"$feature/{feature_flag.key}"

        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase"),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        # No control variant
        for variant, purchase_count in [("test", 8)]:
            for i in range(10):
                _create_person(distinct_ids=[f"user_{variant}_{i}"], team_id=self.team.pk)
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"user_{variant}_{i}",
                    timestamp="2020-01-02T12:00:00Z",
                    properties={
                        feature_flag_property: variant,
                        "$feature_flag_response": variant,
                        "$feature_flag": feature_flag.key,
                    },
                )
                if i < purchase_count:
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=f"user_{variant}_{i}",
                        timestamp="2020-01-02T12:01:00Z",
                        properties={feature_flag_property: variant, "amount": 10 if i < 2 else ""},
                    )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)
        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        self.assertEqual(control_variant.sum, 0)
        self.assertEqual(test_variant.sum, 8)
        self.assertEqual(control_variant.number_of_samples, 0)
        self.assertEqual(test_variant.number_of_samples, 10)

    @parameterized.expand(
        [
            [
                "person_properties",
                {
                    "key": "email",
                    "value": "@posthog.com",
                    "operator": "not_icontains",
                    "type": "person",
                },
                {
                    "control_absolute_exposure": 12,
                    "test_absolute_exposure": 15,
                },
            ],
            [
                "event_properties",
                {
                    "key": "$host",
                    "value": "^(localhost|127\\.0\\.0\\.1)($|:)",
                    "operator": "not_regex",
                    "type": "event",
                },
                {
                    "control_absolute_exposure": 6,
                    "test_absolute_exposure": 6,
                },
            ],
            [
                "feature_flags",
                {
                    "key": "$feature/flag_doesnt_exist",
                    "type": "event",
                    "value": ["test", "control"],
                    "operator": "exact",
                },
                {
                    "control_absolute_exposure": 0,
                    "test_absolute_exposure": 0,
                },
            ],
            [
                "cohort_static",
                {
                    "key": "id",
                    "type": "static-cohort",
                    # value is generated in the test
                    "value": None,
                    "operator": "exact",
                },
                {
                    "control_absolute_exposure": 2,
                    "test_absolute_exposure": 1,
                },
            ],
            [
                "cohort_dynamic",
                {
                    "key": "id",
                    "type": "cohort",
                    # value is generated in the test
                    "value": None,
                    "operator": "exact",
                },
                {
                    "control_absolute_exposure": 12,
                    "test_absolute_exposure": 15,
                },
            ],
            [
                "group",
                {
                    "key": "name",
                    "type": "group",
                    # Value is generated in the test
                    "value": None,
                    "operator": "exact",
                    "group_type_index": 0,
                },
                {
                    "control_absolute_exposure": 8,
                    "test_absolute_exposure": 10,
                },
            ],
            [
                "element",
                {
                    "key": "tag_name",
                    "type": "element",
                    "value": ["button"],
                    "operator": "exact",
                },
                {
                    "control_absolute_exposure": 0,
                    "test_absolute_exposure": 0,
                },
            ],
        ]
    )
    @snapshot_clickhouse_queries
    def test_query_runner_with_internal_filters(self, filter_name: str, filter: dict, expected_results: dict):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag, start_date=datetime(2020, 1, 1), end_date=datetime(2020, 1, 31)
        )
        # Note: This test doesn't need query builder parameterization as it tests the same logic
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": False}

        cohort = None
        if filter_name == "cohort_static":
            cohort = Cohort.objects.create(
                team=self.team,
                name="cohort_static",
                is_static=True,
            )
            filter["value"] = cohort.pk
        elif filter_name == "cohort_dynamic":
            cohort = Cohort.objects.create(
                team=self.team,
                name="cohort_dynamic",
                groups=[
                    {
                        "properties": [
                            {"key": "email", "operator": "not_icontains", "value": "@posthog.com", "type": "person"},
                        ]
                    }
                ],
            )
            filter["value"] = cohort.pk
        elif filter_name == "group":
            create_group_type_mapping_without_created_at(
                team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
            )
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key="my_awesome_group",
                properties={"name": "Test Group"},
            )
            filter["value"] = ["Test Group"]

        self.team.test_account_filters = [filter]
        self.team.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        metric = ExperimentMeanMetric(
            source=EventsNode(event="$pageview"),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.exposure_criteria = {"filterTestAccounts": True}
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        # Populate count events - ensuring we have non-zero values and variance
        # Create pageview events with variance to avoid statistical errors
        for variant, count in [("control", 14), ("test", 16)]:
            for i in range(count):
                # Create different numbers of pageviews per user to ensure variance
                num_pageviews = (i % 4) + 1  # 1, 2, 3, or 4 pageviews per user
                for j in range(num_pageviews):
                    extra_properties = {"$host": "localhost", "$group_0": "my_awesome_group"} if i > 5 else {}
                    # Add some events with button elements for the element filter test
                    if i < 2:  # First 2 events have button element
                        extra_properties["$elements"] = [{"tag_name": "button"}]  # type: ignore
                    # Don't add the feature flag property - this filter is meant to filter out all events
                    _create_event(
                        team=self.team,
                        event="$pageview",
                        distinct_id=f"user_{variant}_{i}",
                        timestamp=datetime(2020, 1, min(i + 4 + j, 30)),  # Pageviews happen after exposure (i+3)
                        properties={feature_flag_property: variant, **extra_properties},
                    )

        # Populate exposure events
        for variant, count in [("control", 14), ("test", 16)]:
            for i in range(count):
                extra_properties = {"$host": "localhost", "$group_0": "my_awesome_group"} if i > 5 else {}
                # Add element properties to exposure events for element filter test
                if i < 2:  # First 2 events have button element
                    extra_properties["$elements"] = [{"tag_name": "button"}]  # type: ignore
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"user_{variant}_{i}",
                    timestamp=datetime(2020, 1, i + 3),
                    properties={
                        "$feature_flag_response": variant,
                        "$feature_flag": feature_flag.key,
                        feature_flag_property: variant,
                        **extra_properties,
                    },
                )

        # Create persons for all users
        # Only give some users @posthog.com emails so they get filtered out
        for variant, count in [("control", 14), ("test", 16)]:
            for i in range(count):
                properties = {}
                # Give @posthog.com emails to specific users that should be filtered out
                if (variant == "control" and i in [3, 6]) or (variant == "test" and i == 2):
                    properties = {"email": f"user_{variant}_{i}@posthog.com"}
                _create_person(
                    team=self.team,
                    distinct_ids=[f"user_{variant}_{i}"],
                    properties=properties,
                )

        flush_persons_and_events()

        if filter_name == "cohort_static" and cohort:
            cohort.insert_users_by_list(["user_control_1", "user_control_2", "user_test_2"])
            self.assertEqual(cohort.people.count(), 3)
        elif filter_name == "cohort_dynamic" and cohort:
            cohort.calculate_people_ch(pending_version=0)

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)

        # Handle cases where filters result in no exposures
        if expected_results["control_absolute_exposure"] == 0 and expected_results["test_absolute_exposure"] == 0:
            result = query_runner.calculate()
            assert result.variant_results is not None
            control_result = result.baseline
            assert control_result is not None
            test_result = result.variant_results[0]
            assert test_result is not None
            self.assertEqual(control_result.number_of_samples, 0)
            self.assertEqual(test_result.number_of_samples, 0)
            self.assertEqual(control_result.sum, 0)
            self.assertEqual(test_result.sum, 0)

        else:
            result = query_runner.calculate()
            assert result.variant_results is not None
            control_result = result.baseline
            assert control_result is not None
            test_result = result.variant_results[0]
            assert test_result is not None

            self.assertEqual(control_result.number_of_samples, expected_results["control_absolute_exposure"])
            self.assertEqual(test_result.number_of_samples, expected_results["test_absolute_exposure"])

        ## Run again with filterTestAccounts=False
        metric = ExperimentMeanMetric(
            source=EventsNode(event="$pageview"),
        )
        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )
        experiment.exposure_criteria = {"filterTestAccounts": False}
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()
        assert result.variant_results is not None
        control_result = result.baseline
        assert control_result is not None
        test_result = result.variant_results[0]
        assert test_result is not None

        self.assertEqual(control_result.number_of_samples, 14)
        self.assertEqual(test_result.number_of_samples, 16)

    @parameterized.expand(
        [
            [
                "experiment_duration",
                None,
                {
                    "control_count": 3,
                    "test_count": 3,
                },
            ],
            [
                "24_hour_window",
                24,
                {
                    "control_count": 1,
                    "test_count": 1,
                },
            ],
            [
                "48_hour_window",
                48,
                {
                    "control_count": 6,
                    "test_count": 6,
                },
            ],
            [
                "72_hour_window",
                72,
                {
                    "control_count": 7,
                    "test_count": 7,
                },
            ],
        ]
    )
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_with_time_window(self, time_window_name, time_window_hours, expected_results):
        feature_flag = self.create_feature_flag()
        # Note: This test doesn't need query builder parameterization as it tests the same logic

        feature_flag_property = f"$feature/{feature_flag.key}"

        experiment = self.create_experiment(
            feature_flag=feature_flag, start_date=datetime(2020, 1, 1), end_date=datetime(2020, 1, 5, 12, 0, 0)
        )
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": False}

        metric = ExperimentMeanMetric(
            source=EventsNode(event="purchase"),
            conversion_window=time_window_hours,
            conversion_window_unit=FunnelConversionWindowTimeUnit.HOUR,
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        for variant, purchase_count in [("control", 6), ("test", 8)]:
            for i in range(10):
                d = datetime(2020, 1, i + 2, 11, 30, 0)
                _create_person(distinct_ids=[f"user_{variant}_{i}"], team_id=self.team.pk)
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"user_{variant}_{i}",
                    timestamp=d,
                    properties={
                        feature_flag_property: variant,
                        "$feature_flag_response": variant,
                        "$feature_flag": feature_flag.key,
                    },
                )
                if i < purchase_count:
                    # Create variable number of purchase events to add variance
                    num_purchases = (i % 3) + 1  # 1, 2, or 3 purchases per user
                    for k in range(num_purchases):
                        _create_event(
                            team=self.team,
                            event="purchase",
                            distinct_id=f"user_{variant}_{i}",
                            timestamp=d + timedelta(hours=15 * (i + 1) + k),
                            properties={feature_flag_property: variant},
                        )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)
        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        # Exposures on 2020-01-02 11:30, 2020-01-03 11:30, 2020-01-04 11:30, 2020-01-05 11:30
        self.assertEqual(control_variant.number_of_samples, 4)
        self.assertEqual(test_variant.number_of_samples, 4)
        # Purchases on 2020-01-03 02:30:00 (15 hours), 2020-01-04 17:30:00 (30 hours), 2020-01-06 08:30:00 (45 hours), 2020-01-07 23:30:00 (60 hours)
        self.assertEqual(control_variant.sum, expected_results["control_count"])
        self.assertEqual(test_variant.sum, expected_results["test_count"])

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_excludes_multiple_variants(self, name, use_new_query_builder):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        metric = ExperimentMeanMetric(
            source=EventsNode(event="$pageview"),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        # Users who see only control variant
        for i in range(3):
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_control_{i}",
                timestamp="2020-01-02T12:00:00Z",
                properties={
                    "$feature_flag_response": "control",
                    feature_flag_property: "control",
                    "$feature_flag": feature_flag.key,
                },
            )
            # Create different numbers of events per user to create variance
            for j in range(i + 1):
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_control_{i}",
                    timestamp=f"2020-01-02T12:0{j+1}:00Z",
                    properties={feature_flag_property: "control"},
                )

        # Users who see only test variant
        for i in range(3):
            _create_person(distinct_ids=[f"user_test_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_test_{i}",
                timestamp="2020-01-02T12:00:00Z",
                properties={
                    "$feature_flag_response": "test",
                    feature_flag_property: "test",
                    "$feature_flag": feature_flag.key,
                },
            )
            # Create different numbers of events per user to create variance
            for j in range(i + 1):
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_test_{i}",
                    timestamp=f"2020-01-02T12:0{j+1}:00Z",
                    properties={feature_flag_property: "test"},
                )

        # User who sees both variants (should be excluded)
        _create_person(distinct_ids=["user_multiple"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_multiple",
            timestamp="2020-01-02T12:00:00Z",
            properties={
                "$feature_flag_response": "control",
                feature_flag_property: "control",
                "$feature_flag": feature_flag.key,
            },
        )
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_multiple",
            timestamp="2020-01-02T12:01:00Z",
            properties={
                "$feature_flag_response": "test",
                feature_flag_property: "test",
                "$feature_flag": feature_flag.key,
            },
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_multiple",
            timestamp="2020-01-02T12:02:00Z",
            properties={feature_flag_property: "control"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_multiple",
            timestamp="2020-01-02T12:03:00Z",
            properties={feature_flag_property: "test"},
        )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)
        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        # Verify that only the single-variant users are counted
        # Control: user_0 (1 event) + user_1 (2 events) + user_2 (3 events) = 6 total events
        self.assertEqual(control_variant.sum, 6)  # 1 + 2 + 3 = 6 events
        # Test: user_0 (1 event) + user_1 (2 events) + user_2 (3 events) = 6 total events
        self.assertEqual(test_variant.sum, 6)  # 1 + 2 + 3 = 6 events

        # Verify the exposure counts (users who have been exposed to the variant)
        self.assertEqual(control_variant.number_of_samples, 3)  # 3 control users
        self.assertEqual(test_variant.number_of_samples, 3)  # 3 test users

    @parameterized.expand(
        [
            [
                "exclude",
                MultipleVariantHandling.EXCLUDE,
                {"control_count": 3, "test_count": 3, "control_exposure": 2, "test_exposure": 2},
            ],
            [
                "first_seen",
                MultipleVariantHandling.FIRST_SEEN,
                {"control_count": 6, "test_count": 5, "control_exposure": 3, "test_exposure": 3},
            ],
        ]
    )
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_multiple_variant_handling_options(
        self, handling_name, multiple_variant_handling, expected_results
    ):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        # Note: This test doesn't need query builder parameterization as it tests the same logic
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": False}

        # Set the multiple_variant_handling configuration
        experiment.exposure_criteria = {"multiple_variant_handling": multiple_variant_handling}
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        metric = ExperimentMeanMetric(
            source=EventsNode(event="$pageview"),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        # Users who see only control variant - create multiple users with different pageview counts
        for i in range(2):
            _create_person(distinct_ids=[f"user_control_only_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_control_only_{i}",
                timestamp="2020-01-02T12:00:00Z",
                properties={
                    "$feature_flag_response": "control",
                    feature_flag_property: "control",
                    "$feature_flag": feature_flag.key,
                },
            )
            # First user gets 1 pageview, second user gets 2 pageviews
            for j in range(i + 1):
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_control_only_{i}",
                    timestamp=f"2020-01-02T12:0{j+1}:00Z",
                    properties={feature_flag_property: "control"},
                )

        # Users who see only test variant - create multiple users with different pageview counts
        for i in range(2):
            _create_person(distinct_ids=[f"user_test_only_{i}"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_test_only_{i}",
                timestamp="2020-01-02T12:00:00Z",
                properties={
                    "$feature_flag_response": "test",
                    feature_flag_property: "test",
                    "$feature_flag": feature_flag.key,
                },
            )
            # First user gets 1 pageview, second user gets 2 pageviews
            for j in range(i + 1):
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_test_only_{i}",
                    timestamp=f"2020-01-02T12:0{j+1}:00Z",
                    properties={feature_flag_property: "test"},
                )

        # User who sees control first, then test (for testing first_seen vs last_seen)
        _create_person(distinct_ids=["user_multiple_control_first"], team_id=self.team.pk)
        # First exposure: control (earlier timestamp)
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_multiple_control_first",
            timestamp="2020-01-02T11:00:00Z",
            properties={
                "$feature_flag_response": "control",
                feature_flag_property: "control",
                "$feature_flag": feature_flag.key,
            },
        )
        # Second exposure: test (later timestamp)
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_multiple_control_first",
            timestamp="2020-01-02T13:00:00Z",
            properties={
                "$feature_flag_response": "test",
                feature_flag_property: "test",
                "$feature_flag": feature_flag.key,
            },
        )
        # Events for both variants
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_multiple_control_first",
            timestamp="2020-01-02T11:30:00Z",
            properties={feature_flag_property: "control"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_multiple_control_first",
            timestamp="2020-01-02T12:30:00Z",
            properties={feature_flag_property: "control"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_multiple_control_first",
            timestamp="2020-01-02T13:30:00Z",
            properties={feature_flag_property: "test"},
        )

        # User who sees test first, then control (for testing first_seen vs last_seen)
        _create_person(distinct_ids=["user_multiple_test_first"], team_id=self.team.pk)
        # First exposure: test (earlier timestamp)
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_multiple_test_first",
            timestamp="2020-01-02T10:00:00Z",
            properties={
                "$feature_flag_response": "test",
                feature_flag_property: "test",
                "$feature_flag": feature_flag.key,
            },
        )
        # Second exposure: control (later timestamp)
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_multiple_test_first",
            timestamp="2020-01-02T14:00:00Z",
            properties={
                "$feature_flag_response": "control",
                feature_flag_property: "control",
                "$feature_flag": feature_flag.key,
            },
        )
        # Events for both variants
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_multiple_test_first",
            timestamp="2020-01-02T10:30:00Z",
            properties={feature_flag_property: "test"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_multiple_test_first",
            timestamp="2020-01-02T14:30:00Z",
            properties={feature_flag_property: "control"},
        )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)
        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        # Verify the expected behavior based on multiple_variant_handling setting
        self.assertEqual(
            control_variant.sum,
            expected_results["control_count"],
            f"Control count mismatch for {handling_name} handling",
        )
        self.assertEqual(
            test_variant.sum, expected_results["test_count"], f"Test count mismatch for {handling_name} handling"
        )
        self.assertEqual(
            control_variant.number_of_samples,
            expected_results["control_exposure"],
            f"Control exposure mismatch for {handling_name} handling",
        )
        self.assertEqual(
            test_variant.number_of_samples,
            expected_results["test_exposure"],
            f"Test exposure mismatch for {handling_name} handling",
        )

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_with_none_event_filters_all_events(self, name, use_new_query_builder):
        """Test that when event is None, all events are selected (no event name filter applied)."""
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Use None event to match all events
        metric = ExperimentMeanMetric(
            source=EventsNode(
                event=None,  # This should match all events
                properties=[
                    EventPropertyFilter(
                        key="test_property", operator=PropertyOperator.EXACT, value="test_value", type="event"
                    ),
                ],
            ),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        # Create exposure events
        for variant in ["control", "test"]:
            for i in range(5):
                _create_person(distinct_ids=[f"user_{variant}_{i}"], team_id=self.team.pk)
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"user_{variant}_{i}",
                    timestamp="2020-01-02T12:00:00Z",
                    properties={
                        feature_flag_property: variant,
                        "$feature_flag_response": variant,
                        "$feature_flag": feature_flag.key,
                    },
                )

        # Create metric events with different event names but same property filter
        # These should all be counted since event=None should match all events
        metric_events = [
            ("purchase", "control", 3),
            ("signup", "control", 2),
            ("pageview", "control", 1),
            ("purchase", "test", 4),
            ("signup", "test", 3),
            ("pageview", "test", 2),
        ]

        for event_name, variant, count in metric_events:
            for i in range(count):
                _create_event(
                    team=self.team,
                    event=event_name,
                    distinct_id=f"user_{variant}_{i}",
                    timestamp="2020-01-02T12:01:00Z",
                    properties={
                        feature_flag_property: variant,
                        "test_property": "test_value",  # This matches our property filter
                    },
                )

        # Create some events that should NOT be counted (different property value)
        for variant in ["control", "test"]:
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=f"user_{variant}_excluded",
                timestamp="2020-01-02T12:01:00Z",
                properties={
                    feature_flag_property: variant,
                    "test_property": "different_value",  # This should be filtered out
                },
            )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()

        assert result.variant_results is not None

        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        assert control_variant is not None

        test_variant = result.variant_results[0]
        assert test_variant is not None

        # Control should have 3 + 2 + 1 = 6 events (all event types with matching property)
        self.assertEqual(control_variant.sum, 6)
        # Test should have 4 + 3 + 2 = 9 events (all event types with matching property)
        self.assertEqual(test_variant.sum, 9)
        # Both should have 5 exposures each
        self.assertEqual(control_variant.number_of_samples, 5)
        self.assertEqual(test_variant.number_of_samples, 5)

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_with_hogql_aggregation_expressions(self, name, use_new_query_builder):
        """Test that HogQL aggregation expressions work end-to-end."""
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Test with sum aggregation expression
        metric_sum = ExperimentMeanMetric(
            source=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.HOGQL,
                math_hogql="sum(toFloat(properties.revenue) - toFloat(properties.cost))",
            ),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric_sum,
        )

        experiment.metrics = [metric_sum.model_dump(mode="json")]
        experiment.save()

        # Create test data with revenue and cost properties
        for variant, user_count in [("control", 10), ("test", 10)]:
            for i in range(user_count):
                _create_person(distinct_ids=[f"user_{variant}_{i}"], team_id=self.team.pk)
                # Create exposure event
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"user_{variant}_{i}",
                    timestamp="2020-01-02T12:00:00Z",
                    properties={
                        feature_flag_property: variant,
                        "$feature_flag_response": variant,
                        "$feature_flag": feature_flag.key,
                    },
                )
                # Create purchase events with different revenue/cost values
                purchase_count = 6 if variant == "control" else 8
                if i < purchase_count:
                    if variant == "control":
                        revenue = 100 + (i * 10)  # revenue: 100, 110, 120, 130, 140, 150
                        cost = 20 + (i * 5)  # cost: 20, 25, 30, 35, 40, 45
                    else:  # test variant
                        revenue = 120 + (i * 15)  # revenue: 120, 135, 150, 165, 180, 195, 210, 225
                        cost = 30 + (i * 3)  # cost: 30, 33, 36, 39, 42, 45, 48, 51

                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=f"user_{variant}_{i}",
                        timestamp="2020-01-02T12:01:00Z",
                        properties={
                            feature_flag_property: variant,
                            "revenue": revenue,
                            "cost": cost,
                        },
                    )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()
        assert result.variant_results is not None

        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]

        # Control: 6 purchases with (revenue - cost) = (80, 85, 90, 95, 100, 105) = sum = 555
        expected_control_sum = sum([80, 85, 90, 95, 100, 105])
        self.assertEqual(control_variant.sum, expected_control_sum)
        self.assertEqual(control_variant.number_of_samples, 10)

        # Test: 8 purchases with (revenue - cost) = (90, 102, 114, 126, 138, 150, 162, 174) = sum = 1056
        expected_test_sum = sum([90, 102, 114, 126, 138, 150, 162, 174])
        self.assertEqual(test_variant.sum, expected_test_sum)
        self.assertEqual(test_variant.number_of_samples, 10)

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_with_hogql_aggregation_end_to_end(self, name, use_new_query_builder):
        """Test that HogQL aggregation expressions work end-to-end with the experiment query runner."""
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Test with avg aggregation expression - this should use avg() not sum()
        metric_avg = ExperimentMeanMetric(
            source=EventsNode(
                event="purchase", math=ExperimentMetricMathType.HOGQL, math_hogql="avg(properties.amount)"
            ),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric_avg,
        )

        experiment.metrics = [metric_avg.model_dump(mode="json")]
        experiment.save()

        # Create test data - simple case with one event per user
        for variant, amounts in [("control", [10, 20, 30]), ("test", [15, 25, 35, 45])]:
            for i, amount in enumerate(amounts):
                _create_person(distinct_ids=[f"user_{variant}_{i}"], team_id=self.team.pk)
                # Create exposure event
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"user_{variant}_{i}",
                    timestamp="2020-01-02T12:00:00Z",
                    properties={
                        feature_flag_property: variant,
                        "$feature_flag_response": variant,
                        "$feature_flag": feature_flag.key,
                    },
                )
                # Create purchase event
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_{variant}_{i}",
                    timestamp="2020-01-02T12:01:00Z",
                    properties={
                        feature_flag_property: variant,
                        "amount": amount,
                    },
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()
        assert result.variant_results is not None

        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]

        # With one event per user, avg(amount) per user = amount, so we get:
        # Control: 10 + 20 + 30 = 60
        # Test: 15 + 25 + 35 + 45 = 120
        self.assertEqual(control_variant.sum, 60)
        self.assertEqual(test_variant.sum, 120)
        self.assertEqual(control_variant.number_of_samples, 3)
        self.assertEqual(test_variant.number_of_samples, 4)

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_with_hogql_fallback_to_sum(self, name, use_new_query_builder):
        """Test that HogQL expressions without aggregation functions default to sum."""
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        # Test with simple property expression (no aggregation function)
        metric_simple = ExperimentMeanMetric(
            source=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.HOGQL,
                math_hogql="properties.price",  # No aggregation function, should default to sum
            ),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric_simple,
        )

        experiment.metrics = [metric_simple.model_dump(mode="json")]
        experiment.save()

        # Create test data
        for variant, prices in [("control", [50, 75]), ("test", [60, 80, 100])]:
            for i, price in enumerate(prices):
                _create_person(distinct_ids=[f"user_{variant}_{i}"], team_id=self.team.pk)
                # Create exposure event
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"user_{variant}_{i}",
                    timestamp="2020-01-02T12:00:00Z",
                    properties={
                        feature_flag_property: variant,
                        "$feature_flag_response": variant,
                        "$feature_flag": feature_flag.key,
                    },
                )
                # Create purchase event
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_{variant}_{i}",
                    timestamp="2020-01-02T12:01:00Z",
                    properties={
                        feature_flag_property: variant,
                        "price": price,
                    },
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()
        assert result.variant_results is not None

        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]

        # Control: sum(50, 75) = 125
        self.assertEqual(control_variant.sum, 125)
        self.assertEqual(control_variant.number_of_samples, 2)

        # Test: sum(60, 80, 100) = 240
        self.assertEqual(test_variant.sum, 240)
        self.assertEqual(test_variant.number_of_samples, 3)

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_with_unique_users_metric(self, name, use_new_query_builder):
        """Test that unique users metric correctly counts unique users, not total events."""
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag, start_date=datetime(2020, 1, 1), end_date=datetime(2020, 1, 10)
        )
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="purchase",
                math=ExperimentMetricMathType.DAU,
            ),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        # Create test data with multiple events per user to verify unique counting
        # Control: 3 users, but user_0 has 3 events, user_1 has 2 events, user_2 has 1 event
        for i in range(3):
            _create_person(distinct_ids=[f"user_control_{i}"], team_id=self.team.pk)
            # Create exposure event
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_control_{i}",
                timestamp="2020-01-02T12:00:00Z",
                properties={
                    feature_flag_property: "control",
                    "$feature_flag_response": "control",
                    "$feature_flag": feature_flag.key,
                },
            )
            # Create multiple purchase events for some users
            num_purchases = 2 - i  # user_0: 2 events, user_1: 1 events, user_2: 0 event
            for j in range(num_purchases):
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_control_{i}",
                    timestamp=f"2020-01-0{2+j}T12:01:00Z",  # Different timestamps
                    properties={
                        feature_flag_property: "control",
                        "price": 50 + (i * 10) + j,
                    },
                )

        # Test: 4 users, with varying numbers of events
        for i in range(4):
            _create_person(distinct_ids=[f"user_test_{i}"], team_id=self.team.pk)
            # Create exposure event
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=f"user_test_{i}",
                timestamp="2020-01-02T12:00:00Z",
                properties={
                    feature_flag_property: "test",
                    "$feature_flag_response": "test",
                    "$feature_flag": feature_flag.key,
                },
            )
            # Create multiple purchase events: user_0: 4 events, user_1: 3 events, user_2: 2 events, user_3: 1 event
            num_purchases = 4 - i
            for j in range(num_purchases):
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_test_{i}",
                    timestamp=f"2020-01-0{2+j}T12:01:00Z",  # Different timestamps
                    properties={
                        feature_flag_property: "test",
                        "price": 60 + (i * 10) + j,
                    },
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()
        assert result.variant_results is not None

        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        # should count unique users, not total events
        # Control: 2 unique users (even though total events = 2+1 = 3)
        self.assertEqual(control_variant.sum, 2)
        self.assertEqual(control_variant.number_of_samples, 3)

        # Test: 4 unique users (even though total events = 4+3+2+1 = 10)
        self.assertEqual(test_variant.sum, 4)
        self.assertEqual(test_variant.number_of_samples, 4)

    @parameterized.expand([("disable_new_query_builder", False), ("enable_new_query_builder", True)])
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_with_unique_group_metric(self, name, use_new_query_builder):
        """Test unique group metric counts unique groups that performed the target event."""
        feature_flag = self.create_feature_flag()
        feature_flag.filters["aggregation_group_type_index"] = 0
        feature_flag.save()
        experiment = self.create_experiment(
            feature_flag=feature_flag, start_date=datetime(2020, 1, 1), end_date=datetime(2020, 1, 10)
        )
        experiment.stats_config = {"method": "frequentist", "use_new_query_builder": use_new_query_builder}
        experiment.save()

        metric = ExperimentMeanMetric(
            source=EventsNode(
                event="purchase",
                math="unique_group",
                math_group_type_index=0,
            ),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        create_standard_group_test_events(self.team, feature_flag)

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = query_runner.calculate()
        assert result.variant_results is not None

        self.assertEqual(len(result.variant_results), 1)

        control_variant = result.baseline
        assert control_variant is not None
        test_variant = result.variant_results[0]
        assert test_variant is not None

        # Control: groups 0 and 1 have purchase events (first 6 users: 0→0, 1→1, 2→0, 3→1, 4→0, 5→1)
        # Test: groups 2, 3, and 4 have purchase events (first 8 users: 0→2, 1→3, 2→4, 3→2, 4→3, 5→4, 6→2, 7→3)
        self.assertEqual(control_variant.sum, 2)  # 2 unique groups with purchase events
        self.assertEqual(control_variant.number_of_samples, 2)  # 2 unique groups exposed to control
        self.assertEqual(test_variant.sum, 3)  # 3 unique groups with purchase events
        self.assertEqual(test_variant.number_of_samples, 3)  # 3 unique groups exposed to test
