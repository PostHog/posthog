import asyncio
import datetime
from enum import Enum
from queue import Queue
import threading
from typing import Any, Optional

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.source import config
from posthog.warehouse.types import IncrementalField, IncrementalFieldType
from temporalio.client import Client
from temporalio.service import TLSConfig, RPCError


class TemporalIOResource(Enum):
    Workflows = "workflows"
    WorkflowHistories = "workflow_histories"


ENDPOINTS = (TemporalIOResource.Workflows.value, TemporalIOResource.WorkflowHistories.value)
INCREMENTAL_ENDPOINTS = (TemporalIOResource.Workflows.value, TemporalIOResource.WorkflowHistories.value)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    TemporalIOResource.Workflows.value: [
        {
            "label": "CloseTime",
            "type": IncrementalFieldType.DateTime,
            "field": "close_time",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    TemporalIOResource.WorkflowHistories.value: [
        {
            "label": "CloseTime",
            "type": IncrementalFieldType.DateTime,
            "field": "workflow_close_time",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}


@config.config
class TemporalIOSourceConfig(config.Config):
    host: str
    port: int
    namespace: str
    server_client_root_ca: str
    client_certificate: str
    client_private_key: str


def _async_iter_to_sync(async_iter):
    q = Queue()
    sentinel = object()

    async def runner():
        try:
            async for item in async_iter:
                q.put(item)
        finally:
            q.put(sentinel)

    def run_event_loop():
        asyncio.run(runner())

    threading.Thread(target=run_event_loop, daemon=True).start()

    while True:
        item = q.get()
        if item is sentinel:
            break
        yield item


def _sanitize(obj):
    def safe_convert(value):
        try:
            if isinstance(value, int | float | str | bool | dict | list | datetime.datetime):
                return value
            if value is None:
                return None
            return str(value)
        except Exception:
            return None

    return {k: safe_convert(v) for k, v in obj.items()}


async def _get_temporal_client(config: TemporalIOSourceConfig) -> Client:
    tls = TLSConfig(
        server_root_ca_cert=bytes(config.server_client_root_ca, "utf-8"),
        client_cert=bytes(config.client_certificate, "utf-8"),
        client_private_key=bytes(config.client_private_key, "utf-8"),
    )

    return await Client.connect(
        f"{config.host}:{config.port}",
        namespace=config.namespace,
        tls=tls,
    )


async def _get_workflows(
    config: TemporalIOSourceConfig, db_incremental_field_last_value: Optional[Any], is_incremental: bool
):
    query = "ORDER BY CloseTime asc"
    if is_incremental and db_incremental_field_last_value:
        if not isinstance(db_incremental_field_last_value, datetime.datetime):
            raise Exception(
                f"Incremental field last value should be a datetime, but instead is {db_incremental_field_last_value.__class__}"
            )

        query = f'CloseTime >= "{db_incremental_field_last_value.strftime("%Y-%m-%dT%H:%M:%S.000Z")}" {query}'

    client = await _get_temporal_client(config)
    workflows = client.list_workflows(query=query)
    async for item in workflows:
        yield _sanitize(item.__dict__)


async def _get_workflow_histories(
    config: TemporalIOSourceConfig, db_incremental_field_last_value: Optional[Any], is_incremental: bool
):
    query = "ORDER BY CloseTime asc"
    if is_incremental and db_incremental_field_last_value:
        if not isinstance(db_incremental_field_last_value, datetime.datetime):
            raise Exception(
                f"Incremental field last value should be a datetime, but instead is {db_incremental_field_last_value.__class__}"
            )

        query = f'CloseTime >= "{db_incremental_field_last_value.strftime("%Y-%m-%dT%H:%M:%S.000Z")}" {query}'

    client = await _get_temporal_client(config)
    workflows = client.list_workflows(query=query)
    async for item in workflows:
        try:
            history = await client.get_workflow_handle(item.id, run_id=item.run_id).fetch_history()
            history_dict = history.to_json_dict()
            events = history_dict["events"]
            for event in events:
                id = f"{item.id}-{item.run_id}-{event['taskId']}"
                event_with_ids = {
                    "id": id,
                    "workflow_id": item.id,
                    "run_id": item.run_id,
                    "workflow_start_time": item.start_time,
                    "workflow_close_time": item.close_time,
                    **event,
                }
                yield _sanitize(event_with_ids)
        except RPCError as e:
            # If temporal cloud retention period kicks in before we've grabbed the history, then we can get a 404 error for the workflow
            if "workflow execution not found for" in e.message:
                continue
            raise


def temporalio_source(
    config: TemporalIOSourceConfig,
    resource: TemporalIOResource,
    db_incremental_field_last_value: Optional[Any],
    is_incremental: bool = False,
) -> SourceResponse:
    if resource == TemporalIOResource.Workflows:

        async def get_workflows_iterator():
            return _get_workflows(config, db_incremental_field_last_value, is_incremental)

        workflows = _async_iter_to_sync(asyncio.run(get_workflows_iterator()))

        return SourceResponse(
            name=resource.value,
            items=workflows,
            primary_keys=["id"],
            partition_count=1,  # this enables partitioning
            partition_size=1,  # this enables partitioning
            partition_mode="datetime",
            partition_format="day",
            partition_keys=["close_time"],
        )
    elif resource == TemporalIOResource.WorkflowHistories:

        async def get_histories_iterator():
            return _get_workflow_histories(config, db_incremental_field_last_value, is_incremental)

        workflows = _async_iter_to_sync(asyncio.run(get_histories_iterator()))

        return SourceResponse(
            name=resource.value,
            items=workflows,
            primary_keys=["id"],
            partition_count=1,  # this enables partitioning
            partition_size=1,  # this enables partitioning
            partition_mode="datetime",
            partition_format="day",
            partition_keys=["workflow_close_time"],
        )
    else:
        raise Exception(f"TemporalIOResource '{resource}' not recognised")
