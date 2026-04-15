import json
import asyncio
import datetime as dt
import dataclasses
import urllib.parse

from django.conf import settings

import aiohttp
import temporalio.activity
import temporalio.workflow
from structlog.contextvars import bind_contextvars
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger, get_write_only_logger

from products.batch_exports.backend.service import BatchExportField, BatchExportInsertInputs, WorkflowsBatchExportInputs
from products.batch_exports.backend.temporal.batch_exports import (
    OverBillingLimitError,
    StartBatchExportRunInputs,
    get_data_interval,
    start_batch_export_run,
)
from products.batch_exports.backend.temporal.pipeline.consumer import Consumer, run_consumer_from_stage
from products.batch_exports.backend.temporal.pipeline.entrypoint import execute_batch_export_using_internal_stage
from products.batch_exports.backend.temporal.pipeline.producer import Producer
from products.batch_exports.backend.temporal.pipeline.transformer import JSONLStreamTransformer
from products.batch_exports.backend.temporal.pipeline.types import BatchExportResult
from products.batch_exports.backend.temporal.spmc import RecordBatchQueue, wait_for_schema_or_producer
from products.batch_exports.backend.temporal.utils import (
    handle_non_retryable_errors,
    make_retryable_with_exponential_backoff,
)

LOGGER = get_write_only_logger(__name__)
EXTERNAL_LOGGER = get_logger("EXTERNAL")

NON_RETRYABLE_ERROR_TYPES: list[str] = [
    "NotFoundErrorGroup",
    "BadRequestErrorGroup",
    "HogFunctionErrorThresholdExceeded",
]
HOG_FUNCTION_API_PATH = "/api/projects/{team_id}/hog_functions/{hog_function_id}/batch_export_invocations"


def workflows_default_fields(batch_export_id: str) -> list[BatchExportField]:
    return [
        BatchExportField(expression="toString(uuid)", alias="uuid"),
        BatchExportField(expression="event", alias="event"),
        BatchExportField(expression="timestamp", alias="_inserted_at"),
        BatchExportField(expression="timestamp", alias="timestamp"),
        BatchExportField(expression="distinct_id", alias="distinct_id"),
        BatchExportField(expression="toString(person_id)", alias="person_id"),
        BatchExportField(expression="team_id", alias="project_id"),
        BatchExportField(expression="team_id", alias="team_id"),
        BatchExportField(expression="created_at", alias="created_at"),
        BatchExportField(expression="elements_chain", alias="elements_chain"),
        BatchExportField(expression="properties", alias="properties"),
        BatchExportField(expression="person_properties", alias="person_properties"),
        BatchExportField(expression="person_created_at", alias="person_created_at"),
        BatchExportField(expression="group0_properties", alias="group0_properties"),
        BatchExportField(expression="group1_properties", alias="group1_properties"),
        BatchExportField(expression="group2_properties", alias="group2_properties"),
        BatchExportField(expression="group3_properties", alias="group3_properties"),
        BatchExportField(expression="group4_properties", alias="group4_properties"),
        BatchExportField(expression="group0_created_at", alias="group0_created_at"),
        BatchExportField(expression="group1_created_at", alias="group1_created_at"),
        BatchExportField(expression="group2_created_at", alias="group2_created_at"),
        BatchExportField(expression="group3_created_at", alias="group3_created_at"),
        BatchExportField(expression="group4_created_at", alias="group4_created_at"),
        BatchExportField(expression=f"'{batch_export_id}'", alias="batch_export_id"),
    ]


class TooManyRequests(aiohttp.ClientResponseError):
    pass


class NotFound(aiohttp.ClientResponseError):
    pass


class BadRequest(aiohttp.ClientResponseError):
    pass


class InternalServerError(aiohttp.ClientResponseError):
    pass


class ServiceUnavailable(aiohttp.ClientResponseError):
    pass


class ClientResponseErrorGroup(ExceptionGroup[aiohttp.ClientResponseError]):
    """Base class for grouped HTTP errors."""

    def derive(self, excs):
        return ClientResponseErrorGroup(self.message, excs)


