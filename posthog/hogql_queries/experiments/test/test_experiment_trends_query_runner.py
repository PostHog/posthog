from django.test import override_settings
from posthog.hogql.errors import QueryError
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
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
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

from boto3 import resource
from botocore.config import Config
from posthog.warehouse.models.credential import DataWarehouseCredential
from posthog.warehouse.models.table import DataWarehouseTable

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
        names = ["id", "timestamp", "distinct_id", "amount"]

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
                "timestamp": "DateTime64(3, 'UTC')",
                "distinct_id": "String",
                "amount": "Int64",
            },
            credential=credential,
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
                    properties={feature_flag_property: variant},
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
                    properties={feature_flag_property: variant},
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

    def test_query_runner_with_data_warehouse_series(self):
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
                    distinct_id_field="distinct_id",
                    id_field="distinct_id",
                    table_name=table_name,
                    timestamp_field="timestamp",
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
                    properties={feature_flag_property: variant},
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
            properties={feature_flag_property: "control"},
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
            properties={feature_flag_property: "control"},
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
                    distinct_id_field="distinct_id",
                    id_field="distinct_id",
                    table_name=table_name,
                    timestamp_field="timestamp",
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
            with self.assertRaises(QueryError) as context:
                query_runner.calculate()

        self.assertEqual(str(context.exception), 'Unknown table "invalid_table_name".')

    @freeze_time("2020-01-01T12:00:00Z")
    def test_query_runner_with_avg_math(self):
        feature_flag = self.create_feature_flag()
        experiment = self.create_experiment(feature_flag=feature_flag)

        count_query = TrendsQuery(series=[EventsNode(event="$pageview", math="avg")])
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

        prepared_count_query = query_runner.prepared_count_query
        self.assertEqual(prepared_count_query.series[0].math, "sum")

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
                        "properties": {ff_property: "control"},
                    },
                ],
                "user_control_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "control"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {ff_property: "control"},
                    },
                ],
                "user_test_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-03", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-04", "properties": {ff_property: "test"}},
                    {"event": "$feature_flag_called", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                ],
                "user_test_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                    {"event": "$pageview", "timestamp": "2020-01-03", "properties": {ff_property: "test"}},
                    {"event": "$feature_flag_called", "timestamp": "2020-01-02", "properties": {ff_property: "test"}},
                ],
            },
            self.team,
        )

        flush_persons_and_events()

        query_runner = ExperimentTrendsQueryRunner(
            query=ExperimentTrendsQuery(**experiment.metrics[0]["query"]), team=self.team
        )
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
