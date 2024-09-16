from datetime import datetime
from freezegun import freeze_time
from posthog.hogql.modifiers import create_default_modifiers_for_team

from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.trends.trends_query_builder import TrendsQueryBuilder
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.schema import (
    BreakdownFilter,
    BreakdownType,
    ChartDisplayType,
    InsightDateRange,
    DataWarehouseNode,
    DataWarehouseEventsModifier,
    TrendsQuery,
    TrendsFilter,
)
from posthog.test.base import BaseTest
from posthog.warehouse.models import DataWarehouseTable, DataWarehouseCredential

from boto3 import resource
from botocore.config import Config
from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
    XDIST_SUFFIX,
)
import s3fs
from pyarrow import parquet as pq
import pyarrow as pa

from posthog.test.base import (
    ClickhouseTestMixin,
    snapshot_clickhouse_queries,
)
from posthog.hogql_queries.legacy_compatibility.filter_to_query import (
    clean_entity_properties,
)

TEST_BUCKET = "test_storage_bucket-posthog.hogql.datawarehouse.trendquery" + XDIST_SUFFIX


class TestTrendsDataWarehouseQuery(ClickhouseTestMixin, BaseTest):
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

    def get_response(self, trends_query: TrendsQuery):
        query_date_range = QueryDateRange(
            date_range=trends_query.dateRange,
            team=self.team,
            interval=trends_query.interval,
            now=datetime.now(),
        )

        timings = HogQLTimings()
        modifiers = create_default_modifiers_for_team(self.team)

        if isinstance(trends_query.series[0], DataWarehouseNode):
            series = trends_query.series[0]
            modifiers.dataWarehouseEventsModifiers = [
                DataWarehouseEventsModifier(
                    table_name=series.table_name,
                    timestamp_field=series.timestamp_field,
                    id_field=series.id_field,
                    distinct_id_field=series.distinct_id_field,
                )
            ]
            query_builder = TrendsQueryBuilder(
                trends_query=trends_query,
                team=self.team,
                query_date_range=query_date_range,
                series=trends_query.series[0],
                timings=timings,
                modifiers=modifiers,
            )
        else:
            raise Exception("Unsupported series type")

        query = query_builder.build_query()

        return execute_hogql_query(
            query_type="TrendsQuery",
            query=query,
            team=self.team,
            timings=timings,
            modifiers=modifiers,
        )

    def create_parquet_file(self):
        if not OBJECT_STORAGE_ACCESS_KEY_ID or not OBJECT_STORAGE_ACCESS_KEY_ID:
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

        id = pa.array(["1", "2", "3", "4"])
        created = pa.array([datetime(2023, 1, 1), datetime(2023, 1, 2), datetime(2023, 1, 3), datetime(2023, 1, 4)])
        prop_1 = pa.array(["a", "b", "c", "d"])
        prop_2 = pa.array(["e", "f", "g", "h"])
        names = ["id", "created", "prop_1", "prop_2"]

        pq.write_to_dataset(
            pa.Table.from_arrays([id, created, prop_1, prop_2], names=names),
            path_to_s3_object,
            filesystem=fs,
            use_dictionary=True,
            compression="snappy",
            version="2.0",
        )

        table_name = "test_table_1"

        credential = DataWarehouseCredential.objects.create(
            access_key=OBJECT_STORAGE_ACCESS_KEY_ID,
            access_secret=OBJECT_STORAGE_SECRET_ACCESS_KEY,
            team=self.team,
        )

        # TODO: use env vars
        DataWarehouseTable.objects.create(
            name=table_name,
            url_pattern=f"http://host.docker.internal:19000/{OBJECT_STORAGE_BUCKET}/{TEST_BUCKET}/*.parquet",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            columns={
                "id": "String",
                "created": "DateTime64(3, 'UTC')",
                "prop_1": "String",
                "prop_2": "String",
            },
            credential=credential,
        )

        return table_name

    @snapshot_clickhouse_queries
    def test_trends_data_warehouse(self):
        table_name = self.create_parquet_file()

        trends_query = TrendsQuery(
            kind="TrendsQuery",
            dateRange=InsightDateRange(date_from="2023-01-01"),
            series=[
                DataWarehouseNode(
                    id=table_name,
                    table_name=table_name,
                    id_field="id",
                    distinct_id_field="customer_email",
                    timestamp_field="created",
                )
            ],
        )

        with freeze_time("2023-01-07"):
            response = self.get_response(trends_query=trends_query)

        assert response.columns is not None
        assert set(response.columns).issubset({"date", "total"})
        assert response.results[0][1] == [1, 1, 1, 1, 0, 0, 0]

    @snapshot_clickhouse_queries
    def test_trends_entity_property(self):
        table_name = self.create_parquet_file()

        trends_query = TrendsQuery(
            kind="TrendsQuery",
            dateRange=InsightDateRange(date_from="2023-01-01"),
            series=[
                DataWarehouseNode(
                    id=table_name,
                    table_name=table_name,
                    id_field="id",
                    timestamp_field="created",
                    distinct_id_field="customer_email",
                    properties=clean_entity_properties([{"key": "prop_1", "value": "a", "type": "data_warehouse"}]),
                )
            ],
        )

        with freeze_time("2023-01-07"):
            response = self.get_response(trends_query=trends_query)

        assert response.columns is not None
        assert set(response.columns).issubset({"date", "total"})
        assert response.results[0][1] == [1, 0, 0, 0, 0, 0, 0]

    @snapshot_clickhouse_queries
    def test_trends_query_properties(self):
        table_name = self.create_parquet_file()

        trends_query = TrendsQuery(
            kind="TrendsQuery",
            dateRange=InsightDateRange(date_from="2023-01-01"),
            series=[
                DataWarehouseNode(
                    id=table_name,
                    table_name=table_name,
                    id_field="id",
                    distinct_id_field="customer_email",
                    timestamp_field="created",
                )
            ],
            properties=clean_entity_properties([{"key": "prop_1", "value": "a", "type": "data_warehouse"}]),
        )

        with freeze_time("2023-01-07"):
            response = self.get_response(trends_query=trends_query)

        assert response.columns is not None
        assert set(response.columns).issubset({"date", "total"})
        assert response.results[0][1] == [1, 1, 1, 1, 0, 0, 0]

    @snapshot_clickhouse_queries
    def test_trends_breakdown(self):
        table_name = self.create_parquet_file()

        trends_query = TrendsQuery(
            kind="TrendsQuery",
            dateRange=InsightDateRange(date_from="2023-01-01"),
            series=[
                DataWarehouseNode(
                    id=table_name,
                    table_name=table_name,
                    id_field="id",
                    distinct_id_field="customer_email",
                    timestamp_field="created",
                )
            ],
            breakdownFilter=BreakdownFilter(breakdown_type=BreakdownType.DATA_WAREHOUSE, breakdown="prop_1"),
        )

        with freeze_time("2023-01-07"):
            response = self.get_response(trends_query=trends_query)

        assert response.columns is not None
        assert set(response.columns).issubset({"date", "total", "breakdown_value"})
        assert len(response.results) == 4
        assert response.results[0][1] == [1, 0, 0, 0, 0, 0, 0]
        assert response.results[0][2] == "a"

        assert response.results[1][1] == [0, 1, 0, 0, 0, 0, 0]
        assert response.results[1][2] == "b"

        assert response.results[2][1] == [0, 0, 1, 0, 0, 0, 0]
        assert response.results[2][2] == "c"

        assert response.results[3][1] == [0, 0, 0, 1, 0, 0, 0]
        assert response.results[3][2] == "d"

    @snapshot_clickhouse_queries
    def test_trends_breakdown_with_property(self):
        table_name = self.create_parquet_file()

        trends_query = TrendsQuery(
            kind="TrendsQuery",
            dateRange=InsightDateRange(date_from="2023-01-01"),
            series=[
                DataWarehouseNode(
                    id=table_name,
                    table_name=table_name,
                    id_field="id",
                    distinct_id_field="customer_email",
                    timestamp_field="created",
                    properties=clean_entity_properties([{"key": "prop_1", "value": "a", "type": "data_warehouse"}]),
                )
            ],
            breakdownFilter=BreakdownFilter(breakdown_type=BreakdownType.DATA_WAREHOUSE, breakdown="prop_1"),
        )

        with freeze_time("2023-01-07"):
            response = self.get_response(trends_query=trends_query)

        assert response.columns is not None
        assert set(response.columns).issubset({"date", "total", "breakdown_value"})
        assert len(response.results) == 1
        assert response.results[0][1] == [1, 0, 0, 0, 0, 0, 0]
        assert response.results[0][2] == "a"

    def assert_column_names_with_display_type(self, display_type: ChartDisplayType):
        # KLUDGE: creating data on every variant
        table_name = self.create_parquet_file()

        trends_query = TrendsQuery(
            kind="TrendsQuery",
            dateRange=InsightDateRange(date_from="2023-01-01"),
            series=[
                DataWarehouseNode(
                    id=table_name,
                    table_name=table_name,
                    id_field="id",
                    distinct_id_field="customer_email",
                    timestamp_field="created",
                )
            ],
            trendsFilter=TrendsFilter(display=display_type),
        )

        with freeze_time("2023-01-07"):
            response = self.get_response(trends_query)

        assert response.columns is not None
        assert set(response.columns).issubset({"date", "total"})

    def test_column_names_with_display_type(self):
        self.assert_column_names_with_display_type(ChartDisplayType.ACTIONS_AREA_GRAPH)
        self.assert_column_names_with_display_type(ChartDisplayType.ACTIONS_BAR)
        self.assert_column_names_with_display_type(ChartDisplayType.ACTIONS_BAR_VALUE)
        self.assert_column_names_with_display_type(ChartDisplayType.ACTIONS_LINE_GRAPH)
        self.assert_column_names_with_display_type(ChartDisplayType.ACTIONS_PIE)
        self.assert_column_names_with_display_type(ChartDisplayType.BOLD_NUMBER)
        self.assert_column_names_with_display_type(ChartDisplayType.WORLD_MAP)
        self.assert_column_names_with_display_type(ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE)
