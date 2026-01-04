import io
import gzip
import json
import uuid
import datetime as dt
import operator

from django.conf import settings

import brotli
import zstandard
import pyarrow.parquet as pq
from azure.storage.blob.aio import ContainerClient
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.batch_exports.service import BatchExportModel, BatchExportSchema
from posthog.temporal.tests.utils.models import afetch_batch_export_runs

from products.batch_exports.backend.temporal.batch_exports import finish_batch_export_run, start_batch_export_run
from products.batch_exports.backend.temporal.destinations.azure_blob_batch_export import (
    AzureBlobBatchExportInputs,
    AzureBlobBatchExportWorkflow,
    azure_blob_default_fields,
    insert_into_azure_blob_activity_from_stage,
)
from products.batch_exports.backend.temporal.pipeline.internal_stage import insert_into_internal_stage_activity
from products.batch_exports.backend.temporal.record_batch_model import SessionsRecordBatchModel
from products.batch_exports.backend.temporal.spmc import Producer, RecordBatchQueue
from products.batch_exports.backend.tests.temporal.utils.records import get_record_batch_from_queue


async def list_blobs(container: ContainerClient, prefix: str = "") -> list[str]:
    """Return blob names matching prefix."""
    names = []
    async for blob in container.list_blobs(name_starts_with=prefix):
        names.append(blob.name)
    return names


async def download_blob(container: ContainerClient, name: str) -> bytes:
    """Download blob content as bytes."""
    blob_client = container.get_blob_client(name)
    stream = await blob_client.download_blob()
    return await stream.readall()


def decompress(data: bytes, compression: str | None) -> bytes:
    """Decompress data based on compression type."""
    if compression is None:
        return data
    if compression == "gzip":
        return gzip.decompress(data)
    if compression == "brotli":
        return brotli.decompress(data)
    if compression == "zstd":
        return zstandard.ZstdDecompressor().decompress(data)
    raise ValueError(f"Unknown compression: {compression}")


def parse_jsonl(data: bytes) -> list[dict]:
    """Parse JSONLines data into list of records."""
    return [json.loads(line) for line in data.decode().strip().split("\n") if line]


def normalize_record(record: dict, json_columns: tuple[str, ...]) -> dict:
    """Format datetimes as ISO strings and parse JSON columns."""
    normalized = {}
    for key, value in record.items():
        if isinstance(value, dt.datetime):
            normalized[key] = value.isoformat()
        elif key in json_columns and value is not None:
            normalized[key] = json.loads(value)
        else:
            normalized[key] = value
    return normalized


def parse_parquet(data: bytes, json_columns: tuple[str, ...]) -> list[dict]:
    """Parse Parquet data, converting datetimes to isoformat and parsing JSON columns."""
    return [normalize_record(record, json_columns) for record in pq.read_table(io.BytesIO(data)).to_pylist()]


async def read_exported_records(
    container: ContainerClient,
    prefix: str,
    file_format: str,
    compression: str | None,
    json_columns: tuple[str, ...] = ("properties", "person_properties", "set", "set_once"),
) -> list[dict]:
    """Read all exported records from blobs matching prefix."""
    records = []
    for name in await list_blobs(container, prefix):
        if name.endswith("manifest.json"):
            continue

        data = await download_blob(container, name)

        if file_format == "Parquet":
            records.extend(parse_parquet(data, json_columns))
        else:
            decompressed = decompress(data, compression)
            records.extend(parse_jsonl(decompressed))

    return records


async def read_manifest(container: ContainerClient, prefix: str) -> dict | None:
    """Read manifest.json if it exists."""
    blobs = await list_blobs(container, prefix)
    manifest_blobs = [b for b in blobs if b.endswith("manifest.json")]

    if not manifest_blobs:
        return None

    data = await download_blob(container, manifest_blobs[0])
    return json.loads(data.decode())


def extract_model_configuration(
    batch_export_model: BatchExportModel | BatchExportSchema | None,
) -> tuple[str, list[dict] | None, list[dict] | None, dict | None]:
    """Extract (model_name, fields, filters, extra_query_parameters) from model config."""
    if batch_export_model is None:
        return "events", None, None, None

    if isinstance(batch_export_model, BatchExportModel):
        schema = batch_export_model.schema
        return (
            batch_export_model.name,
            schema["fields"] if schema else None,
            batch_export_model.filters,
            schema["values"] if schema else None,
        )

    return "custom", batch_export_model["fields"], None, batch_export_model["values"]