class BadRequestErrorGroup(ClientResponseErrorGroup):
    def derive(self, excs):
        return BadRequestErrorGroup(self.message, excs)


class NotFoundErrorGroup(ClientResponseErrorGroup):
    def derive(self, excs):
        return NotFoundErrorGroup(self.message, excs)


class HogFunctionErrorThresholdExceeded(Exception):
    """Raised when too many Hog Function executions fail with status=error."""

    def __init__(self, failed_count: int, total_count: int, latest_error: str | None = None):
        self.failed_count = failed_count
        self.total_count = total_count
        self.latest_error = latest_error

        message = f"Hog Function error rate above threshold: {failed_count}/{total_count} executions failed."
        if latest_error:
            message += f" Latest error message: '{latest_error}'"
        super().__init__(message)


def _make_exception(
    exc: type[aiohttp.ClientResponseError], err: aiohttp.ClientResponseError
) -> aiohttp.ClientResponseError:
    """Construct one of the specific exception classes from a generic error.

    Used to appease mypy, who doesn't like (*args, **kwargs) syntax.
    """
    return exc(err.request_info, err.history, status=err.status, message=err.message, headers=err.headers)


class WorkflowsConsumer(Consumer):
    """Consumer that posts each record as a Hog Function invocation to the CDP API.

    One HTTP POST request per record is issued concurrently via `request_task_group`, up
    to `max_concurrent_requests` in flight at a time.

    A 2xx response with a `{"status": "error", ...}` body is treated as a Hog Function
    execution error (the CDP call succeeded but the function itself failed).

    If the ratio of such execution errors to total handled records exceeds
    `hog_function_error_threshold_pct` — once at least
    `hog_function_error_threshold_min_records` records have been handled —
    the consumer aborts the run by raising a non-retryable
    `HogFunctionErrorThresholdExceeded` exception.
    """

    def __init__(
        self,
        url: str,
        hog_function_id: str,
        team_id: int,
        session: aiohttp.ClientSession,
        request_task_group: asyncio.TaskGroup,
        model: str = "events",
        max_concurrent_requests: int = 1_000,
        hog_function_error_threshold_pct: float = 0.5,
        hog_function_error_threshold_min_records: int = 100,
    ):
        super().__init__(model=model)

        path = HOG_FUNCTION_API_PATH.format(team_id=team_id, hog_function_id=hog_function_id)

        parsed = urllib.parse.urlparse(url)
        if not all((parsed.scheme, parsed.netloc)):
            raise ValueError(f"Invalid URL: {url}")

        self.url = urllib.parse.urljoin(url, path)
        self.session = session
        self.request_task_group = request_task_group
        self._requests_semaphore = asyncio.Semaphore(max_concurrent_requests)
        self.hog_function_error_threshold_pct = hog_function_error_threshold_pct
        self.hog_function_error_threshold_min_records = hog_function_error_threshold_min_records
        self.records_handled_count = 0
        self.latest_hog_function_error: str | None = None

    async def consume_chunk(self, data: bytes) -> None:
        post = make_retryable_with_exponential_backoff(
            self.post,
            retryable_exceptions=(
                InternalServerError,
                ServiceUnavailable,
                TooManyRequests,
                aiohttp.ServerDisconnectedError,
            ),
            # Retry forever on retryable errors
            max_attempts=None,
        )
        self.request_task_group.create_task(post(data))

    async def post(self, data: bytes) -> None:
        async with self._requests_semaphore:
            async with self.session.post(
                self.url,
                # Data is already JSON encoded, so we can't use json=data and must set
                # the header ourselves.
                data=b'{"clickhouse_event":' + data + b"}",
                headers={
                    "Content-Type": "application/json",
                },
            ) as response:
                try:
                    response.raise_for_status()
                except aiohttp.ClientResponseError as err:
                    response_body = await response.text()
                    self.logger.exception("Request failed", status=err.status, response_body=response_body)

                    match err.status:
                        case 404:
                            raise _make_exception(NotFound, err)
                        case 429:
                            raise _make_exception(TooManyRequests, err)
                        case n if n >= 400 and n < 500:
                            raise _make_exception(BadRequest, err)
                        case 503:
                            raise _make_exception(ServiceUnavailable, err)
                        case n if n >= 500:
                            raise _make_exception(InternalServerError, err)
                else:
                    response_body = await response.json()
                    self.records_handled_count += 1
                    if response_body.get("status") == "error":
                        errors = response_body.get("errors", [])
                        self.logger.warning("Hog Function execution failed", errors=errors)
                        self.records_failed_count += 1
                        if errors:
                            self.latest_hog_function_error = errors[-1]

                        if (
                            self.records_handled_count >= self.hog_function_error_threshold_min_records
                            and self.records_failed_count / self.records_handled_count
                            >= self.hog_function_error_threshold_pct
                        ):
                            raise HogFunctionErrorThresholdExceeded(
                                failed_count=self.records_failed_count,
                                total_count=self.records_handled_count,
                                latest_error=self.latest_hog_function_error,
                            )

    async def finalize_file(self):
        """Required by consumer interface."""
        pass

    async def finalize(self) -> None:
        """Required by consumer interface."""
        pass


