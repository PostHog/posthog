from django.test import override_settings
from posthog.hogql_queries.experiments.experiment_trends_query_runner import ExperimentTrendsQueryRunner
from posthog.models.experiment import Experiment, ExperimentHoldout
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.schema import (
    DataWarehouseNode,
    EventsNode,
    ExperimentSignificanceCode,
    ExperimentTrendsQuery,
    ExperimentTrendsQueryResponse,
    TrendsQuery,
)
from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
    XDIST_SUFFIX,
)
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from freezegun import freeze_time
from typing import cast
from django.utils import timezone
from datetime import datetime, timedelta
from posthog.test.test_journeys import journeys_for
from rest_framework.exceptions import ValidationError
from posthog.constants import ExperimentNoResultsErrorKeys
import s3fs
from pyarrow import parquet as pq
import pyarrow as pa
import json
from flaky import flaky

from boto3 import resource
from botocore.config import Config
from posthog.warehouse.models.credential import DataWarehouseCredential
from posthog.warehouse.models.join import DataWarehouseJoin
from posthog.warehouse.models.table import DataWarehouseTable
from posthog.hogql.query import execute_hogql_query

TEST_BUCKET = "test_storage_bucket-posthog.hogql.datawarehouse.trendquery" + XDIST_SUFFIX


