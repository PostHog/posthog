from datetime import datetime
import json
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
from posthog.models.cohort.cohort import Cohort
from posthog.models.group.util import create_group
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.schema import (
    ExperimentDataWarehouseNode,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentQuery,
    ExperimentVariantTrendsBaseStats,
    LegacyExperimentQueryResponse,
)
from posthog.hogql_queries.legacy_compatibility.clean_properties import clean_entity_properties
from posthog.test.base import (
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentQueryRunner(ExperimentQueryRunnerBaseTest):
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
        self.assertEqual(control_result.count, 6)
        self.assertEqual(test_result.count, 7)

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

        self.assertEqual(control_result.count, 6)
        self.assertEqual(test_result.count, 7)
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
        with freeze_time("2023-01-31"):
            result = cast(LegacyExperimentQueryResponse, query_runner.calculate())

        self.assertEqual(len(result.variants), 2)

        control_result = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "control")
        )
        test_result = cast(
            ExperimentVariantTrendsBaseStats, next(variant for variant in result.variants if variant.key == "test")
        )

        self.assertEqual(control_result.count, 650)
        self.assertEqual(test_result.count, 1150)
        self.assertEqual(control_result.absolute_exposure, 7)
        self.assertEqual(test_result.absolute_exposure, 9)

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

    @parameterized.expand(
        [
            [
                "single_property_filter",
                clean_entity_properties(
                    [{"key": "plan", "operator": "exact", "value": "premium", "type": "data_warehouse"}]
                ),
                {"control_count": 500, "test_count": 750},
            ],
            [
                "multiple_property_filters",
                clean_entity_properties(
                    [
                        {"key": "plan", "operator": "exact", "value": "premium", "type": "data_warehouse"},
                        {"key": "region", "operator": "exact", "value": "us-west", "type": "data_warehouse"},
                    ]
                ),
                {"control_count": 250, "test_count": 375},
            ],
            [
                "numeric_property_filter",
                clean_entity_properties([{"key": "usage", "operator": "gt", "value": 100, "type": "data_warehouse"}]),
                {"control_count": 500, "test_count": 1000},
            ],
            [
                "mixed_property_filters",
                clean_entity_properties(
                    [
                        {"key": "plan", "operator": "exact", "value": "premium", "type": "data_warehouse"},
                        {"key": "usage", "operator": "gt", "value": 50, "type": "data_warehouse"},
                    ]
                ),
                {"control_count": 500, "test_count": 750},
            ],
        ]
    )
    @snapshot_clickhouse_queries
    def test_query_runner_data_warehouse_metric_with_property_filters(self, name, properties, expected_results):
        """Test that data warehouse metrics properly apply property filters"""
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
                properties=properties,
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

        self.assertEqual(control_result.count, expected_results["control_count"])
        self.assertEqual(test_result.count, expected_results["test_count"])
        self.assertEqual(control_result.absolute_exposure, 7)
        self.assertEqual(test_result.absolute_exposure, 9)

    @snapshot_clickhouse_queries
    def test_query_runner_data_warehouse_metric_with_fixed_properties(self):
        """Test that data warehouse metrics properly apply fixedProperties"""
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
                fixedProperties=clean_entity_properties(
                    [
                        {"key": "plan", "operator": "exact", "value": "premium", "type": "data_warehouse"},
                    ]
                ),
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

        # Should filter to only premium plan usage
        self.assertEqual(control_result.count, 500)
        self.assertEqual(test_result.count, 750)
        self.assertEqual(control_result.absolute_exposure, 7)
        self.assertEqual(test_result.absolute_exposure, 9)

    @snapshot_clickhouse_queries
    def test_query_runner_data_warehouse_metric_with_both_properties_and_fixed_properties(self):
        """Test that data warehouse metrics properly apply both properties and fixedProperties"""
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
                properties=clean_entity_properties(
                    [
                        {"key": "plan", "operator": "exact", "value": "premium", "type": "data_warehouse"},
                    ]
                ),
                fixedProperties=clean_entity_properties(
                    [
                        {"key": "region", "operator": "exact", "value": "us-west", "type": "data_warehouse"},
                    ]
                ),
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

        # Should filter to only premium plan AND us-west region
        self.assertEqual(control_result.count, 250)
        self.assertEqual(test_result.count, 375)
        self.assertEqual(control_result.absolute_exposure, 7)
        self.assertEqual(test_result.absolute_exposure, 9)

    @snapshot_clickhouse_queries
    def test_query_runner_data_warehouse_metric_with_no_properties(self):
        """Test that data warehouse metrics work without any property filters (baseline behavior)"""
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
                # No properties or fixedProperties
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

        # Should include all data (no filters)
        self.assertEqual(control_result.count, 650)
        self.assertEqual(test_result.count, 1150)
        self.assertEqual(control_result.absolute_exposure, 7)
        self.assertEqual(test_result.absolute_exposure, 9)