@dataclasses.dataclass
class WorkflowsInsertInputs:
    """Inputs for Workflows."""

    batch_export: BatchExportInsertInputs
    url: str
    hog_function_id: str


@temporalio.activity.defn
@handle_non_retryable_errors(NON_RETRYABLE_ERROR_TYPES)
async def insert_into_workflows_activity_from_stage(inputs: WorkflowsInsertInputs) -> BatchExportResult:
    bind_contextvars(
        team_id=inputs.batch_export.team_id,
        destination="Workflows",
        data_interval_start=inputs.batch_export.data_interval_start,
        data_interval_end=inputs.batch_export.data_interval_end,
    )
    external_logger = EXTERNAL_LOGGER.bind()
    external_logger.info(
        "Batch exporting range %s - %s to Workflows API",
        inputs.batch_export.data_interval_start or "START",
        inputs.batch_export.data_interval_end or "END",
    )

    async with Heartbeater():
        queue = RecordBatchQueue(max_size_bytes=settings.BATCH_EXPORT_WORKFLOWS_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES)
        producer = Producer()
        assert inputs.batch_export.batch_export_id is not None
        producer_task = await producer.start(
            queue=queue,
            batch_export_id=inputs.batch_export.batch_export_id,
            data_interval_start=inputs.batch_export.data_interval_start,
            data_interval_end=inputs.batch_export.data_interval_end,
            max_record_batch_size_bytes=1024 * 1024 * 60,  # 60MB
        )

        record_batch_schema = await wait_for_schema_or_producer(queue, producer_task)
        if record_batch_schema is None:
            external_logger.info(
                "Batch export will finish early as there is no data matching specified filters in range %s - %s",
                inputs.batch_export.data_interval_start or "START",
                inputs.batch_export.data_interval_end or "END",
            )

            return BatchExportResult(records_completed=0, bytes_exported=0)

        transformer = JSONLStreamTransformer(max_workers=1)

        # NOTE: We initialize the TaskGroup first so that any errors in setting up
        # the consumer are not raised in the TaskGroup context.
        # TODO: The consumer should be refactored.
        tg = asyncio.TaskGroup()
        # The batch exports API resolves to a local address which our proxy blocks,
        # so we have to disable it by not reading the environment configuration.
        # nosemgrep: aiohttp-missing-trust-env
        async with aiohttp.ClientSession(
            trust_env=False,
            connector=aiohttp.TCPConnector(
                limit=settings.BATCH_EXPORT_WORKFLOWS_MAX_CONCURRENT_REQUESTS, keepalive_timeout=5
            ),
            headers={
                "X-Internal-Api-Secret": settings.INTERNAL_API_SECRET,
            },
        ) as session:
            consumer = WorkflowsConsumer(
                inputs.url,
                hog_function_id=inputs.hog_function_id,
                team_id=inputs.batch_export.team_id,
                session=session,
                request_task_group=tg,
                model=inputs.batch_export.batch_export_model.name
                if inputs.batch_export.batch_export_model
                else "events",
                max_concurrent_requests=settings.BATCH_EXPORT_WORKFLOWS_MAX_CONCURRENT_REQUESTS,
            )
            try:
                async with tg:
                    # TODO: Use multiple consumers
                    _ = await run_consumer_from_stage(
                        queue=queue,
                        consumer=consumer,
                        producer_task=producer_task,
                        transformer=transformer,
                        # the CDP API expects the JSON columns to be strings
                        json_columns=(),
                    )
            # NOTE: Nothing inside the TaskGroup raises an ExceptionGroup, so it is
            # impossible for a nested ExceptionGroup to be captured by except*.
            # Mypy is unable to figure this out, so we just ignore the errors. Otherwise
            # We would need a lot of extra code to flatten any groups (that do not
            # exist). If you are adding a TaskGroup inside this TaskGroup revisit this!
            except* BadRequest as exc_group:
                raise BadRequestErrorGroup(exc_group.message, exc_group.exceptions) from exc_group  # type: ignore[arg-type]
            except* NotFound as exc_group:
                raise NotFoundErrorGroup(exc_group.message, exc_group.exceptions) from exc_group  # type: ignore[arg-type]
            except* HogFunctionErrorThresholdExceeded:
                # Since we're making multiple requests in parallel, as soon as we hit the error threshold
                # we expect any new errors to also raise the same exception.
                # Therefore, rather than raising an ExceptionGroup we just re-raise the exception once,
                # but using the most recent values.
                exc = HogFunctionErrorThresholdExceeded(
                    failed_count=consumer.records_failed_count,
                    total_count=consumer.records_handled_count,
                    latest_error=consumer.latest_hog_function_error,
                )
                external_logger.exception(str(exc))
                raise exc

        return consumer.collect_result()


