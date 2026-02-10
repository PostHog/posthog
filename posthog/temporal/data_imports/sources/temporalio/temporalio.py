import base64
import asyncio
import datetime
import threading
import dataclasses
from enum import StrEnum
from queue import Queue
from typing import Any, Optional

from structlog.types import FilteringBoundLogger
from temporalio.client import Client
from temporalio.service import RPCError

from posthog.temporal.common.client import connect
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.generated_configs import TemporalIOSourceConfig

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType


class TemporalIOResource(StrEnum):
    Workflows = "workflows"
    WorkflowHistories = "workflow_histories"


ENDPOINTS = (TemporalIOResource.Workflows, TemporalIOResource.WorkflowHistories)
INCREMENTAL_ENDPOINTS = (TemporalIOResource.Workflows, TemporalIOResource.WorkflowHistories)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    TemporalIOResource.Workflows: [
        {
            "label": "CloseTime",
            "type": IncrementalFieldType.DateTime,
            "field": "close_time",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    TemporalIOResource.WorkflowHistories: [
        {
            "label": "CloseTime",
            "type": IncrementalFieldType.DateTime,
            "field": "workflow_close_time",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}


@dataclasses.dataclass
class TemporalIOResumeConfig:
    next_page_token: str  # Base64-encoded bytes for JSON serialization


def _async_iter_to_sync(async_iter):
    q: Queue[Any] = Queue(maxsize=5000)
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
            q.task_done()
            break

        yield item
        q.task_done()


def _sanitize(obj):
    """This converts some underlying non-serializable classes to their string representation"""

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


@dataclasses.dataclass
class FakeSettings:
    """Required to trick temporal.io client to think its reading from django settings"""

    SECRET_KEY: str


async def _get_temporal_client(config: TemporalIOSourceConfig) -> Client:
    return await connect(
        host=config.host,
        port=config.port,
        namespace=config.namespace,
        server_root_ca_cert=config.server_client_root_ca,
        client_cert=config.client_certificate,
        client_key=config.client_private_key,
        settings=FakeSettings(config.encryption_key)
        if config.encryption_key and len(config.encryption_key) > 0
        else None,
    )


async def _get_workflows(
    config: TemporalIOSourceConfig,
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool,
    resumable_source_manager: ResumableSourceManager[TemporalIOResumeConfig],
    logger: FilteringBoundLogger,
):
    query: str | None = None
    if should_use_incremental_field and db_incremental_field_last_value:
        if not isinstance(db_incremental_field_last_value, datetime.datetime):
            raise Exception(
                f"Incremental field last value should be a datetime, but instead is {db_incremental_field_last_value.__class__}"
            )

        query = f'CloseTime >= "{db_incremental_field_last_value.strftime("%Y-%m-%dT%H:%M:%S.000Z")}"'

    # Only use resume state for full-refresh syncs — the pagination token is tied
    # to a specific query, so it becomes invalid when incremental field values change.
    next_page_token: bytes | None = None
    if not should_use_incremental_field and resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            next_page_token = base64.b64decode(resume_config.next_page_token)
            logger.debug("TemporalIO: resuming from next_page_token")

    client = await _get_temporal_client(config)
    workflows = client.list_workflows(query=query, next_page_token=next_page_token)

    page_count = 0
    total_count = 0
    async for item in workflows:
        yield _sanitize(item.__dict__)
        total_count += 1

        # current_page_index is incremented by __anext__ before returning, so it
        # equals 1 on the first item of each new page. Save state at page
        # boundaries so we can resume from the next page if interrupted.
        if workflows.current_page_index == 1 and total_count > 1 and not should_use_incremental_field:
            page_count += 1
            if workflows.next_page_token:
                token_b64 = base64.b64encode(workflows.next_page_token).decode("utf-8")
                resumable_source_manager.save_state(TemporalIOResumeConfig(next_page_token=token_b64))
                logger.debug(f"TemporalIO: saved resume state after page {page_count} ({total_count} total workflows)")


async def _get_workflow_histories(
    config: TemporalIOSourceConfig,
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool,
    resumable_source_manager: ResumableSourceManager[TemporalIOResumeConfig],
    logger: FilteringBoundLogger,
):
    query: str | None = None
    if should_use_incremental_field and db_incremental_field_last_value:
        if not isinstance(db_incremental_field_last_value, datetime.datetime):
            raise Exception(
                f"Incremental field last value should be a datetime, but instead is {db_incremental_field_last_value.__class__}"
            )

        query = f'CloseTime >= "{db_incremental_field_last_value.strftime("%Y-%m-%dT%H:%M:%S.000Z")}"'

    next_page_token: bytes | None = None
    if not should_use_incremental_field and resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            next_page_token = base64.b64decode(resume_config.next_page_token)
            logger.debug("TemporalIO: resuming workflow histories from next_page_token")

    client = await _get_temporal_client(config)
    workflows = client.list_workflows(query=query, next_page_token=next_page_token)

    page_count = 0
    workflow_count = 0
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
            if "workflow execution not found for" in e.message:
                continue
            raise

        workflow_count += 1
        if workflows.current_page_index == 1 and workflow_count > 1 and not should_use_incremental_field:
            page_count += 1
            if workflows.next_page_token:
                token_b64 = base64.b64encode(workflows.next_page_token).decode("utf-8")
                resumable_source_manager.save_state(TemporalIOResumeConfig(next_page_token=token_b64))
                logger.debug(
                    f"TemporalIO: saved resume state after page {page_count} ({workflow_count} total workflow histories)"
                )


def temporalio_source(
    config: TemporalIOSourceConfig,
    resource: TemporalIOResource,
    db_incremental_field_last_value: Optional[Any],
    resumable_source_manager: ResumableSourceManager[TemporalIOResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    if resource == TemporalIOResource.Workflows:

        async def get_workflows_iterator():
            return _get_workflows(
                config, db_incremental_field_last_value, should_use_incremental_field, resumable_source_manager, logger
            )

        workflows = _async_iter_to_sync(asyncio.run(get_workflows_iterator()))

        return SourceResponse(
            name=resource.value,
            items=lambda: workflows,
            primary_keys=["id", "run_id"],
            partition_count=1,  # this enables partitioning
            partition_size=1,  # this enables partitioning
            partition_mode="datetime",
            partition_format="day",
            partition_keys=["close_time"],
            sort_mode="desc",
        )
    elif resource == TemporalIOResource.WorkflowHistories:

        async def get_histories_iterator():
            return _get_workflow_histories(
                config, db_incremental_field_last_value, should_use_incremental_field, resumable_source_manager, logger
            )

        workflows = _async_iter_to_sync(asyncio.run(get_histories_iterator()))

        return SourceResponse(
            name=resource.value,
            items=lambda: workflows,
            primary_keys=["id"],
            partition_count=1,  # this enables partitioning
            partition_size=1,  # this enables partitioning
            partition_mode="datetime",
            partition_format="day",
            partition_keys=["workflow_close_time"],
            sort_mode="desc",
        )
    else:
        raise Exception(f"TemporalIOResource '{resource}' not recognised")
