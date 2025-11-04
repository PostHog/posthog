import json
import uuid
import typing as t
import asyncio
import datetime as dt
import operator

from django.conf import settings

import aioboto3
import botocore.exceptions
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.batch_exports.service import BackfillDetails, BatchExportModel, BatchExportSchema
from posthog.temporal.common.clickhouse import ClickHouseClient
from posthog.temporal.tests.utils.models import afetch_batch_export_runs

from products.batch_exports.backend.temporal.batch_exports import finish_batch_export_run, start_batch_export_run
from products.batch_exports.backend.temporal.destinations.s3_batch_export import (
    COMPRESSION_EXTENSIONS,
    S3BatchExportInputs,
    S3BatchExportWorkflow,
    insert_into_s3_activity_from_stage,
    s3_default_fields,
)
from products.batch_exports.backend.temporal.pipeline.internal_stage import insert_into_internal_stage_activity
from products.batch_exports.backend.temporal.record_batch_model import SessionsRecordBatchModel
from products.batch_exports.backend.temporal.spmc import Producer, RecordBatchQueue
from products.batch_exports.backend.tests.temporal.utils.records import get_record_batch_from_queue
from products.batch_exports.backend.tests.temporal.utils.s3 import assert_file_in_s3, assert_no_files_in_s3

COMPRESSION_OPTIONS = [*COMPRESSION_EXTENSIONS.keys(), None]

TEST_S3_MODELS: list[BatchExportModel | BatchExportSchema | None] = [
    BatchExportModel(
        name="a-custom-model",
        schema={
            "fields": [
                {"expression": "uuid", "alias": "uuid"},
                {"expression": "event", "alias": "my_event_name"},
                {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_0)s), '')", "alias": "browser"},
                {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_1)s), '')", "alias": "os"},
                {"expression": "nullIf(properties, '')", "alias": "all_properties"},
            ],
            "values": {"hogql_val_0": "$browser", "hogql_val_1": "$os"},
        },
    ),
    BatchExportModel(name="events", schema=None),
    BatchExportModel(
        name="events",
        schema=None,
        filters=[
            {"key": "$browser", "operator": "exact", "type": "event", "value": ["Chrome"]},
            {"key": "$os", "operator": "exact", "type": "event", "value": ["Mac OS X"]},
        ],
    ),
    BatchExportModel(name="persons", schema=None),
    BatchExportModel(name="sessions", schema=None),
    {
        "fields": [
            {"expression": "uuid", "alias": "uuid"},
            {"expression": "event", "alias": "my_event_name"},
            {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_0)s), '')", "alias": "browser"},
            {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_1)s), '')", "alias": "os"},
            {"expression": "nullIf(properties, '')", "alias": "all_properties"},
        ],
        "values": {"hogql_val_0": "$browser", "hogql_val_1": "$os"},
    },
    None,
]


async def check_valid_credentials() -> bool:
    """Check if there are valid AWS credentials in the environment."""
    session = aioboto3.Session()
    async with session.client("sts") as sts:
        try:
            await sts.get_caller_identity()
        except botocore.exceptions.ClientError:
            return False
        else:
            return True


def has_valid_credentials() -> bool:
    """Synchronous wrapper around check_valid_credentials."""
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(check_valid_credentials())


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


async def run_s3_batch_export_workflow(
    model: BatchExportModel | BatchExportSchema | None,
    ateam,
    batch_export_id,
    s3_destination_config,
    interval,
    data_interval_start,
    data_interval_end,
    clickhouse_client,
    s3_client,
    backfill_details: BackfillDetails | None = None,
    expect_no_data: bool = False,
):
    """Run the S3 batch export workflow and assert it completes successfully.

    This is a shared helper function used by tests for S3, GCS, and MinIO buckets.
    """
    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    exclude_events = s3_destination_config.get("exclude_events", None)
    file_format = s3_destination_config.get("file_format", "JSONLines")
    compression = s3_destination_config.get("compression", None)
    s3_key_prefix = s3_destination_config.get("prefix", None)
    bucket_name = s3_destination_config.get("bucket_name", None)

    expected_key_prefix = s3_key_prefix.format(
        table=batch_export_model.name if batch_export_model is not None else "events",
        year=data_interval_end.year,
        month=data_interval_end.strftime("%m"),
        day=data_interval_end.strftime("%d"),
        hour=data_interval_end.strftime("%H"),
        minute=data_interval_end.strftime("%M"),
        second=data_interval_end.strftime("%S"),
    )

    workflow_id = str(uuid.uuid4())
    inputs = S3BatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=batch_export_id,
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_model=batch_export_model,
        batch_export_schema=batch_export_schema,
        backfill_details=backfill_details,
        **s3_destination_config,
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[S3BatchExportWorkflow],
            activities=[
                start_batch_export_run,
                finish_batch_export_run,
                insert_into_internal_stage_activity,
                insert_into_s3_activity_from_stage,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await activity_environment.client.execute_workflow(
                S3BatchExportWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
                execution_timeout=dt.timedelta(minutes=10),
            )

    runs = await afetch_batch_export_runs(batch_export_id=batch_export_id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"

    if expect_no_data:
        assert run.records_completed == 0 or (
            isinstance(model, BatchExportModel)
            and model.name == "sessions"
            and run.records_completed is not None
            and run.records_completed <= 1
        )
        assert run.bytes_exported == 0
        await assert_no_files_in_s3(s3_client, bucket_name, expected_key_prefix)
        return run

    assert run.bytes_exported is not None
    assert run.bytes_exported > 0

    sort_key = "uuid"
    if isinstance(model, BatchExportModel) and model.name == "persons":
        sort_key = "person_id"
    elif isinstance(model, BatchExportModel) and model.name == "sessions":
        sort_key = "session_id"

    await assert_metrics_in_clickhouse(
        clickhouse_client,
        batch_export_id,
        {("success", "succeeded"): 1, ("rows", "rows_exported"): run.records_completed or 0},
    )

    await assert_clickhouse_records_in_s3(
        s3_compatible_client=s3_client,
        clickhouse_client=clickhouse_client,
        bucket_name=bucket_name,
        key_prefix=expected_key_prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        exclude_events=exclude_events,
        compression=compression,
        file_format=file_format,
        sort_key=sort_key,
        backfill_details=backfill_details,
    )
    return run