@temporalio.workflow.defn(name="workflows-export", failure_exception_types=[temporalio.workflow.NondeterminismError])
class WorkflowsBatchExportWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> "WorkflowsBatchExportWorkflow":
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return WorkflowsBatchExportWorkflow(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: WorkflowsBatchExportInputs):
        """Workflow implementation to export data to Workflows API."""
        is_backfill = inputs.get_is_backfill()
        is_earliest_backfill = inputs.get_is_earliest_backfill()
        data_interval_start, data_interval_end = get_data_interval(
            inputs.interval, inputs.data_interval_end, inputs.timezone
        )
        should_backfill_from_beginning = is_backfill and is_earliest_backfill

        start_batch_export_run_inputs = StartBatchExportRunInputs(
            team_id=inputs.team_id,
            batch_export_id=inputs.batch_export_id,
            data_interval_start=data_interval_start.isoformat() if not should_backfill_from_beginning else None,
            data_interval_end=data_interval_end.isoformat(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            backfill_id=inputs.backfill_details.backfill_id if inputs.backfill_details else None,
        )

        try:
            run_id = await temporalio.workflow.execute_activity(
                start_batch_export_run,
                start_batch_export_run_inputs,
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(seconds=60),
                    maximum_attempts=0,
                    non_retryable_error_types=["NotNullViolation", "IntegrityError", "OverBillingLimitError"],
                ),
            )
        except OverBillingLimitError:
            return

        batch_export_inputs = BatchExportInsertInputs(
            team_id=inputs.team_id,
            data_interval_start=data_interval_start.isoformat() if not should_backfill_from_beginning else None,
            data_interval_end=data_interval_end.isoformat(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            run_id=run_id,
            backfill_details=inputs.backfill_details,
            is_backfill=is_backfill,
            batch_export_model=inputs.batch_export_model,
            batch_export_schema=inputs.batch_export_schema,
            batch_export_id=inputs.batch_export_id,
            destination_default_fields=workflows_default_fields(inputs.batch_export_id),
        )

        insert_inputs = WorkflowsInsertInputs(
            batch_export=batch_export_inputs,
            url=settings.BATCH_EXPORT_WORKFLOWS_API_URL,
            hog_function_id=inputs.hog_function_id,
        )

        await execute_batch_export_using_internal_stage(
            insert_into_workflows_activity_from_stage,
            insert_inputs,  # type: ignore[arg-type]
            interval=inputs.interval,
            is_workflows=True,
        )