@override_settings(IN_UNIT_TESTING=True)
class TestExperimentTrendsQueryRunner(ClickhouseTestMixin, APIBaseTest):
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
        if end_date is None:
            end_date = timezone.now() + timedelta(days=14)
        return Experiment.objects.create(
            name=name,
            team=self.team,
            feature_flag=feature_flag,
            start_date=start_date,
            end_date=end_date,
        )

    def create_holdout_for_experiment(self, experiment: Experiment):
        holdout = ExperimentHoldout.objects.create(
            team=self.team,
            name="Test Experiment holdout",
        )
        holdout.filters = [{"properties": [], "rollout_percentage": 20, "variant": f"holdout-{holdout.id}"}]
        holdout.save()
        experiment.holdout = holdout
        experiment.save()
        return holdout

    def create_data_warehouse_table_with_payments(self):
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

        id = pa.array(["1", "2", "3", "4", "5"])
        timestamp = pa.array(
            [
                datetime(2023, 1, 1),
                datetime(2023, 1, 2),
                datetime(2023, 1, 3),
                datetime(2023, 1, 6),
                datetime(2023, 1, 7),
            ]
        )
        distinct_id = pa.array(["user_control_0", "user_test_1", "user_test_2", "user_test_3", "user_extra"])
        amount = pa.array([100, 50, 75, 80, 90])
        names = ["id", "dw_timestamp", "dw_distinct_id", "amount"]

        pq.write_to_dataset(
            pa.Table.from_arrays([id, timestamp, distinct_id, amount], names=names),
            path_to_s3_object,
            filesystem=fs,
            use_dictionary=True,
            compression="snappy",
            version="2.0",
        )

        table_name = "payments"

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
                "dw_timestamp": "DateTime64(3, 'UTC')",
                "dw_distinct_id": "String",
                "amount": "Int64",
            },
            credential=credential,
        )

        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name=table_name,
            source_table_key="dw_distinct_id",
            joining_table_name="events",
            joining_table_key="distinct_id",
            field_name="events",
            configuration={"experiments_optimized": True, "experiments_timestamp_key": "dw_timestamp"},
        )
        return table_name

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

        id = pa.array(["1", "2", "3", "4", "5", "6"])
        date = pa.array(["2023-01-01", "2023-01-02", "2023-01-03", "2023-01-04", "2023-01-06", "2023-01-07"])
        user_id = pa.array(
            ["user_control_0", "user_test_1", "user_test_2", "internal_test_1", "user_test_3", "user_extra"]
        )
        usage = pa.array([1000, 500, 750, 100000, 800, 900])
        names = ["id", "ds", "userid", "usage"]

        pq.write_to_dataset(
            pa.Table.from_arrays([id, date, user_id, usage], names=names),
            path_to_s3_object,
            filesystem=fs,
            use_dictionary=True,
            compression="snappy",
            version="2.0",
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

    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        feature_flag_property = f"$feature/{feature_flag.key}"
        count_query = TrendsQuery(series=[EventsNode(event="$pageview")])
        exposure_query = TrendsQuery(series=[EventsNode(event="$feature_flag_called")])

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=exposure_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        # Populate experiment events
        for variant, count in [("control", 11), ("test", 15)]:
            for i in range(count):
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_{variant}_{i}",
                    properties={feature_flag_property: variant},
                )

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
                )

        flush_persons_and_events()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        result = query_runner.calculate()

        self.assertEqual(len(result.variants), 2)

        control_result = next(variant for variant in result.variants if variant.key == "control")
        test_result = next(variant for variant in result.variants if variant.key == "test")

        self.assertEqual(control_result.count, 11)
        self.assertEqual(test_result.count, 15)
        self.assertEqual(control_result.absolute_exposure, 7)
        self.assertEqual(test_result.absolute_exposure, 9)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_with_custom_exposure(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        ff_property = f"$feature/{feature_flag.key}"
        count_query = TrendsQuery(series=[EventsNode(event="$pageview")])
        exposure_query = TrendsQuery(
            series=[EventsNode(event="custom_exposure_event", properties=[{"key": "valid_exposure", "value": "true"}])]
        )

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=exposure_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        journeys_for(
            {
                "user_control_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "control", "valid_exposure": "true"},
                    },
                ],
                "user_control_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "control", "valid_exposure": "true"},
                    },
                ],
                "user_test_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "test", "valid_exposure": "true"},
                    },
                ],
                "user_test_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "test", "valid_exposure": "true"},
                    },
                ],
                "user_out_of_control": [
                    {"event": "$pageview", "timestamp": "2020-01-02"},
                ],
                "user_out_of_control_exposure": [
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "control", "valid_exposure": "false"},
                    },
                ],
                "user_out_of_date_range": [
                    {"event": "$pageview", "timestamp": "2019-01-01", "properties": {ff_property: "control"}},
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2019-01-01",
                        "properties": {ff_property: "control", "valid_exposure": "true"},
                    },
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        result = query_runner.calculate()

        trend_result = cast(ExperimentTrendsQueryResponse, result)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        self.assertEqual(control_result.count, 3)
        self.assertEqual(test_result.count, 5)

        self.assertEqual(control_result.absolute_exposure, 2)
        self.assertEqual(test_result.absolute_exposure, 2)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_with_default_exposure(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        ff_property = f"$feature/{feature_flag.key}"
        count_query = TrendsQuery(series=[EventsNode(event="$pageview")])

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=None,  # No exposure query provided
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        journeys_for(
            {
                "user_control_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature_flag_response": "control", "$feature_flag": feature_flag.key},
                    },
                ],
                "user_control_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature_flag_response": "control", "$feature_flag": feature_flag.key},
                    },
                ],
                "user_test_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature_flag_response": "test", "$feature_flag": feature_flag.key},
                    },
                ],
                "user_test_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature_flag_response": "test", "$feature_flag": feature_flag.key},
                    },
                ],
                "user_out_of_control": [
                    {"event": "$pageview", "timestamp": "2020-01-02"},
                ],
                "user_out_of_control_exposure": [
                    {"event": "$feature_flag_called", "timestamp": "2020-01-02"},
                ],
                "user_out_of_date_range": [
                    {"event": "$pageview", "timestamp": "2019-01-01", "properties": {ff_property: "control"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2019-01-01",
                        "properties": {"$feature_flag_response": "control", "$feature_flag": feature_flag.key},
                    },
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        result = query_runner.calculate()

        trend_result = cast(ExperimentTrendsQueryResponse, result)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        self.assertEqual(control_result.count, 3)
        self.assertEqual(test_result.count, 5)

        self.assertEqual(control_result.absolute_exposure, 2)
        self.assertEqual(test_result.absolute_exposure, 2)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_with_holdout(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)
        holdout = self.create_holdout_for_experiment(experiment)

        feature_flag_property = f"$feature/{feature_flag.key}"
        count_query = TrendsQuery(series=[EventsNode(event="$pageview")])
        exposure_query = TrendsQuery(series=[EventsNode(event="$feature_flag_called")])

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=exposure_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        # Populate experiment events
        for variant, count in [("control", 11), ("test", 15), (f"holdout-{holdout.id}", 8)]:
            for i in range(count):
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"user_{variant}_{i}",
                    properties={feature_flag_property: variant},
                )

        # Populate exposure events
        for variant, count in [("control", 7), ("test", 9), (f"holdout-{holdout.id}", 4)]:
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
                )

        flush_persons_and_events()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        result = query_runner.calculate()

        self.assertEqual(len(result.variants), 3)

        control_result = next(variant for variant in result.variants if variant.key == "control")
        test_result = next(variant for variant in result.variants if variant.key == "test")
        holdout_result = next(variant for variant in result.variants if variant.key == f"holdout-{holdout.id}")

        self.assertEqual(control_result.count, 11)
        self.assertEqual(test_result.count, 15)
        self.assertEqual(holdout_result.count, 8)
        self.assertEqual(control_result.absolute_exposure, 7)
        self.assertEqual(test_result.absolute_exposure, 9)
        self.assertEqual(holdout_result.absolute_exposure, 4)

    def test_query_runner_with_data_warehouse_series_total_count(self):
        table_name = self.create_data_warehouse_table_with_payments()

        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 1, 10),
        )

        feature_flag_property = f"$feature/{feature_flag.key}"

        count_query = TrendsQuery(
            series=[
                DataWarehouseNode(
                    id=table_name,
                    distinct_id_field="dw_distinct_id",
                    id_field="id",
                    table_name=table_name,
                    timestamp_field="dw_timestamp",
                    math="total",
                )
            ]
        )
        exposure_query = TrendsQuery(series=[EventsNode(event="$feature_flag_called")])

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=exposure_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
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

        # "user_test_3" first exposure (feature_flag_property="control") is on 2023-01-03
        # "user_test_3" relevant exposure (feature_flag_property="test") is on 2023-01-04
        # "user_test_3" other event (feature_flag_property="control" is on 2023-01-05
        # "user_test_3" purchase is on 2023-01-06
        # "user_test_3" second exposure (feature_flag_property="control") is on 2023-01-09
        # "user_test_3" should fall into the "test" variant, not the "control" variant
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_test_3",
            properties={
                feature_flag_property: "control",
                "$feature_flag_response": "control",
                "$feature_flag": feature_flag.key,
            },
            timestamp=datetime(2023, 1, 3),
        )
        _create_event(
            team=self.team,
            event="Some other event",
            distinct_id="user_test_3",
            properties={feature_flag_property: "control"},
            timestamp=datetime(2023, 1, 5),
        )
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_test_3",
            properties={
                feature_flag_property: "control",
                "$feature_flag_response": "control",
                "$feature_flag": feature_flag.key,
            },
            timestamp=datetime(2023, 1, 9),
        )

        flush_persons_and_events()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        with freeze_time("2023-01-07"):
            result = query_runner.calculate()

        trend_result = cast(ExperimentTrendsQueryResponse, result)

        self.assertEqual(len(result.variants), 2)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        self.assertEqual(control_result.count, 1)
        self.assertEqual(test_result.count, 3)
        self.assertEqual(control_result.absolute_exposure, 9)
        self.assertEqual(test_result.absolute_exposure, 9)

    def test_query_runner_with_data_warehouse_series_avg_amount(self):
        table_name = self.create_data_warehouse_table_with_payments()

        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 1, 10),
        )

        feature_flag_property = f"$feature/{feature_flag.key}"

        count_query = TrendsQuery(
            series=[
                DataWarehouseNode(
                    id=table_name,
                    distinct_id_field="dw_distinct_id",
                    id_field="id",
                    table_name=table_name,
                    timestamp_field="dw_timestamp",
                    math="avg",
                    math_property="amount",
                    math_property_type="data_warehouse_properties",
                )
            ]
        )
        exposure_query = TrendsQuery(series=[EventsNode(event="$feature_flag_called")])

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=exposure_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
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

        # "user_test_3" first exposure (feature_flag_property="control") is on 2023-01-03
        # "user_test_3" relevant exposure (feature_flag_property="test") is on 2023-01-04
        # "user_test_3" other event (feature_flag_property="control" is on 2023-01-05
        # "user_test_3" purchase is on 2023-01-06
        # "user_test_3" second exposure (feature_flag_property="control") is on 2023-01-09
        # "user_test_3" should fall into the "test" variant, not the "control" variant
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_test_3",
            properties={
                "$feature_flag_response": "control",
                feature_flag_property: "control",
                "$feature_flag": feature_flag.key,
            },
            timestamp=datetime(2023, 1, 3),
        )
        _create_event(
            team=self.team,
            event="Some other event",
            distinct_id="user_test_3",
            properties={
                "$feature_flag_response": "control",
                feature_flag_property: "control",
                "$feature_flag": feature_flag.key,
            },
            timestamp=datetime(2023, 1, 5),
        )
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user_test_3",
            properties={
                "$feature_flag_response": "control",
                feature_flag_property: "control",
                "$feature_flag": feature_flag.key,
            },
            timestamp=datetime(2023, 1, 9),
        )

        flush_persons_and_events()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        with freeze_time("2023-01-07"):
            result = query_runner.calculate()

        trend_result = cast(ExperimentTrendsQueryResponse, result)

        self.assertEqual(len(result.variants), 2)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        control_insight = next(variant for variant in trend_result.insight if variant["breakdown_value"] == "control")
        test_insight = next(variant for variant in trend_result.insight if variant["breakdown_value"] == "test")

        self.assertEqual(control_result.count, 100)
        self.assertEqual(test_result.count, 205)
        self.assertEqual(control_result.absolute_exposure, 1)
        self.assertEqual(test_result.absolute_exposure, 3)

        self.assertEqual(
            control_insight["data"],
            [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
        )
        self.assertEqual(
            test_insight["data"],
            [0.0, 50.0, 125.0, 125.0, 125.0, 205.0, 205.0, 205.0, 205.0, 205.0],
        )

    def test_query_runner_with_data_warehouse_series_no_end_date_and_nested_id(self):
        table_name = self.create_data_warehouse_table_with_usage()

        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2023, 1, 1),
        )

        feature_flag_property = f"$feature/{feature_flag.key}"

        self.team.test_account_filters = [
            {
                "key": "email",
                "value": "@posthog.com",
                "operator": "not_icontains",
                "type": "person",
            },
            {
                "key": "$host",
                "type": "event",
                "value": "^(localhost|127\\.0\\.0\\.1)($|:)",
                "operator": "not_regex",
            },
        ]
        self.team.save()
        count_query = TrendsQuery(
            series=[
                DataWarehouseNode(
                    id=table_name,
                    distinct_id_field="userid",
                    id_field="id",
                    table_name=table_name,
                    timestamp_field="ds",
                    math="avg",
                    math_property="usage",
                    math_property_type="data_warehouse_properties",
                )
            ],
            filterTestAccounts=True,
        )
        exposure_query = TrendsQuery(series=[EventsNode(event="$feature_flag_called")], filterTestAccounts=True)

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=exposure_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
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

        _create_person(
            team=self.team,
            uuid="018f14b8-6cf3-7ffd-80bb-5ef1a9e4d328",
            distinct_ids=["018f14b8-6cf3-7ffd-80bb-5ef1a9e4d328", "internal_test_1"],
            properties={"email": "internal_test_1@posthog.com"},
        )

        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="internal_test_1",
            properties={
                feature_flag_property: "test",
                "$feature_flag_response": "test",
                "$feature_flag": feature_flag.key,
                "$user_id": "internal_test_1",
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

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        with freeze_time("2023-01-07"):
            # Build and execute the query to get the ClickHouse SQL
            queries = query_runner.count_query_runner.to_queries()
            response = execute_hogql_query(
                query_type="TrendsQuery",
                query=queries[0],
                team=query_runner.count_query_runner.team,
                modifiers=query_runner.count_query_runner.modifiers,
                limit_context=query_runner.count_query_runner.limit_context,
            )

            # Assert the expected join condition in the clickhouse SQL
            expected_join_condition = f"and(equals(events.team_id, {query_runner.count_query_runner.team.id}), equals(event, %(hogql_val_9)s), greaterOrEquals(timestamp, assumeNotNull(parseDateTime64BestEffortOrNull(%(hogql_val_10)s, 6, %(hogql_val_11)s))), lessOrEquals(timestamp, assumeNotNull(parseDateTime64BestEffortOrNull(%(hogql_val_12)s, 6, %(hogql_val_13)s))))) AS e__events ON"
            self.assertIn(
                expected_join_condition,
                str(response.clickhouse),
                "Please check to make sure the timestamp statements are included in the ASOF LEFT JOIN select statement. This may also fail if the placeholder numbers have changed.",
            )

            result = query_runner.calculate()

        trend_result = cast(ExperimentTrendsQueryResponse, result)

        self.assertEqual(len(result.variants), 2)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        control_insight = next(variant for variant in trend_result.insight if variant["breakdown_value"] == "control")
        test_insight = next(variant for variant in trend_result.insight if variant["breakdown_value"] == "test")

        self.assertEqual(control_result.count, 1000)
        self.assertEqual(test_result.count, 2050)
        self.assertEqual(control_result.absolute_exposure, 1)
        self.assertEqual(test_result.absolute_exposure, 3)

        self.assertEqual(
            control_insight["data"][:10],
            [1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0],
        )
        self.assertEqual(
            test_insight["data"][:10],
            [0.0, 500.0, 1250.0, 1250.0, 1250.0, 2050.0, 2050.0, 2050.0, 2050.0, 2050.0],
        )

        # Run the query again with filter_test_accounts=False
        # as a point of comparison to above
        count_query = TrendsQuery(
            series=[
                DataWarehouseNode(
                    id=table_name,
                    distinct_id_field="userid",
                    id_field="id",
                    table_name=table_name,
                    timestamp_field="ds",
                    math="avg",
                    math_property="usage",
                    math_property_type="data_warehouse_properties",
                )
            ],
            filterTestAccounts=False,
        )
        exposure_query = TrendsQuery(series=[EventsNode(event="$feature_flag_called")], filterTestAccounts=False)

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=exposure_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        with freeze_time("2023-01-07"):
            result = query_runner.calculate()

        trend_result = cast(ExperimentTrendsQueryResponse, result)

        self.assertEqual(len(result.variants), 2)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        control_insight = next(variant for variant in trend_result.insight if variant["breakdown_value"] == "control")
        test_insight = next(variant for variant in trend_result.insight if variant["breakdown_value"] == "test")

        self.assertEqual(control_result.count, 1000)
        self.assertEqual(test_result.count, 102050)
        self.assertEqual(control_result.absolute_exposure, 1)
        self.assertEqual(test_result.absolute_exposure, 4)

        self.assertEqual(
            control_insight["data"][:10],
            [1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0],
        )
        self.assertEqual(
            test_insight["data"][:10],
            [0.0, 500.0, 1250.0, 101250.0, 101250.0, 102050.0, 102050.0, 102050.0, 102050.0, 102050.0],
        )

    def test_query_runner_with_data_warehouse_series_expected_query(self):
        table_name = self.create_data_warehouse_table_with_payments()

        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 1, 10),
        )

        feature_flag_property = f"$feature/{feature_flag.key}"

        count_query = TrendsQuery(
            series=[
                DataWarehouseNode(
                    id=table_name,
                    distinct_id_field="dw_distinct_id",
                    id_field="id",
                    table_name=table_name,
                    timestamp_field="dw_timestamp",
                    math="total",
                )
            ]
        )
        exposure_query = TrendsQuery(series=[EventsNode(event="$feature_flag_called")])

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=exposure_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
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

        flush_persons_and_events()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        with freeze_time("2023-01-07"):
            # Build and execute the query to get the ClickHouse SQL
            queries = query_runner.count_query_runner.to_queries()
            response = execute_hogql_query(
                query_type="TrendsQuery",
                query=queries[0],
                team=query_runner.count_query_runner.team,
                modifiers=query_runner.count_query_runner.modifiers,
                limit_context=query_runner.count_query_runner.limit_context,
            )

            # Assert the expected join condition in the clickhouse SQL
            expected_join_condition = f"and(equals(events.team_id, {query_runner.count_query_runner.team.id}), equals(event, %(hogql_val_7)s), greaterOrEquals(timestamp, assumeNotNull(parseDateTime64BestEffortOrNull(%(hogql_val_8)s, 6, %(hogql_val_9)s))), lessOrEquals(timestamp, assumeNotNull(parseDateTime64BestEffortOrNull(%(hogql_val_10)s, 6, %(hogql_val_11)s))))) AS e__events ON"
            self.assertIn(
                expected_join_condition,
                str(response.clickhouse),
                "Please check to make sure the timestamp statements are included in the ASOF LEFT JOIN select statement. This may also fail if the placeholder numbers have changed.",
            )

            result = query_runner.calculate()

        trend_result = cast(ExperimentTrendsQueryResponse, result)

        self.assertEqual(len(result.variants), 2)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        self.assertEqual(control_result.count, 1)
        self.assertEqual(test_result.count, 3)
        self.assertEqual(control_result.absolute_exposure, 7)
        self.assertEqual(test_result.absolute_exposure, 9)

    def test_query_runner_with_invalid_data_warehouse_table_name(self):
        # parquet file isn't created, so we'll get an error
        table_name = "invalid_table_name"

        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(
            feature_flag=feature_flag,
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 1, 10),
        )

        count_query = TrendsQuery(
            series=[
                DataWarehouseNode(
                    id=table_name,
                    distinct_id_field="dw_distinct_id",
                    id_field="id",
                    table_name=table_name,
                    timestamp_field="dw_timestamp",
                )
            ]
        )
        exposure_query = TrendsQuery(series=[EventsNode(event="$feature_flag_called")])

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=exposure_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        with freeze_time("2023-01-07"):
            with self.assertRaises(KeyError) as context:
                query_runner.calculate()

        self.assertEqual(str(context.exception), "'invalid_table_name'")

    # Uses the same values as test_query_runner_with_data_warehouse_series_avg_amount for easy comparison
    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_with_avg_math(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        feature_flag_property = f"$feature/{feature_flag.key}"

        count_query = TrendsQuery(
            series=[
                EventsNode(event="purchase", math="avg", math_property="amount", math_property_type="event_properties")
            ]
        )
        exposure_query = TrendsQuery(series=[EventsNode(event="$feature_flag_called")])

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=exposure_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )

        # Populate exposure events - same as data warehouse test
        for variant, count in [("control", 1), ("test", 3)]:
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
                    timestamp=datetime(2020, 1, i + 1),
                )

        # Create purchase events with same amounts as data warehouse test
        # Control: 1 purchase of 100
        # Test: 3 purchases of 50, 75, and 80
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_control_0",
            properties={feature_flag_property: "control", "amount": 100},
            timestamp=datetime(2020, 1, 2),
        )

        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_test_1",
            properties={feature_flag_property: "test", "amount": 50},
            timestamp=datetime(2020, 1, 2),
        )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_test_2",
            properties={feature_flag_property: "test", "amount": 75},
            timestamp=datetime(2020, 1, 3),
        )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_test_3",
            properties={feature_flag_property: "test", "amount": 80},
            timestamp=datetime(2020, 1, 6),
        )

        flush_persons_and_events()

        prepared_count_query = query_runner.prepared_count_query
        self.assertEqual(prepared_count_query.series[0].math, "sum")

        result = query_runner.calculate()
        trend_result = cast(ExperimentTrendsQueryResponse, result)

        self.assertEqual(trend_result.stats_version, 1)
        self.assertEqual(trend_result.significant, False)
        self.assertEqual(trend_result.significance_code, ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE)
        self.assertEqual(trend_result.p_value, 1.0)

        self.assertEqual(len(result.variants), 2)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        control_insight = next(variant for variant in trend_result.insight if variant["breakdown_value"] == "control")
        test_insight = next(variant for variant in trend_result.insight if variant["breakdown_value"] == "test")

        self.assertEqual(control_result.count, 100)
        self.assertAlmostEqual(test_result.count, 205)
        self.assertEqual(control_result.absolute_exposure, 1)
        self.assertEqual(test_result.absolute_exposure, 3)

        self.assertEqual(
            control_insight["data"],
            [0.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
        )
        self.assertEqual(
            test_insight["data"],
            [0.0, 50.0, 125.0, 125.0, 125.0, 205.0, 205.0, 205.0, 205.0, 205.0, 205.0, 205.0, 205.0, 205.0, 205.0],
        )

    # Uses the same values as test_query_runner_with_data_warehouse_series_avg_amount for easy comparison
    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_with_avg_math_v2_stats(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        feature_flag_property = f"$feature/{feature_flag.key}"

        count_query = TrendsQuery(
            series=[
                EventsNode(event="purchase", math="avg", math_property="amount", math_property_type="event_properties")
            ],
        )
        exposure_query = TrendsQuery(series=[EventsNode(event="$feature_flag_called")])

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=exposure_query,
            stats_version=2,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )

        # Populate exposure events - same as data warehouse test
        for variant, count in [("control", 1), ("test", 3)]:
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
                    timestamp=datetime(2020, 1, i + 1),
                )

        # Create purchase events with same amounts as data warehouse test
        # Control: 1 purchase of 100
        # Test: 3 purchases of 50, 75, and 80
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_control_0",
            properties={feature_flag_property: "control", "amount": 100},
            timestamp=datetime(2020, 1, 2),
        )

        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_test_1",
            properties={feature_flag_property: "test", "amount": 50},
            timestamp=datetime(2020, 1, 2),
        )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_test_2",
            properties={feature_flag_property: "test", "amount": 75},
            timestamp=datetime(2020, 1, 3),
        )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_test_3",
            properties={feature_flag_property: "test", "amount": 80},
            timestamp=datetime(2020, 1, 6),
        )

        flush_persons_and_events()

        prepared_count_query = query_runner.prepared_count_query
        self.assertEqual(prepared_count_query.series[0].math, "sum")

        result = query_runner.calculate()
        trend_result = cast(ExperimentTrendsQueryResponse, result)

        self.assertEqual(trend_result.stats_version, 2)
        self.assertEqual(trend_result.significant, False)
        self.assertEqual(trend_result.significance_code, ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE)
        self.assertEqual(trend_result.p_value, 1.0)

        self.assertEqual(len(result.variants), 2)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        control_insight = next(variant for variant in trend_result.insight if variant["breakdown_value"] == "control")
        test_insight = next(variant for variant in trend_result.insight if variant["breakdown_value"] == "test")

        self.assertEqual(control_result.count, 100)
        self.assertAlmostEqual(test_result.count, 205)
        self.assertEqual(control_result.absolute_exposure, 1)
        self.assertEqual(test_result.absolute_exposure, 3)

        self.assertEqual(
            control_insight["data"],
            [0.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
        )
        self.assertEqual(
            test_insight["data"],
            [0.0, 50.0, 125.0, 125.0, 125.0, 205.0, 205.0, 205.0, 205.0, 205.0, 205.0, 205.0, 205.0, 205.0, 205.0],
        )

    @flaky(max_runs=10, min_passes=1)
    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_standard_flow(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        ff_property = f"$feature/{feature_flag.key}"
        count_query = TrendsQuery(series=[EventsNode(event="$pageview")])
        exposure_query = TrendsQuery(series=[EventsNode(event="$feature_flag_called")])

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=exposure_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
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

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
        self.assertEqual(query_runner.stats_version, 1)
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

        self.assertAlmostEqual(result.credible_intervals["control"][0], 0.5449, places=3)
        self.assertAlmostEqual(result.credible_intervals["control"][1], 4.3836, places=3)
        self.assertAlmostEqual(result.credible_intervals["test"][0], 1.1009, places=3)
        self.assertAlmostEqual(result.credible_intervals["test"][1], 5.8342, places=3)

        self.assertAlmostEqual(result.p_value, 1.0, places=3)

        self.assertAlmostEqual(result.probability["control"], 0.2549, places=2)
        self.assertAlmostEqual(result.probability["test"], 0.7453, places=2)

        self.assertEqual(result.significance_code, ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE)

        self.assertFalse(result.significant)

        self.assertEqual(len(result.variants), 2)

        self.assertEqual(control_variant.absolute_exposure, 2.0)
        self.assertEqual(control_variant.count, 3.0)
        self.assertEqual(control_variant.exposure, 1.0)

        self.assertEqual(test_variant.absolute_exposure, 2.0)
        self.assertEqual(test_variant.count, 5.0)
        self.assertEqual(test_variant.exposure, 1.0)

    @flaky(max_runs=10, min_passes=1)
    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_standard_flow_v2_stats(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        ff_property = f"$feature/{feature_flag.key}"
        count_query = TrendsQuery(series=[EventsNode(event="$pageview")])
        exposure_query = TrendsQuery(series=[EventsNode(event="$feature_flag_called")])

        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=exposure_query,
            stats_version=2,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
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

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
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

        self.assertAlmostEqual(result.credible_intervals["control"][0], 0.3633, places=3)
        self.assertAlmostEqual(result.credible_intervals["control"][1], 2.9224, places=3)
        self.assertAlmostEqual(result.credible_intervals["test"][0], 0.7339, places=3)
        self.assertAlmostEqual(result.credible_intervals["test"][1], 3.8894, places=3)

        self.assertAlmostEqual(result.p_value, 1.0, places=3)

        self.assertAlmostEqual(result.probability["control"], 0.2549, places=2)
        self.assertAlmostEqual(result.probability["test"], 0.7453, places=2)

        self.assertEqual(result.significance_code, ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE)

        self.assertFalse(result.significant)

        self.assertEqual(len(result.variants), 2)

        self.assertEqual(control_variant.absolute_exposure, 2.0)
        self.assertEqual(control_variant.count, 3.0)
        self.assertEqual(control_variant.exposure, 1.0)

        self.assertEqual(test_variant.absolute_exposure, 2.0)
        self.assertEqual(test_variant.count, 5.0)
        self.assertEqual(test_variant.exposure, 1.0)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_property_math_sum(self):
        self._test_query_runner_property_math(
            math="sum",
            expected_control={
                "count": 10,
                "absolute_exposure": 5,
                "data": [0.0, 0.0, 1.0, 3.0, 6.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            },
            expected_test={
                "count": 90,
                "absolute_exposure": 10,
                "data": [0.0, 0.0, 2.0, 6.0, 12.0, 20.0, 30.0, 42.0, 56.0, 72.0, 90.0, 90.0, 90.0, 90.0, 90.0],
            },
        )

    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_property_math_avg(self):
        self._test_query_runner_property_math(
            math="avg",
            expected_control={
                "count": 10,
                "absolute_exposure": 5,
                "data": [0.0, 0.0, 1.0, 3.0, 6.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            },
            expected_test={
                "count": 90,
                "absolute_exposure": 10,
                "data": [0.0, 0.0, 2.0, 6.0, 12.0, 20.0, 30.0, 42.0, 56.0, 72.0, 90.0, 90.0, 90.0, 90.0, 90.0],
            },
        )

    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_property_math_min(self):
        self._test_query_runner_property_math(
            math="min",
            expected_control={
                "count": 5,
                "absolute_exposure": 5,
                "data": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0],
            },
            expected_test={
                "count": 10,
                "absolute_exposure": 10,
                "data": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            },
        )

    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_property_math_max(self):
        self._test_query_runner_property_math(
            math="max",
            expected_control={
                "count": 5,
                "absolute_exposure": 5,
                "data": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0],
            },
            expected_test={
                "count": 10,
                "absolute_exposure": 10,
                "data": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            },
        )

    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_property_math_median(self):
        self._test_query_runner_property_math(
            math="median",
            expected_control={
                "count": 5,
                "absolute_exposure": 5,
                "data": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0],
            },
            expected_test={
                "count": 10,
                "absolute_exposure": 10,
                "data": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            },
        )

    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_property_math_p90(self):
        self._test_query_runner_property_math(
            math="p90",
            expected_control={
                "count": 5,
                "absolute_exposure": 5,
                "data": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0],
            },
            expected_test={
                "count": 10,
                "absolute_exposure": 10,
                "data": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            },
        )

    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_property_math_p95(self):
        self._test_query_runner_property_math(
            math="p95",
            expected_control={
                "count": 5,
                "absolute_exposure": 5,
                "data": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0],
            },
            expected_test={
                "count": 10,
                "absolute_exposure": 10,
                "data": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            },
        )

    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_property_math_p99(self):
        self._test_query_runner_property_math(
            math="p99",
            expected_control={
                "count": 5,
                "absolute_exposure": 5,
                "data": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0],
            },
            expected_test={
                "count": 10,
                "absolute_exposure": 10,
                "data": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            },
        )

    def _test_query_runner_property_math(self, math, expected_control, expected_test):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag, start_date=datetime(2020, 1, 1))

        feature_flag_property = f"$feature/{feature_flag.key}"

        # control values are 0, 1, 2, 3, 4
        # test values are 0, 2, 4, 6, 8, 10, 12, 14, 16, 18

        # Populate metric + exposure events
        for variant, count in [("control", 5), ("test", 10)]:
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
                    timestamp=datetime(2020, 1, i + 1),
                )
                _create_event(
                    team=self.team,
                    event="purchase",
                    distinct_id=f"user_{variant}_{i}",
                    properties={
                        feature_flag_property: variant,
                        "amount": i * (1 if variant == "control" else 2),
                    },
                    timestamp=datetime(2020, 1, i + 2),
                )

        count_query = TrendsQuery(
            series=[
                EventsNode(
                    event="purchase",
                    math=math,
                    math_property="amount",
                    math_property_type="event_properties",
                )
            ]
        )
        exposure_query = TrendsQuery(series=[EventsNode(event="$feature_flag_called")])
        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
            exposure_query=exposure_query,
        )

        experiment.metrics = [{"type": "primary", "query": experiment_query.model_dump()}]
        experiment.save()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )

        flush_persons_and_events()

        result = query_runner.calculate()

        trend_result = cast(ExperimentTrendsQueryResponse, result)

        self.assertEqual(len(result.variants), 2)

        control_result = next(variant for variant in trend_result.variants if variant.key == "control")
        test_result = next(variant for variant in trend_result.variants if variant.key == "test")

        control_insight = next(variant for variant in trend_result.insight if variant["breakdown_value"] == "control")
        test_insight = next(variant for variant in trend_result.insight if variant["breakdown_value"] == "test")

        self.assertEqual(control_result.count, expected_control["count"])
        self.assertEqual(test_result.count, expected_test["count"])
        self.assertEqual(control_result.absolute_exposure, expected_control["absolute_exposure"])
        self.assertEqual(test_result.absolute_exposure, expected_test["absolute_exposure"])

        self.assertEqual(
            control_insight["data"],
            expected_control["data"],
        )
        self.assertEqual(
            test_insight["data"],
            expected_test["data"],
        )

    @freeze_time("2020-01-01T12:00:00Z")
    def test_validate_event_variants_no_events(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        count_query = TrendsQuery(series=[EventsNode(event="$pageview")])
        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
        )

        query_runner = ExperimentTrendsQueryRunner(query=experiment_query, team=self.team)
        with self.assertRaises(ValidationError) as context:
            query_runner.calculate()

        expected_errors = json.dumps(
            {
                ExperimentNoResultsErrorKeys.NO_EVENTS: True,
                ExperimentNoResultsErrorKeys.NO_FLAG_INFO: True,
                ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: True,
                ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: True,
            }
        )
        self.assertEqual(cast(list, context.exception.detail)[0], expected_errors)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_validate_event_variants_no_control(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        ff_property = f"$feature/{feature_flag.key}"
        journeys_for(
            {
                "user_test": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        count_query = TrendsQuery(series=[EventsNode(event="$pageview")])
        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
        )

        query_runner = ExperimentTrendsQueryRunner(query=experiment_query, team=self.team)
        with self.assertRaises(ValidationError) as context:
            query_runner.calculate()

        expected_errors = json.dumps(
            {
                ExperimentNoResultsErrorKeys.NO_EVENTS: False,
                ExperimentNoResultsErrorKeys.NO_FLAG_INFO: False,
                ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: True,
                ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: False,
            }
        )
        self.assertEqual(cast(list, context.exception.detail)[0], expected_errors)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_validate_event_variants_no_test(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        ff_property = f"$feature/{feature_flag.key}"
        journeys_for(
            {
                "user_control": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        count_query = TrendsQuery(series=[EventsNode(event="$pageview")])
        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
        )

        query_runner = ExperimentTrendsQueryRunner(query=experiment_query, team=self.team)
        with self.assertRaises(ValidationError) as context:
            query_runner.calculate()

        expected_errors = json.dumps(
            {
                ExperimentNoResultsErrorKeys.NO_EVENTS: False,
                ExperimentNoResultsErrorKeys.NO_FLAG_INFO: False,
                ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: False,
                ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: True,
            }
        )
        self.assertEqual(cast(list, context.exception.detail)[0], expected_errors)

    @freeze_time("2020-01-01T12:00:00Z")
    def test_validate_event_variants_no_flag_info(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        journeys_for(
            {
                "user_no_flag_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02"},
                ],
                "user_no_flag_2": [
                    {"event": "$pageview", "timestamp": "2020-01-03"},
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        count_query = TrendsQuery(series=[EventsNode(event="$pageview")])
        experiment_query = ExperimentTrendsQuery(
            experiment_id=experiment.id,
            kind="ExperimentTrendsQuery",
            count_query=count_query,
        )

        query_runner = ExperimentTrendsQueryRunner(query=experiment_query, team=self.team)
        with self.assertRaises(ValidationError) as context:
            query_runner.calculate()

        expected_errors = json.dumps(
            {
                ExperimentNoResultsErrorKeys.NO_EVENTS: True,
                ExperimentNoResultsErrorKeys.NO_FLAG_INFO: True,
                ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: True,
                ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: True,
            }
        )
        self.assertEqual(cast(list, context.exception.detail)[0], expected_errors)
