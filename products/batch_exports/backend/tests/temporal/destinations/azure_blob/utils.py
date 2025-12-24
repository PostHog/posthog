import io
import gzip
import json
import uuid
import datetime as dt
from dataclasses import dataclass

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
    insert_into_azure_blob_activity_from_stage,
)
from products.batch_exports.backend.temporal.pipeline.internal_stage import insert_into_internal_stage_activity


@dataclass
class ModelConfig:
    json_columns: tuple[str, ...]
    sort_key: str


MODEL_CONFIGS = {
    "events": ModelConfig(
        json_columns=("properties", "person_properties", "set", "set_once"),
        sort_key="uuid",
    ),
    "persons": ModelConfig(
        json_columns=("properties",),
        sort_key="person_id",
    ),
    "sessions": ModelConfig(
        json_columns=(),
        sort_key="session_id",
    ),
}


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


def parse_parquet(data: bytes, json_columns: tuple[str, ...]) -> list[dict]:
    """Parse Parquet data, converting datetimes to isoformat and parsing JSON columns."""
    records = []
    for record in pq.read_table(io.BytesIO(data)).to_pylist():
        casted_record = {}
        for k, v in record.items():
            if isinstance(v, dt.datetime):
                casted_record[k] = v.isoformat()
            elif k in json_columns and v is not None:
                casted_record[k] = json.loads(v)
            else:
                casted_record[k] = v
        records.append(casted_record)
    return records


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


def _assert_events_match(exported_records: list[dict], generated_data: list[dict]):
    assert len(exported_records) == len(generated_data)
    exported_by_uuid = {r["uuid"]: r for r in exported_records}
    for event in generated_data:
        exported = exported_by_uuid.get(event["uuid"])
        assert exported is not None, f"Event {event['uuid']} not found"
        assert exported["event"] == event["event"]
        assert exported["distinct_id"] == event["distinct_id"]
        assert exported["team_id"] == event["team_id"]
        assert exported["properties"] == event["properties"]


def _assert_persons_match(exported_records: list[dict], generated_data: list[dict]):
    assert len(exported_records) == len(generated_data)
    exported_by_person_id = {r["person_id"]: r for r in exported_records}
    for person in generated_data:
        exported = exported_by_person_id.get(person["person_id"])
        assert exported is not None, f"Person {person['person_id']} not found"
        assert exported["team_id"] == person["team_id"]
        assert exported["distinct_id"] == person["distinct_id"]


def _assert_sessions_match(exported_records: list[dict], generated_events: list[dict]):
    assert len(exported_records) >= 1
    expected_session_ids = {e["properties"]["$session_id"] for e in generated_events if e.get("properties")}
    assert len(expected_session_ids) >= 1, "Test data must include events with $session_id"
    exported_session_ids = {r["session_id"] for r in exported_records}
    assert exported_session_ids.issubset(expected_session_ids) or expected_session_ids.issubset(exported_session_ids)


MODEL_ASSERTIONS = {
    "events": _assert_events_match,
    "persons": _assert_persons_match,
    "sessions": _assert_sessions_match,
}


async def assert_exported_data_matches_generated(
    container: ContainerClient,
    prefix: str,
    generated_data: list[dict],
    file_format: str = "JSONLines",
    compression: str | None = None,
    model_name: str = "events",
):
    """Assert exported data matches what was generated."""
    config = MODEL_CONFIGS[model_name]
    exported_records = await read_exported_records(container, prefix, file_format, compression, config.json_columns)
    MODEL_ASSERTIONS[model_name](exported_records, generated_data)


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
