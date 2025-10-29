import json
import typing as t
import asyncio
import datetime as dt
import operator

from django.conf import settings

from posthog.batch_exports.service import BackfillDetails, BatchExportModel, BatchExportSchema
from posthog.temporal.common.clickhouse import ClickHouseClient

from products.batch_exports.backend.temporal.destinations.s3_batch_export import (
    COMPRESSION_EXTENSIONS,
    FILE_FORMAT_EXTENSIONS,
    s3_default_fields,
)
from products.batch_exports.backend.temporal.record_batch_model import SessionsRecordBatchModel
from products.batch_exports.backend.temporal.spmc import Producer, RecordBatchQueue
from products.batch_exports.backend.tests.temporal.utils.records import get_record_batch_from_queue
from products.batch_exports.backend.tests.temporal.utils.s3 import read_parquet_from_s3, read_s3_data_as_json

COMPRESSION_OPTIONS = [*COMPRESSION_EXTENSIONS.keys(), None]


async def assert_files_in_s3(s3_compatible_client, bucket_name, key_prefix, file_format, compression, json_columns):
    """Assert that there are files in S3 under key_prefix and return the combined contents, and the keys of files found."""
    if file_format == "Arrow":
        expected_file_extension = "arrow"
    else:
        expected_file_extension = FILE_FORMAT_EXTENSIONS[file_format]
    if compression is not None:
        expected_file_extension = f"{expected_file_extension}.{COMPRESSION_EXTENSIONS[compression]}"

    objects = await s3_compatible_client.list_objects_v2(Bucket=bucket_name, Prefix=key_prefix)

    s3_data = []
    keys = []
    assert objects.get("KeyCount", 0) > 0
    assert "Contents" in objects
    for obj in objects["Contents"]:
        key = obj.get("Key")
        if not key.endswith(expected_file_extension):
            continue

        keys.append(key)

        if file_format == "Parquet":
            s3_data.extend(
                await read_parquet_from_s3(
                    s3_client=s3_compatible_client,
                    bucket_name=bucket_name,
                    key=key,
                    json_columns=json_columns,
                )
            )

        elif file_format == "Arrow":
            s3_object = await s3_compatible_client.get_object(Bucket=bucket_name, Key=key)
            data = await s3_object["Body"].read()
            s3_data.extend(data)
        elif file_format == "JSONLines":
            s3_object = await s3_compatible_client.get_object(Bucket=bucket_name, Key=key)
            data = await s3_object["Body"].read()
            s3_data.extend(read_s3_data_as_json(data, compression))
        else:
            raise ValueError(f"Unsupported file format: {file_format}")

    return s3_data, keys


async def assert_file_in_s3(s3_compatible_client, bucket_name, key_prefix, file_format, compression, json_columns):
    """Assert a file is in S3 and return its contents."""
    s3_data, keys = await assert_files_in_s3(
        s3_compatible_client, bucket_name, key_prefix, file_format, compression, json_columns
    )
    assert len(keys) == 1
    return s3_data


async def assert_no_files_in_s3(s3_compatible_client, bucket_name, key_prefix):
    """Assert that there are no files in S3 under key_prefix."""
    objects = await s3_compatible_client.list_objects_v2(Bucket=bucket_name, Prefix=key_prefix)
    assert len(objects.get("Contents", [])) == 0


async def read_json_file_from_s3(s3_compatible_client, bucket_name, key) -> list | dict:
    s3_object: dict = await s3_compatible_client.get_object(Bucket=bucket_name, Key=key)
    data = await s3_object["Body"].read()
    data = read_s3_data_as_json(data, None)
    return data[0]


MetricKind = t.Literal["success", "cancellation", "failure", "rows"]
MetricName = t.Literal["succeeded", "canceled", "failed", "rows_exported"]
ExpectedCount = int
ExpectedMetricsMap = dict[tuple[MetricKind, MetricName], ExpectedCount]


async def assert_metrics_in_clickhouse(
    clickhouse_client: ClickHouseClient,
    batch_export_id: str,
    expected_metrics: ExpectedMetricsMap,
):
    """Assert metrics are correctly ingested in ClickHouse.

    We read metrics ingested into `sharded_app_metrics2` and compare them with the
    provided `expected_metrics`.
    """
    query = """
            SELECT metric_kind, metric_name, count
            FROM sharded_app_metrics2
            WHERE app_source = 'batch_export'
            AND app_source_id = {{batch_export_id:String}}
            FORMAT JSONEachRow \
            """

    resp = await clickhouse_client.read_query(
        query,
        query_parameters={"batch_export_id": batch_export_id, "cluster_name": settings.CLICKHOUSE_CLUSTER},
    )

    iterations = 0
    while not resp and iterations < 10:
        await asyncio.sleep(1)
        resp = await clickhouse_client.read_query(
            query,
            query_parameters={"batch_export_id": batch_export_id, "cluster_name": settings.CLICKHOUSE_CLUSTER},
        )

        iterations += 1

    if not resp:
        raise ValueError(f"Metrics for batch export '{batch_export_id}' not found")

    ingested_metrics = [json.loads(line) for line in resp.split(b"\n") if line]
    for ingested_metric in ingested_metrics:
        ingested_metric_kind, ingested_metric_name = ingested_metric["metric_kind"], ingested_metric["metric_name"]
        ingested_count = int(ingested_metric["count"])

        try:
            expected_count = expected_metrics[(ingested_metric_kind, ingested_metric_name)]
        except KeyError:
            raise ValueError(f"Ingested unexpected metric: '{ingested_metric_kind}'")

        assert (
            ingested_count == expected_count
        ), f"Ingested metric '{ingested_metric_kind}' with count {ingested_count} does not match expected {expected_count}"