async def assert_clickhouse_records_in_azure_blob(
    container: ContainerClient,
    key_prefix: str,
    team_id: int,
    data_interval_start: dt.datetime,
    data_interval_end: dt.datetime,
    batch_export_model: BatchExportModel | BatchExportSchema | None = None,
    compression: str | None = None,
    file_format: str = "JSONLines",
    exclude_events: list[str] | None = None,
    include_events: list[str] | None = None,
):
    json_columns = ("properties", "person_properties", "set", "set_once")

    exported_records = await read_exported_records(
        container=container,
        prefix=key_prefix,
        file_format=file_format,
        compression=compression,
        json_columns=json_columns,
    )

    model_name, fields, filters, extra_query_parameters = extract_model_configuration(batch_export_model)

    expected_records = []
    queue = RecordBatchQueue()
    producer = Producer(model=SessionsRecordBatchModel(team_id)) if model_name == "sessions" else Producer()

    producer_task = await producer.start(
        queue=queue,
        model_name=model_name,
        team_id=team_id,
        full_range=(data_interval_start, data_interval_end),
        done_ranges=[],
        fields=fields,
        filters=filters,
        destination_default_fields=azure_blob_default_fields(),
        exclude_events=exclude_events,
        include_events=include_events,
        is_backfill=False,
        backfill_details=None,
        extra_query_parameters=extra_query_parameters,
        order_columns=None,
    )

    while not queue.empty() or not producer_task.done():
        record_batch = await get_record_batch_from_queue(queue, producer_task)
        if record_batch is None:
            break
        for record in record_batch.to_pylist():
            expected_records.append(normalize_record(record, json_columns))

    assert len(exported_records) > 0, "No records were exported to Azure Blob"
    assert len(expected_records) > 0, "No expected records were produced from Producer"
    assert len(exported_records) == len(
        expected_records
    ), f"Record count mismatch: exported {len(exported_records)}, expected {len(expected_records)}"

    expected_columns = list(expected_records[0].keys())

    if "team_id" in expected_columns:
        assert all(
            record.get("team_id") == team_id for record in exported_records
        ), f"Some exported records have wrong team_id (expected {team_id})"

    preferred_sort_keys = ("uuid", "session_id", "person_id")
    effective_sort_key = next((key for key in preferred_sort_keys if key in expected_columns), None)
    assert effective_sort_key, f"No valid sort key found. Expected one of {preferred_sort_keys} in {expected_columns}"

    exported_records = sorted(exported_records, key=operator.itemgetter(effective_sort_key))
    expected_records = sorted(expected_records, key=operator.itemgetter(effective_sort_key))

    assert exported_records == expected_records


TEST_AZURE_BLOB_MODELS: list[BatchExportModel | BatchExportSchema | None] = [
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


async def run_azure_blob_batch_export_workflow(
    team,
    batch_export_id: str,
    container_name: str,
    prefix: str,
    interval: str,
    data_interval_end: dt.datetime,
    integration_id: int,
    file_format: str = "JSONLines",
    compression: str | None = None,
    batch_export_model: BatchExportModel | None = None,
    batch_export_schema: BatchExportSchema | None = None,
):
    """Run the Azure Blob batch export workflow and return the run result."""
    workflow_id = str(uuid.uuid4())
    inputs = AzureBlobBatchExportInputs(
        team_id=team.pk,
        batch_export_id=batch_export_id,
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        container_name=container_name,
        prefix=prefix,
        file_format=file_format,
        compression=compression,
        integration_id=integration_id,
        batch_export_model=batch_export_model,
        batch_export_schema=batch_export_schema,
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[AzureBlobBatchExportWorkflow],
            activities=[
                start_batch_export_run,
                finish_batch_export_run,
                insert_into_internal_stage_activity,
                insert_into_azure_blob_activity_from_stage,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await activity_environment.client.execute_workflow(
                AzureBlobBatchExportWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=settings.BATCH_EXPORTS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
                execution_timeout=dt.timedelta(minutes=10),
            )

    runs = await afetch_batch_export_runs(batch_export_id=batch_export_id)
    assert len(runs) == 1
    return runs[0]
