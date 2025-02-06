from typing import cast
from django.test import override_settings
import pytest
from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
from posthog.models.cohort.cohort import Cohort
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.group.util import create_group
from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
    XDIST_SUFFIX,
)
from posthog.schema import (
    ExperimentDataWarehouseMetricConfig,
    ExperimentEventMetricConfig,
    ExperimentMetric,
    ExperimentMetricType,
    ExperimentQuery,
    ExperimentSignificanceCode,
    ExperimentTrendsQueryResponse,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
from freezegun import freeze_time
from django.utils import timezone
from datetime import datetime, timedelta
from posthog.test.test_journeys import journeys_for
from posthog.models.experiment import Experiment
from parameterized import parameterized
import s3fs
from pyarrow import parquet as pq
import pyarrow as pa
from boto3 import resource
from botocore.config import Config
from posthog.warehouse.models.credential import DataWarehouseCredential
from posthog.warehouse.models.join import DataWarehouseJoin
from posthog.warehouse.models.table import DataWarehouseTable

TEST_BUCKET = "test_storage_bucket-posthog.hogql.experiments.queryrunner" + XDIST_SUFFIX


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def teardown_method(self, method) -> None:
        s3 = resource(
            "s3",
            endpoint_url=OBJECT_STORAGE_ENDPOINT,
            aws_access_key_id=OBJECT_STORAGE_ACCESS_KEY_ID,
            aws_secret_access_key=OBJECT_STORAGE_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
        )
        bucket = s3.Bucket(OBJECT_STORAGE_BUCKET)
        bucket.objects.filter(Prefix=TEST_BUCKET).delete()

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
        else:
            start_date = timezone.make_aware(start_date)  # Make naive datetime timezone-aware
        if end_date is None:
            end_date = timezone.now() + timedelta(days=14)
        elif end_date is not None:
            end_date = timezone.make_aware(end_date)  # Make naive datetime timezone-aware
        return Experiment.objects.create(
            name=name,
            team=self.team,
            feature_flag=feature_flag,
            start_date=start_date,
            end_date=end_date,
        )

    def create_data_warehouse_table_with_usage(self):
        if not OBJECT_STORAGE_ACCESS_KEY_ID or not OBJECT_STORAGE_SECRET_ACCESS_KEY:
            raise Exception("Missing vars")

        fs = s3fs.S3FileSystem(
            client_kwargs={
                "region_name": "us-east-1",
                "endpoint_url": OBJECT_STORAGE_ENDPOINT,
                "aws_access_key_id": OBJECT_STORAGE_ACCESS_KEY_ID,
                "aws_secret_access_key": OBJECT_STORAGE_SECRET_ACCESS_KEY,
            },
        )

        path_to_s3_object = "s3://" + OBJECT_STORAGE_BUCKET + f"/{TEST_BUCKET}"

        table_data = [
            {"id": "1", "ds": "2023-01-01", "userid": "user_control_0", "usage": 1000},
            {"id": "2", "ds": "2023-01-02", "userid": "user_test_1", "usage": 500},
            {"id": "3", "ds": "2023-01-03", "userid": "user_test_2", "usage": 750},
            {"id": "4", "ds": "2023-01-04", "userid": "internal_test_1", "usage": 100000},
            {"id": "5", "ds": "2023-01-06", "userid": "user_test_3", "usage": 800},
            {"id": "6", "ds": "2023-01-07", "userid": "user_extra", "usage": 900},
        ]

        pq.write_to_dataset(
            pa.Table.from_pylist(table_data),
            path_to_s3_object,
            filesystem=fs,
            use_dictionary=True,
            compression="snappy",
        )

        table_name = "usage"

        credential = DataWarehouseCredential.objects.create(
            access_key=OBJECT_STORAGE_ACCESS_KEY_ID,
            access_secret=OBJECT_STORAGE_SECRET_ACCESS_KEY,
            team=self.team,
        )

        DataWarehouseTable.objects.create(
            name=table_name,
            url_pattern=f"http://host.docker.internal:19000/{OBJECT_STORAGE_BUCKET}/{TEST_BUCKET}/*.parquet",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            columns={
                "id": "String",
                "ds": "Date",
                "userid": "String",
                "usage": "Int64",
            },
            credential=credential,
        )

        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name=table_name,
            source_table_key="userid",
            joining_table_name="events",
            joining_table_key="properties.$user_id",
            field_name="events",
            configuration={"experiments_optimized": True, "experiments_timestamp_key": "ds"},
        )
        return table_name

    def create_data_warehouse_table_with_subscriptions(self):
        if not OBJECT_STORAGE_ACCESS_KEY_ID or not OBJECT_STORAGE_SECRET_ACCESS_KEY:
            raise Exception("Missing vars")

        fs = s3fs.S3FileSystem(
            client_kwargs={
                "region_name": "us-east-1",
                "endpoint_url": OBJECT_STORAGE_ENDPOINT,
                "aws_access_key_id": OBJECT_STORAGE_ACCESS_KEY_ID,
                "aws_secret_access_key": OBJECT_STORAGE_SECRET_ACCESS_KEY,
            },
        )

        path_to_s3_object = "s3://" + OBJECT_STORAGE_BUCKET + f"/{TEST_BUCKET}"

        credential = DataWarehouseCredential.objects.create(
            access_key=OBJECT_STORAGE_ACCESS_KEY_ID,
            access_secret=OBJECT_STORAGE_SECRET_ACCESS_KEY,
            team=self.team,
        )

        subscription_table_data = [
            {
                "subscription_id": "1",
                "subscription_created_at": datetime(2023, 1, 2),
                "subscription_customer_id": "1",
                "subscription_amount": 100,
            },
            {
                "subscription_id": "2",
                "subscription_created_at": datetime(2023, 1, 3),
                "subscription_customer_id": "2",
                "subscription_amount": 50,
            },
            {
                "subscription_id": "3",
                "subscription_created_at": datetime(2023, 1, 4),
                "subscription_customer_id": "3",
                "subscription_amount": 75,
            },
            {
                "subscription_id": "4",
                "subscription_created_at": datetime(2023, 1, 5),
                "subscription_customer_id": "4",
                "subscription_amount": 80,
            },
            {
                "subscription_id": "5",
                "subscription_created_at": datetime(2023, 1, 6),
                "subscription_customer_id": "5",
                "subscription_amount": 90,
            },
        ]

        pq.write_to_dataset(
            pa.Table.from_pylist(subscription_table_data),
            path_to_s3_object,
            filesystem=fs,
            use_dictionary=True,
            compression="snappy",
        )

        subscription_table_name = "subscriptions"

        DataWarehouseTable.objects.create(
            name=subscription_table_name,
            url_pattern=f"http://host.docker.internal:19000/{OBJECT_STORAGE_BUCKET}/{TEST_BUCKET}/*.parquet",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            columns={
                "subscription_id": "String",
                "subscription_created_at": "DateTime64(3, 'UTC')",
                "subscription_customer_id": "String",
                "subscription_amount": "Int64",
            },
            credential=credential,
        )

        customer_table_data = [
            {
                "customer_id": "1",
                "customer_created_at": datetime(2023, 1, 1),
                "customer_name": "John Doe",
                "customer_email": "john.doe@example.com",
            },
            {
                "customer_id": "2",
                "customer_created_at": datetime(2023, 1, 2),
                "customer_name": "Jane Doe",
                "customer_email": "jane.doe@example.com",
            },
            {
                "customer_id": "3",
                "customer_created_at": datetime(2023, 1, 3),
                "customer_name": "John Smith",
                "customer_email": "john.smith@example.com",
            },
            {
                "customer_id": "4",
                "customer_created_at": datetime(2023, 1, 6),
                "customer_name": "Jane Smith",
                "customer_email": "jane.smith@example.com",
            },
            {
                "customer_id": "5",
                "customer_created_at": datetime(2023, 1, 7),
                "customer_name": "John Doe Jr",
                "customer_email": "john.doejr@example.com",
            },
        ]

        pq.write_to_dataset(
            pa.Table.from_pylist(customer_table_data),
            path_to_s3_object,
            filesystem=fs,
            use_dictionary=True,
            compression="snappy",
        )

        customer_table_name = "customers"

        DataWarehouseTable.objects.create(
            name=customer_table_name,
            url_pattern=f"http://host.docker.internal:19000/{OBJECT_STORAGE_BUCKET}/{TEST_BUCKET}/*.parquet",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            columns={
                "customer_id": "String",
                "customer_created_at": "DateTime64(3, 'UTC')",
                "customer_name": "String",
                "customer_email": "String",
            },
            credential=credential,
        )

        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name=subscription_table_name,
            source_table_key="subscription_customer_id",
            joining_table_name=customer_table_name,
            joining_table_key="customer_id",
            field_name="subscription_customer",
        )

        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name=subscription_table_name,
            source_table_key="subscription_customer.customer_email",
            joining_table_name="events",
            joining_table_key="person.properties.email",
            field_name="events",
            configuration={"experiments_optimized": True, "experiments_timestamp_key": "subscription_created_at"},
        )

        return subscription_table_name

    @freeze_time("2020-01-01T12:00:00Z")
    @snapshot_clickhouse_queries
    def test_query_runner_standard_flow_v2_stats(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        experiment.stats_config = {"version": 2}
        experiment.save()

        ff_property = f"$feature/{feature_flag.key}"

        metric = ExperimentMetric(
            metric_type=ExperimentMetricType.COUNT,
            metric_config=ExperimentEventMetricConfig(event="$pageview"),
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
        self.assertEqual(query_runner.stats_version, 2)
        result = query_runner.calculate()

        self.assertEqual(len(result.variants), 2)
        for variant in result.variants:
            self.assertIn(variant.key, ["control", "test"])

        control_variant = next(v for v in result.variants if v.key == "control")
        test_variant = next(v for v in result.variants if v.key == "test")

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
        experiment = self.create_experiment(feature_flag=feature_flag)

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

        metric = ExperimentMetric(
            metric_type=ExperimentMetricType.COUNT,
            metric_config=ExperimentEventMetricConfig(event="$pageview"),
            filterTestAccounts=True,
        )

        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

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
                    properties={
                        "$feature_flag_response": variant,
                        "$feature_flag": feature_flag.key,
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
            with self.assertRaises(ValueError) as context:
                query_runner.calculate()

            self.assertEqual(context.exception.args[0], "Control variant not found in experiment results")
        else:
            result = query_runner.calculate()
            trend_result = cast(ExperimentTrendsQueryResponse, result)

            control_result = next(variant for variant in trend_result.variants if variant.key == "control")
            test_result = next(variant for variant in trend_result.variants if variant.key == "test")

            self.assertEqual(control_result.absolute_exposure, expected_results["control_absolute_exposure"])
            self.assertEqual(test_result.absolute_exposure, expected_results["test_absolute_exposure"])

        ## Run again with filterTestAccounts=False
        metric = ExperimentMetric(
            metric_type=ExperimentMetricType.COUNT,
            metric_config=ExperimentEventMetricConfig(event="$pageview"),
            filterTestAccounts=False,
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

        trend_result = cast(ExperimentTrendsQueryResponse, result)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        self.assertEqual(control_result.absolute_exposure, 14)
        self.assertEqual(test_result.absolute_exposure, 16)

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
                    "control_absolute_exposure": 8,
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
                    "control_absolute_exposure": 8,
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

        metric = ExperimentMetric(
            metric_type=ExperimentMetricType.CONTINUOUS,
            metric_config=ExperimentDataWarehouseMetricConfig(
                table_name=table_name,
                distinct_id_field="userid",
                id_field="id",
                timestamp_field="ds",
                math="avg",
                math_property="usage",
            ),
            filterTestAccounts=True,
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

        # "user_test_3" first exposure (feature_flag_property="control") is on 2023-01-03
        # "user_test_3" relevant exposure (feature_flag_property="test") is on 2023-01-04
        # "user_test_3" other event (feature_flag_property="control" is on 2023-01-05
        # "user_test_3" purchase is on 2023-01-06
        # "user_test_3" second exposure (feature_flag_property="control") is on 2023-01-09
        # "user_test_3" should fall into the "test" variant, not the "control" variant
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="distinct_test_3",
            properties={
                "$feature_flag_response": "control",
                feature_flag_property: "control",
                "$feature_flag": feature_flag.key,
                "$user_id": "user_test_3",
            },
            timestamp=datetime(2023, 1, 3),
        )
        _create_event(
            team=self.team,
            event="Some other event",
            distinct_id="distinct_test_3",
            properties={
                "$feature_flag_response": "control",
                feature_flag_property: "control",
                "$feature_flag": feature_flag.key,
                "$user_id": "user_test_3",
            },
            timestamp=datetime(2023, 1, 5),
        )
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="distinct_test_3",
            properties={
                "$feature_flag_response": "control",
                feature_flag_property: "control",
                "$feature_flag": feature_flag.key,
                "$user_id": "user_test_3",
            },
            timestamp=datetime(2023, 1, 9),
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
            with freeze_time("2023-01-07"), self.assertRaises(ValueError) as context:
                query_runner.calculate()

            self.assertEqual(context.exception.args[0], "Control variant not found in experiment results")
        else:
            with freeze_time("2023-01-07"):
                result = query_runner.calculate()

            trend_result = cast(ExperimentTrendsQueryResponse, result)

            self.assertEqual(len(result.variants), 2)

            control_result = next(variant for variant in trend_result.variants if variant.key == "control")
            test_result = next(variant for variant in trend_result.variants if variant.key == "test")

            self.assertEqual(control_result.absolute_exposure, filter_expected["control_absolute_exposure"])
            self.assertEqual(test_result.absolute_exposure, filter_expected["test_absolute_exposure"])

        # Run the query again without filtering
        metric = ExperimentMetric(
            metric_type=ExperimentMetricType.CONTINUOUS,
            metric_config=ExperimentDataWarehouseMetricConfig(
                table_name=table_name,
                distinct_id_field="userid",
                id_field="id",
                timestamp_field="ds",
                math="avg",
                math_property="usage",
            ),
            filterTestAccounts=False,
        )
        experiment_query = ExperimentQuery(
            experiment_id=experiment.id,
            kind="ExperimentQuery",
            metric=metric,
        )

        experiment.metrics = [metric.model_dump(mode="json")]
        experiment.save()

        query_runner = ExperimentQueryRunner(query=experiment_query, team=self.team)
        with freeze_time("2023-01-07"):
            result = query_runner.calculate()

        trend_result = cast(ExperimentTrendsQueryResponse, result)

        self.assertEqual(len(result.variants), 2)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        self.assertEqual(control_result.absolute_exposure, 8)
        self.assertEqual(test_result.absolute_exposure, 10)

    @pytest.mark.skip(reason="Doesn't work with the new query runner")
    def test_query_runner_with_data_warehouse_subscriptions_table(self):
        table_name = self.create_data_warehouse_table_with_subscriptions()

        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 1, 10),
        )

        feature_flag_property = f"$feature/{feature_flag.key}"

        metric = ExperimentMetric(
            metric_type=ExperimentMetricType.COUNT,
            metric_config=ExperimentDataWarehouseMetricConfig(
                table_name=table_name,
                distinct_id_field="subscription_customer_id",
                id_field="id",
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
            result = query_runner.calculate()

        trend_result = cast(ExperimentTrendsQueryResponse, result)

        self.assertEqual(len(result.variants), 2)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        self.assertEqual(control_result.count, 1)
        self.assertEqual(test_result.count, 3)
        self.assertEqual(control_result.absolute_exposure, 7)
        self.assertEqual(test_result.absolute_exposure, 9)