async def assert_clickhouse_records_in_s3(
    s3_compatible_client,
    clickhouse_client: ClickHouseClient,
    bucket_name: str,
    key_prefix: str,
    team_id: int,
    data_interval_start: dt.datetime,
    data_interval_end: dt.datetime,
    exclude_events: list[str] | None = None,
    include_events: list[str] | None = None,
    batch_export_model: BatchExportModel | BatchExportSchema | None = None,
    compression: str | None = None,
    file_format: str = "JSONLines",
    backfill_details: BackfillDetails | None = None,
    allow_duplicates: bool = False,
    sort_key: str = "uuid",
):
    """Assert ClickHouse records are written to JSON in key_prefix in S3 bucket_name.

    Arguments:
        s3_compatible_client: An S3 client used to read records; can be MinIO if doing local testing.
        clickhouse_client: A ClickHouseClient used to read records that are expected to be exported.
        team_id: The ID of the team that we are testing for.
        bucket_name: S3 bucket name where records are exported to.
        key_prefix: S3 key prefix where records are exported to.
        data_interval_start: Start of the batch period for exported records.
        data_interval_end: End of the batch period for exported records.
        exclude_events: Event names to be excluded from the export.
        include_events: Event names to be included in the export.
        batch_export_schema: Custom schema used in the batch export.
        compression: Optional compression used in upload.
        file_format: Optional file format used in upload.
        backfill_details: Optional backfill details (this affects the query that is run to get the records).
        allow_duplicates: If True, allow duplicates when comparing records.
        sort_key: The key to sort the records by since they are not guaranteed to be in order.
    """
    json_columns = ("properties", "person_properties", "set", "set_once")
    s3_data = await assert_file_in_s3(
        s3_compatible_client=s3_compatible_client,
        bucket_name=bucket_name,
        key_prefix=key_prefix,
        file_format=file_format,
        compression=compression,
        json_columns=json_columns,
    )

    if batch_export_model is not None:
        if isinstance(batch_export_model, BatchExportModel):
            model_name = batch_export_model.name
            fields = batch_export_model.schema["fields"] if batch_export_model.schema is not None else None
            filters = batch_export_model.filters
            extra_query_parameters = (
                batch_export_model.schema["values"] if batch_export_model.schema is not None else None
            )
        else:
            model_name = "custom"
            fields = batch_export_model["fields"]
            filters = None
            extra_query_parameters = batch_export_model["values"]
    else:
        model_name = "events"
        extra_query_parameters = None
        fields = None
        filters = None

    if fields is not None:
        schema_column_names = [field["alias"] for field in fields]
    elif isinstance(batch_export_model, BatchExportModel) and batch_export_model.name == "persons":
        schema_column_names = [
            "team_id",
            "distinct_id",
            "person_id",
            "properties",
            "person_version",
            "person_distinct_id_version",
            "_inserted_at",
            "created_at",
            "is_deleted",
        ]
    else:
        schema_column_names = [field["alias"] for field in s3_default_fields()]

    if "_inserted_at" not in schema_column_names:
        schema_column_names.append("_inserted_at")

    expected_records = []

    queue = RecordBatchQueue()
    if model_name == "sessions":
        producer = Producer(model=SessionsRecordBatchModel(team_id))
    else:
        producer = Producer()
    producer_task = await producer.start(
        queue=queue,
        model_name=model_name,
        team_id=team_id,
        full_range=(data_interval_start, data_interval_end),
        done_ranges=[],
        fields=fields,
        filters=filters,
        destination_default_fields=s3_default_fields(),
        exclude_events=exclude_events,
        include_events=include_events,
        is_backfill=backfill_details is not None,
        backfill_details=backfill_details,
        extra_query_parameters=extra_query_parameters,
        order_columns=None,
    )
    while not queue.empty() or not producer_task.done():
        record_batch = await get_record_batch_from_queue(queue, producer_task)
        if record_batch is None:
            break

        for record in record_batch.to_pylist():
            expected_record = {}
            for k, v in record.items():
                if k in json_columns and v is not None:
                    expected_record[k] = json.loads(v)
                elif isinstance(v, dt.datetime):
                    expected_record[k] = v.isoformat()
                else:
                    expected_record[k] = v

            expected_records.append(expected_record)

    if "team_id" in schema_column_names:
        assert all(record["team_id"] == team_id for record in s3_data)

    if sort_key in schema_column_names:
        s3_data = sorted(s3_data, key=operator.itemgetter(sort_key))
        expected_records = sorted(expected_records, key=operator.itemgetter(sort_key))

    if isinstance(batch_export_model, BatchExportModel) and batch_export_model.name in ["events", "persons"]:
        assert set(s3_data[0].keys()) == set(schema_column_names)

    if allow_duplicates:
        s3_data = list({record["uuid"]: record for record in s3_data}.values())
    assert len(s3_data) == len(expected_records)

    first_value_matches = s3_data[0] == expected_records[0]
    assert first_value_matches
    all_match = s3_data == expected_records
    assert all_match
