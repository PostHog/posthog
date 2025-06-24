import json
from datetime import datetime, timedelta
from typing import cast

from django.test import override_settings
from freezegun import freeze_time
from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.constants import ExperimentNoResultsErrorKeys
from posthog.hogql_queries.experiments.experiment_query_runner import (
    ExperimentQueryRunner,
)
from posthog.hogql_queries.experiments.test.experiment_query_runner.base import (
    ExperimentQueryRunnerBaseTest,
)
from posthog.hogql_queries.experiments.test.experiment_query_runner.utils import (
    create_standard_group_test_events,
)
from posthog.models.action.action import Action
from posthog.models.cohort.cohort import Cohort
from posthog.models.group.util import create_group
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.schema import (
    ActionsNode,
    EventPropertyFilter,
    EventsNode,
    ExperimentDataWarehouseNode,
    ExperimentEventExposureConfig,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentQuery,
    ExperimentSignificanceCode,
    ExperimentVariantTrendsBaseStats,
    FunnelConversionWindowTimeUnit,
    LegacyExperimentQueryResponse,
    PropertyOperator,
)
from posthog.test.base import (
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
from posthog.test.test_journeys import journeys_for


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentQueryRunner(ExperimentQueryRunnerBaseTest):
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_includes_date_range(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag, end_date=datetime(2020, 2, 1, 12, 0, 0))
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
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_variant.count, 6)
        self.assertEqual(test_variant.count, 8)
        self.assertEqual(control_variant.absolute_exposure, 10)
        self.assertEqual(test_variant.absolute_exposure, 10)

    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_includes_event_property_filters(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
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
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_variant.count, 6)
        self.assertEqual(test_variant.count, 8)
        self.assertEqual(control_variant.absolute_exposure, 11)
        self.assertEqual(test_variant.absolute_exposure, 11)

    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_using_action(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

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
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_variant.count, 6)
        self.assertEqual(test_variant.count, 8)
        self.assertEqual(control_variant.absolute_exposure, 10)
        self.assertEqual(test_variant.absolute_exposure, 10)

    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_group_aggregation_mean_metric(self):
        feature_flag = self.create_feature_flag()
        feature_flag.filters["aggregation_group_type_index"] = 0
        feature_flag.save()
        experiment = self.create_experiment(feature_flag=feature_flag)

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
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_variant.absolute_exposure, 2)
        self.assertEqual(test_variant.absolute_exposure, 3)
        self.assertEqual(control_variant.count, 6)
        self.assertEqual(test_variant.count, 8)

    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_group_aggregation_mean_property_sum_metric(self):
        feature_flag = self.create_feature_flag()
        feature_flag.filters["aggregation_group_type_index"] = 0
        feature_flag.save()
        experiment = self.create_experiment(feature_flag=feature_flag)

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
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_variant.absolute_exposure, 2)
        self.assertEqual(test_variant.absolute_exposure, 3)
        self.assertEqual(control_variant.count, 60)
        self.assertEqual(test_variant.count, 120)

    @snapshot_clickhouse_queries
    def test_query_runner_group_aggregation_data_warehouse_mean_metric(self):
        feature_flag = self.create_feature_flag()
        feature_flag.filters["aggregation_group_type_index"] = 0
        feature_flag.save()

        experiment = self.create_experiment(
            feature_flag=feature_flag, start_date=datetime(2023, 1, 1), end_date=datetime(2023, 1, 31)
        )
        experiment.save()

        table_name = self.create_data_warehouse_table_with_usage()

        feature_flag_property = f"$feature/{feature_flag.key}"

        metric = ExperimentMeanMetric(
            source=ExperimentDataWarehouseNode(
                table_name=table_name,
                events_join_key="properties.$user_id",
                data_warehouse_join_key="userid",
                timestamp_field="ds",
                math=ExperimentMetricMathType.TOTAL,
                math_property=None,
            ),
        )
        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        GroupTypeMapping.objects.create(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:1",
            properties={"name": "org 1"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:2",
            properties={"name": "org 2"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:3",
            properties={"name": "org 3"},
        )

        # Populate exposure events
        for variant, count in [("control", 7), ("test", 9)]:
            for i in range(count):
                if variant == "test":
                    group_key = "org:2" if i > 5 else "org:3"
                else:
                    group_key = "org:1"

                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"distinct_{variant}_{i}",
                    properties={
                        "$feature_flag_response": variant,
                        feature_flag_property: variant,
                        "$feature_flag": feature_flag.key,
                        "$user_id": f"user_{variant}_{i}",
                        "$group_0": group_key,
                        "$groups": {
                            "organization": group_key,
                        },
                    },
                    timestamp=datetime(2023, 1, i + 1),
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        with freeze_time("2023-01-07"):
            result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_result = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_result = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )
        self.assertEqual(control_result.absolute_exposure, 1)
        self.assertEqual(test_result.absolute_exposure, 2)
        self.assertEqual(control_result.count, 1)
        self.assertEqual(test_result.count, 3)

    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_standard_flow_v2_stats(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
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
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)
        for variant in result.variants:
            self.assertIn(variant.key, ["control", "test"])

        control_variant = cast(ExperimentVariantTrendsBaseStats, next(v for v in result.variants if v.key == "control"))
        test_variant = cast(ExperimentVariantTrendsBaseStats, next(v for v in result.variants if v.key == "test"))

        self.assertEqual(control_variant.count, 3)
        self.assertEqual(test_variant.count, 5)
        self.assertEqual(control_variant.absolute_exposure, 2)
        self.assertEqual(test_variant.absolute_exposure, 2)

        self.assertEqual(result.significance_code, ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE)

        self.assertFalse(result.significant)

        self.assertEqual(len(result.variants), 2)

        self.assertEqual(control_variant.absolute_exposure, 2.0)
        self.assertEqual(control_variant.count, 3.0)
        # In the new query runner, the exposure value is the same as the absolute exposure value
        self.assertEqual(control_variant.exposure, 2.0)

        self.assertEqual(test_variant.absolute_exposure, 2.0)
        self.assertEqual(test_variant.count, 5.0)
        # In the new query runner, the exposure value is the same as the absolute exposure value
        self.assertEqual(test_variant.exposure, 2.0)

    @snapshot_clickhouse_queries
    def test_query_runner_data_warehouse_count_metric(self):
        table_name = self.create_data_warehouse_table_with_usage()

        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag, start_date=datetime(2023, 1, 1), end_date=datetime(2023, 1, 31)
        )
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        metric = ExperimentMeanMetric(
            source=ExperimentDataWarehouseNode(
                table_name=table_name,
                events_join_key="properties.$user_id",
                data_warehouse_join_key="userid",
                timestamp_field="ds",
                math=ExperimentMetricMathType.TOTAL,
                math_property=None,
            ),
        )
        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )
        experiment.exposure_criteria = {"filterTestAccounts": False}
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        # Populate exposure events
        for variant, count in [("control", 7), ("test", 9)]:
            for i in range(count):
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"distinct_{variant}_{i}",
                    properties={
                        "$feature_flag_response": variant,
                        feature_flag_property: variant,
                        "$feature_flag": feature_flag.key,
                        "$user_id": f"user_{variant}_{i}",
                        "$group_0": "my_awesome_group",
                    },
                    timestamp=datetime(2023, 1, i + 1),
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        with freeze_time("2023-01-07"):
            result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_result = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_result = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_result.count, 1)
        self.assertEqual(test_result.count, 3)
        self.assertEqual(control_result.absolute_exposure, 7)
        self.assertEqual(test_result.absolute_exposure, 9)

    @snapshot_clickhouse_queries
    def test_query_runner_data_warehouse_continuous_metric(self):
        table_name = self.create_data_warehouse_table_with_usage()

        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag, start_date=datetime(2023, 1, 1), end_date=datetime(2023, 1, 31)
        )
        experiment.save()

        feature_flag_property = f"$feature/{feature_flag.key}"

        metric = ExperimentMeanMetric(
            source=ExperimentDataWarehouseNode(
                table_name=table_name,
                events_join_key="properties.$user_id",
                data_warehouse_join_key="userid",
                timestamp_field="ds",
                math=ExperimentMetricMathType.SUM,
                math_property="usage",
            ),
        )
        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )
        experiment.exposure_criteria = {"filterTestAccounts": False}
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        # Populate exposure events
        for variant, count in [("control", 7), ("test", 9)]:
            for i in range(count):
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"distinct_{variant}_{i}",
                    properties={
                        "$feature_flag_response": variant,
                        feature_flag_property: variant,
                        "$feature_flag": feature_flag.key,
                        "$user_id": f"user_{variant}_{i}",
                        "$group_0": "my_awesome_group",
                    },
                    timestamp=datetime(2023, 1, i + 1),
                )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        with freeze_time("2023-01-07"):
            result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_result = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_result = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_result.count, 1000)
        self.assertEqual(test_result.count, 2050)
        self.assertEqual(control_result.absolute_exposure, 7)
        self.assertEqual(test_result.absolute_exposure, 9)

    @snapshot_clickhouse_queries
    def test_query_runner_with_custom_exposure(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag, start_date=datetime(2020, 1, 1), end_date=datetime(2020, 1, 31)
        )

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
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_variant.count, 6)
        self.assertEqual(test_variant.count, 8)
        self.assertEqual(control_variant.absolute_exposure, 10)
        self.assertEqual(test_variant.absolute_exposure, 10)

    @snapshot_clickhouse_queries
    def test_query_runner_with_custom_exposure_without_properties(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag, start_date=datetime(2020, 1, 1), end_date=datetime(2020, 1, 31)
        )

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
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_variant.count, 6)
        self.assertEqual(test_variant.count, 8)
        self.assertEqual(control_variant.absolute_exposure, 11)
        self.assertEqual(test_variant.absolute_exposure, 10)

    @snapshot_clickhouse_queries
    def test_query_runner_with_custom_exposure_on_feature_flag_called_event(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag, start_date=datetime(2020, 1, 1), end_date=datetime(2020, 1, 31)
        )

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
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_variant.count, 6)
        self.assertEqual(test_variant.count, 8)
        self.assertEqual(control_variant.absolute_exposure, 10)
        self.assertEqual(test_variant.absolute_exposure, 10)

    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_without_feature_flag_property(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag, end_date=datetime(2020, 2, 1, 12, 0, 0))
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
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_variant.count, 6)
        self.assertEqual(test_variant.count, 8)
        self.assertEqual(control_variant.absolute_exposure, 11)
        self.assertEqual(test_variant.absolute_exposure, 10)

    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_no_exposures(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

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

        # No exposures

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        with self.assertRaises(ValidationError) as context:
            cast(LegacyExperimentQueryResponse, query_runner.calculate())

        expected_errors = json.dumps(
            {
                ExperimentNoResultsErrorKeys.NO_EXPOSURES: True,
                ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: True,
                ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: True,
            }
        )
        self.assertEqual(cast(list, context.exception.detail)[0], expected_errors)

    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_no_variant_events(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

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
        for variant in [("control", 10), ("test", 8)]:
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

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        with self.assertRaises(ValidationError) as context:
            cast(LegacyExperimentQueryResponse, query_runner.calculate())

        expected_errors = json.dumps(
            {
                ExperimentNoResultsErrorKeys.NO_EXPOSURES: True,  # Should be False but the query doesn't support it yet
                ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: True,
                ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: True,
            }
        )
        self.assertEqual(cast(list, context.exception.detail)[0], expected_errors)

    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_no_control_variant(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

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
        with self.assertRaises(ValidationError) as context:
            cast(LegacyExperimentQueryResponse, query_runner.calculate())

        expected_errors = json.dumps(
            {
                ExperimentNoResultsErrorKeys.NO_EXPOSURES: False,
                ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: True,
                ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: False,
            }
        )
        self.assertEqual(cast(list, context.exception.detail)[0], expected_errors)

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
                    "control_absolute_exposure": 2,
                    "test_absolute_exposure": 1,
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
    def test_query_runner_with_internal_filters(self, name: str, filter: dict, expected_results: dict):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag, start_date=datetime(2020, 1, 1), end_date=datetime(2020, 1, 31)
        )

        cohort = None
        if name == "cohort_static":
            cohort = Cohort.objects.create(
                team=self.team,
                name="cohort_static",
                is_static=True,
            )
            filter["value"] = cohort.pk
        elif name == "cohort_dynamic":
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
        elif name == "group":
            GroupTypeMapping.objects.create(
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

        # Populate count events
        for variant, count in [("control", 7), ("test", 9)]:
            for i in range(count):
                extra_properties = {"$host": "localhost", "$group_0": "my_awesome_group"} if i > 5 else {}
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_{variant}_{i}",
                    timestamp=datetime(2020, 1, i + 2),
                    properties={feature_flag_property: variant, **extra_properties},
                )

        # Populate exposure events
        for variant, count in [("control", 14), ("test", 16)]:
            for i in range(count):
                extra_properties = {"$host": "localhost", "$group_0": "my_awesome_group"} if i > 5 else {}
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

        _create_person(
            team=self.team,
            distinct_ids=["user_control_1"],
        )
        _create_person(
            team=self.team,
            distinct_ids=["user_control_2"],
        )
        _create_person(
            team=self.team,
            distinct_ids=["user_control_3"],
            properties={"email": "user_control_3@posthog.com"},
        )
        _create_person(
            team=self.team,
            distinct_ids=["user_control_6"],
            properties={"email": "user_control_6@posthog.com"},
        )
        _create_person(
            team=self.team,
            distinct_ids=["user_test_2"],
            properties={"email": "user_test_2@posthog.com"},
        )
        _create_person(
            team=self.team,
            distinct_ids=["user_test_3"],
        )

        flush_persons_and_events()

        if name == "cohort_static" and cohort:
            cohort.insert_users_by_list(["user_control_1", "user_control_2", "user_test_2"])
            self.assertEqual(cohort.people.count(), 3)
        elif name == "cohort_dynamic" and cohort:
            cohort.calculate_people_ch(pending_version=0)

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        # "feature_flags" and "element" filter out all events
        if name == "feature_flags" or name == "element":
            with self.assertRaises(ValidationError) as context:
                cast(LegacyExperimentQueryResponse, query_runner.calculate())

            expected_errors = json.dumps(
                {
                    ExperimentNoResultsErrorKeys.NO_EXPOSURES: True,
                    ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: True,
                    ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: True,
                }
            )
            self.assertEqual(cast(list, context.exception.detail)[0], expected_errors)
        else:
            result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

            control_result = cast(
                ExperimentVariantTrendsBaseStats,
                next(variant for variant in result.variants if variant.key == "control"),
            )
            test_result = cast(
                ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "test")
            )

            self.assertEqual(control_result.absolute_exposure, expected_results["control_absolute_exposure"])
            self.assertEqual(test_result.absolute_exposure, expected_results["test_absolute_exposure"])

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
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        control_result = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_result = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_result.absolute_exposure, 14)
        self.assertEqual(test_result.absolute_exposure, 16)

    @parameterized.expand(
        [
            [
                "experiment_duration",
                None,
                {
                    "control_count": 2,
                    "test_count": 2,
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
                    "control_count": 3,
                    "test_count": 3,
                },
            ],
            [
                "72_hour_window",
                72,
                {
                    "control_count": 4,
                    "test_count": 4,
                },
            ],
        ]
    )
    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_with_time_window(self, name, time_window_hours, expected_results):
        feature_flag = self.create_feature_flag()

        feature_flag_property = f"$feature/{feature_flag.key}"

        experiment = self.create_experiment(
            feature_flag=feature_flag, start_date=datetime(2020, 1, 1), end_date=datetime(2020, 1, 5, 12, 0, 0)
        )

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
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=f"user_{variant}_{i}",
                        timestamp=d + timedelta(hours=15 * (i + 1)),
                        properties={feature_flag_property: variant},
                    )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        # Exposures on 2020-01-02 11:30, 2020-01-03 11:30, 2020-01-04 11:30, 2020-01-05 11:30
        self.assertEqual(control_variant.absolute_exposure, 4)
        self.assertEqual(test_variant.absolute_exposure, 4)
        # Purchases on 2020-01-03 02:30:00 (15 hours), 2020-01-04 17:30:00 (30 hours), 2020-01-06 08:30:00 (45 hours), 2020-01-07 23:30:00 (60 hours)
        self.assertEqual(control_variant.count, expected_results["control_count"])
        self.assertEqual(test_variant.count, expected_results["test_count"])

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
                    "control_absolute_exposure": 7,
                    "test_absolute_exposure": 9,
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
                    "control_absolute_exposure": 7,
                    "test_absolute_exposure": 9,
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
                    "type": "cohort",
                    # value is generated in the test
                    "value": None,
                    "operator": "exact",
                },
                {
                    "control_absolute_exposure": 1,
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
                    "control_absolute_exposure": 1,
                    "test_absolute_exposure": 1,
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
                    "control_absolute_exposure": 7,
                    "test_absolute_exposure": 9,
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
    def test_query_runner_with_data_warehouse_internal_filters(self, name, filter: dict, filter_expected: dict):
        table_name = self.create_data_warehouse_table_with_usage()

        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 1, 31),
        )

        feature_flag_property = f"$feature/{feature_flag.key}"

        cohort = None
        if name == "cohort_static":
            cohort = Cohort.objects.create(
                team=self.team,
                name="cohort_static",
                is_static=True,
            )
            filter["value"] = cohort.pk
        elif name == "cohort_dynamic":
            cohort = Cohort.objects.create(
                team=self.team,
                name="cohort_dynamic",
                groups=[
                    {
                        "properties": [
                            {"key": "email", "operator": "not_icontains", "value": "@posthog.com", "type": "person"}
                        ]
                    }
                ],
            )
            filter["value"] = cohort.pk
        elif name == "group":
            GroupTypeMapping.objects.create(
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

        metric = ExperimentMeanMetric(
            source=ExperimentDataWarehouseNode(
                table_name=table_name,
                events_join_key="properties.$user_id",
                data_warehouse_join_key="userid",
                timestamp_field="ds",
                math=ExperimentMetricMathType.SUM,
                math_property="usage",
            ),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )
        experiment.exposure_criteria = {"filterTestAccounts": True}
        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        # Populate exposure events
        for variant, count in [("control", 7), ("test", 9)]:
            for i in range(count):
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"distinct_{variant}_{i}",
                    properties={
                        "$feature_flag_response": variant,
                        feature_flag_property: variant,
                        "$feature_flag": feature_flag.key,
                        "$user_id": f"user_{variant}_{i}",
                        "$group_0": "my_awesome_group",
                    },
                    timestamp=datetime(2023, 1, i + 1),
                )

        _create_person(
            team=self.team,
            distinct_ids=["distinct_control_0"],
        )

        _create_person(
            team=self.team,
            distinct_ids=["distinct_test_3"],
        )

        _create_person(
            team=self.team,
            distinct_ids=["internal_test_1"],
            properties={"email": "internal_test_1@posthog.com"},
        )
        # 10th exposure for 'test'
        # filtered out by "event_properties" , "person_properties", and "group"
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="internal_test_1",
            properties={
                feature_flag_property: "test",
                "$feature_flag_response": "test",
                "$feature_flag": feature_flag.key,
                "$user_id": "internal_test_1",
                "$host": "127.0.0.1",
            },
            timestamp=datetime(2023, 1, 3),
        )

        flush_persons_and_events()

        if name == "cohort_static" and cohort:
            cohort.insert_users_by_list(["distinct_control_0", "internal_test_1"])
            self.assertEqual(cohort.people.count(), 2)
        elif name == "cohort_dynamic" and cohort:
            cohort.calculate_people_ch(pending_version=0)

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        # "feature_flags" and "element" filter out all events
        if name == "feature_flags" or name == "element":
            with self.assertRaises(ValidationError) as context:
                query_runner.calculate()

            expected_errors = json.dumps(
                {
                    ExperimentNoResultsErrorKeys.NO_EXPOSURES: True,
                    ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: True,
                    ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: True,
                }
            )
            self.assertEqual(cast(list, context.exception.detail)[0], expected_errors)
        else:
            with freeze_time("2023-01-07"):
                result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

            self.assertEqual(len(result.variants), 2)

            control_result = cast(
                ExperimentVariantTrendsBaseStats,
                next(variant for variant in result.variants if variant.key == "control"),
            )
            test_result = cast(
                ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "test")
            )

            self.assertEqual(control_result.absolute_exposure, filter_expected["control_absolute_exposure"])
            self.assertEqual(test_result.absolute_exposure, filter_expected["test_absolute_exposure"])

        # Run the query again without filtering
        metric = ExperimentMeanMetric(
            source=ExperimentDataWarehouseNode(
                table_name=table_name,
                events_join_key="properties.$user_id",
                data_warehouse_join_key="userid",
                timestamp_field="ds",
                math=ExperimentMetricMathType.SUM,
                math_property="usage",
            ),
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
        with freeze_time("2023-01-07"):
            result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_result = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_result = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_result.absolute_exposure, 7)
        self.assertEqual(test_result.absolute_exposure, 10)

    @snapshot_clickhouse_queries
    def test_query_runner_with_data_warehouse_subscriptions_table(self):
        subscriptions_table_name = self.create_data_warehouse_table_with_subscriptions()

        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 1, 10),
        )

        feature_flag_property = f"$feature/{feature_flag.key}"

        metric = ExperimentMeanMetric(
            source=ExperimentDataWarehouseNode(
                table_name=subscriptions_table_name,
                events_join_key="person.properties.email",
                data_warehouse_join_key="subscription_customer.customer_email",
                timestamp_field="subscription_created_at",
            ),
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        # Populate exposure events
        for variant, count in [("control", 7), ("test", 9)]:
            for i in range(count):
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=f"user_{variant}_{i}",
                    properties={
                        "$feature_flag_response": variant,
                        feature_flag_property: variant,
                        "$feature_flag": feature_flag.key,
                    },
                    timestamp=datetime(2023, 1, i + 1),
                )

        _create_person(
            team=self.team,
            distinct_ids=["user_control_0"],
            properties={"email": "john.doe@example.com"},
        )

        _create_person(
            team=self.team,
            distinct_ids=["user_test_1"],
            properties={"email": "jane.doe@example.com"},
        )

        _create_person(
            team=self.team,
            distinct_ids=["user_test_2"],
            properties={"email": "john.smith@example.com"},
        )

        _create_person(
            team=self.team,
            distinct_ids=["user_test_3"],
            properties={"email": "jane.smith@example.com"},
        )

        flush_persons_and_events()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)

        with freeze_time("2023-01-10"):
            result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_result = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_result = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_result.count, 1)
        self.assertEqual(test_result.count, 3)
        self.assertEqual(control_result.absolute_exposure, 7)
        self.assertEqual(test_result.absolute_exposure, 9)

    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_excludes_multiple_variants(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
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

        # User who sees only control variant
        _create_person(distinct_ids=["user_control"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_control",
            timestamp="2020-01-02T12:00:00Z",
            properties={
                "$feature_flag_response": "control",
                feature_flag_property: "control",
                "$feature_flag": feature_flag.key,
            },
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_control",
            timestamp="2020-01-02T12:01:00Z",
            properties={feature_flag_property: "control"},
        )

        # User who sees only test variant
        _create_person(distinct_ids=["user_test"], team_id=self.team.pk)
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_test",
            timestamp="2020-01-02T12:00:00Z",
            properties={
                "$feature_flag_response": "test",
                feature_flag_property: "test",
                "$feature_flag": feature_flag.key,
            },
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_test",
            timestamp="2020-01-02T12:01:00Z",
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
        result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_variant = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        # Verify that only the single-variant users are counted
        self.assertEqual(control_variant.count, 1)  # Only from user_control
        self.assertEqual(test_variant.count, 1)  # Only from user_test

        # Verify the exposure counts (users who have been exposed to the variant)
        self.assertEqual(control_variant.absolute_exposure, 1)  # Only user_control
        self.assertEqual(test_variant.absolute_exposure, 1)  # Only user_test
