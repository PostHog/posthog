import json
import asyncio
from collections.abc import Coroutine
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from django.db.models import F, Q

import structlog
import posthoganalytics
import temporalio.common
import temporalio.activity
import temporalio.workflow
import temporalio.exceptions
from azure.core import exceptions as azure_exceptions
from openai import APIError as OpenAIAPIError

from posthog.clickhouse.query_tagging import Product, tag_queries
from posthog.exceptions_capture import capture_exception
from posthog.models import Action
from posthog.models.ai.pg_embeddings import INSERT_BULK_PG_EMBEDDINGS_SQL
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.clickhouse import ClickHouseClient, get_client
from posthog.temporal.common.utils import get_scheduled_start_time

from products.enterprise.backend.hogai.summarizers.chains import abatch_summarize_actions
from products.enterprise.backend.hogai.utils.embeddings import aembed_documents, get_async_azure_embeddings_client

logger = structlog.get_logger(__name__)


async def get_actions_qs(start_dt: datetime, offset: int | None = None, batch_size: int | None = None):
    filter_conditions = Q(
        # Only orgs that have accepted data processing
        team__organization__is_ai_data_processing_approved=True,
        # Only actions updated before the start date
        updated_at__lte=start_dt,
    ) & (
        # Never summarized actions but not deleted
        Q(last_summarized_at__isnull=True, deleted=False)
        # Actions updated after last summarization workflow
        | Q(updated_at__gte=F("last_summarized_at"))
        # The line below preserves the execution order of the workflow. Temporal workflows must be deterministic,
        # so activities can be executed in the same order in case of retries. If this line was removed, the execution
        # order with list slices would be non-deterministic, as the queryset would remove already processed actions.
        | Q(last_summarized_at=start_dt)
    )

    actions_to_summarize = Action.objects.filter(filter_conditions).order_by("id", "team_id", "updated_at")
    if offset is None and batch_size is None:
        return actions_to_summarize
    if offset is None or batch_size is None:
        raise ValueError("Cannot provide only offset or only batch_size")
    return actions_to_summarize[offset : offset + batch_size]


@dataclass
class GetApproximateActionsCountInputs:
    start_dt: str


@temporalio.activity.defn
async def get_approximate_actions_count(inputs: GetApproximateActionsCountInputs) -> int:
    """
    Retrieves the approximate count of actions to summarize. The action count can change
    during the sync (updated_at > start_dt). The count is needed for batch summarization.
    """
    qs = await get_actions_qs(datetime.fromisoformat(inputs.start_dt))
    return await qs.acount()


@dataclass
class BatchSummarizeActionsInputs:
    start_dt: str
    offset: int
    batch_size: int


@temporalio.activity.defn
async def batch_summarize_actions(inputs: BatchSummarizeActionsInputs):
    """
    Summarizes actions in batches and saves their summaries to the database.

    Args:
        inputs: Inputs for the activity.
    """
    workflow_start_dt = datetime.fromisoformat(inputs.start_dt)
    actions_to_summarize = await get_actions_qs(workflow_start_dt, inputs.offset, inputs.batch_size)
    actions = [action async for action in actions_to_summarize]

    logger.info(
        "Preparing to summarize actions",
        offset=inputs.offset,
        batch_size=inputs.batch_size,
        start_dt=inputs.start_dt,
        actions_count=len(actions),
    )

    summaries = await abatch_summarize_actions(
        actions,
        start_dt=inputs.start_dt,
        properties={"offset": inputs.offset, "batch_size": inputs.batch_size, "start_dt": inputs.start_dt},
    )
    models_to_update = []
    for action, maybe_summary in zip(actions, summaries):
        # If a few actions across the batch fail, we don't want to fail the entire workflow.
        if isinstance(maybe_summary, BaseException):
            # We know OpenAI APIs might be unavailable or have token or request limits exceeded.
            # Since we spawn up to 96 parallel requests here, we should expect some requests to fail,
            # so we can retry them later. It's not practical to cancel the other 95 requests if
            # one fails, but we can retry summarization later.
            if not isinstance(maybe_summary, OpenAIAPIError):
                capture_exception(maybe_summary, additional_properties={"action_id": action.id, "tag": "max_ai"})
            logger.exception("Error summarizing actions", error=maybe_summary, action_id=action.id)
            continue
        action.last_summarized_at = workflow_start_dt
        action.summary = maybe_summary
        models_to_update.append(action)

    await Action.objects.abulk_update(models_to_update, ["last_summarized_at", "summary"])


async def batch_embed_actions(
    actions: list[dict[str, Any]], batch_size: int
) -> list[tuple[dict[str, Any], list[float]]]:
    """
    Embed actions in batches in parallel.

    Args:
        actions: List of all actions to embed.
        batch_size: How many actions to embed in a single batch.

    Returns:
        List of tuples containing the action and its embedding.
    """
    logger.info(
        "Preparing to embed actions",
        actions_count=len(actions),
    )
    embeddings_client = get_async_azure_embeddings_client()

    filtered_batches = [
        [action for action in actions[i : i + batch_size] if action["summary"]]
        for i in range(0, len(actions), batch_size)
    ]
    embedding_requests = [
        aembed_documents(embeddings_client, [cast(str, action["summary"]) for action in action_batch])
        for action_batch in filtered_batches
    ]
    responses = await asyncio.gather(*embedding_requests, return_exceptions=True)

    successful_batches = []
    for action_batch, maybe_vector in zip(filtered_batches, responses):
        # Authentication exception is not retryable.
        if isinstance(maybe_vector, azure_exceptions.ClientAuthenticationError):
            raise maybe_vector
        # Rate limit raised, wait for a timeout.
        if isinstance(maybe_vector, azure_exceptions.HttpResponseError) and maybe_vector.status_code == 429:
            raise maybe_vector

        if isinstance(maybe_vector, BaseException):
            posthoganalytics.capture_exception(maybe_vector, properties={"tag": "max_ai"})
            logger.exception("Error embedding actions", error=maybe_vector)
            continue
        for action, embedding in zip(action_batch, maybe_vector):
            successful_batches.append((action, embedding))

    return successful_batches


async def sync_action_vectors(
    client: ClickHouseClient,
    actions_with_embeddings: list[tuple[dict[str, Any], list[float]]],
    insert_batch_size: int,
    workflow_start_dt: datetime,
    embedding_version: int | None = None,
):
    """
    Syncs action vectors to ClickHouse and updates the last synced timestamp.

    Args:
        actions_with_embeddings: List of tuples containing the action and its embedding.
        insert_batch_size: How many actions to insert in a single query to ClickHouse.
        workflow_start_dt: The start date of the workflow to set the timestamp to.
    """
    for i in range(0, len(actions_with_embeddings), insert_batch_size):
        batch = actions_with_embeddings[i : i + insert_batch_size]

        rows: list[tuple] = []
        for action, embedding in batch:
            properties = {
                "name": action["name"],
                "description": action["description"],
            }
            if embedding_version is not None:
                properties["embedding_version"] = embedding_version

            rows.append(
                (
                    "action",
                    action["team_id"],
                    action["id"],
                    embedding,
                    action["summary"],
                    json.dumps(properties),
                    1 if action["deleted"] else 0,
                )
            )

        if not rows:
            break

        await client.execute_query(INSERT_BULK_PG_EMBEDDINGS_SQL, *rows)

        bulk_update = []
        for action, _ in batch:
            action_model = Action(id=action["id"], embedding_last_synced_at=workflow_start_dt)
            if embedding_version is not None:
                action_model.embedding_version = embedding_version
            bulk_update.append(action_model)

        await Action.objects.abulk_update(
            bulk_update,
            (
                ["embedding_last_synced_at", "embedding_version"]
                if embedding_version is not None
                else ["embedding_last_synced_at"]
            ),
        )


@dataclass
class BatchEmbedAndSyncActionsInputs:
    start_dt: str
    insert_batch_size: int
    embeddings_batch_size: int
    max_parallel_requests: int
    embedding_version: int | None = None


@dataclass
class BatchEmbedAndSyncActionsOutputs:
    has_more: bool


@temporalio.activity.defn
async def batch_embed_and_sync_actions(inputs: BatchEmbedAndSyncActionsInputs) -> BatchEmbedAndSyncActionsOutputs:
    """
    Embeds actions in batches and syncs them to ClickHouse.

    Args:
        inputs: Inputs for the activity.

    Returns:
        Outputs for the activity: whether there are more actions to sync.
    """
    tag_queries(product=Product.MAX_AI)
    workflow_start_dt = datetime.fromisoformat(inputs.start_dt)

    query = (
        # Include only updated actions.
        Q(last_summarized_at__gt=F("embedding_last_synced_at"))
        # Or actions that haven't never been synced but have summaries.
        | (Q(embedding_last_synced_at__isnull=True) & Q(last_summarized_at__isnull=False))
    )

    # Backward compatibility: Temporal workflows must be deterministic, so we won't
    # look for embedding versions if the version is not set in the inputs.
    if inputs.embedding_version is not None:
        query |= (
            # Or actions that don't have an embedding version.
            Q(embedding_version__isnull=True)
            # Or actions with an old embedding version.
            | Q(embedding_version__lt=inputs.embedding_version)
        )

    actions_to_sync_qs = (
        Action.objects.filter(
            Q(
                # Include only actions that have been summarized.
                last_summarized_at__lte=workflow_start_dt,
                # And they must have a summary to prevent infinite loops.
                summary__isnull=False,
            )
            & query
        )
        .order_by("updated_at", "id")
        .values("team_id", "id", "summary", "name", "description", "deleted")
    )

    actions_batch_size = inputs.embeddings_batch_size * inputs.max_parallel_requests
    offset = 0
    embedded_actions: list[tuple[dict[str, Any], list[float]]] = []

    while offset < inputs.insert_batch_size:
        temporalio.activity.heartbeat()

        qs_slice = [
            cast(dict[str, Any], action) async for action in actions_to_sync_qs[offset : offset + actions_batch_size]
        ]
        if not qs_slice:
            break

        offset += len(qs_slice)
        embedded_actions += await batch_embed_actions(qs_slice, inputs.embeddings_batch_size)

        # Exit early if we don't have enough actions to fill the batch.
        if len(qs_slice) != actions_batch_size:
            break

    if not embedded_actions:
        return BatchEmbedAndSyncActionsOutputs(has_more=False)

    logger.info(
        "Syncing action vectors",
        insert_batch_size=inputs.insert_batch_size,
        start_dt=inputs.start_dt,
        actions_count=len(embedded_actions),
    )
    temporalio.activity.heartbeat()

    async with get_client() as client:
        await sync_action_vectors(
            client, embedded_actions, inputs.insert_batch_size, workflow_start_dt, inputs.embedding_version
        )

    # Returning True as we can't tell that there are no more actions to sync without doing one additional run.
    return BatchEmbedAndSyncActionsOutputs(has_more=True)


@dataclass
class EmbeddingVersion:
    """The version of the embedding model to use per a domain."""

    actions: int


@dataclass
class SyncVectorsInputs:
    start_dt: str | None = None
    """Start date for the sync if the workflow is not triggered by a schedule."""
    summarize_batch_size: int = 96
    """How many elements to summarize in a single batch."""
    embed_batch_size: int = 96
    """How many elements to embed in a single batch."""
    max_parallel_requests: int = 5
    """How many parallel requests to send to vendors."""
    insert_batch_size: int = 10000
    """How many rows to insert in a single query to ClickHouse."""
    delay_between_batches: int = 60
    """How many seconds to wait between batches."""
    embedding_version: int | None = None
    """DEPRECATED: use `embedding_versions` instead. Kept for backward compatibility."""
    embedding_versions: EmbeddingVersion | None = None
    """The versions of the embedding model to use per a domain."""


@temporalio.workflow.defn(name="ai-sync-vectors")
class SyncVectorsWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> SyncVectorsInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return SyncVectorsInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: SyncVectorsInputs):
        start_dt_str = inputs.start_dt or get_scheduled_start_time().isoformat()

        approximate_actions_count = await temporalio.workflow.execute_activity(
            get_approximate_actions_count,
            GetApproximateActionsCountInputs(start_dt=start_dt_str),
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=temporalio.common.RetryPolicy(initial_interval=timedelta(seconds=30), maximum_attempts=3),
        )

        tasks = []
        for i in range(0, approximate_actions_count, inputs.summarize_batch_size):
            tasks.append(
                temporalio.workflow.execute_activity(
                    batch_summarize_actions,
                    BatchSummarizeActionsInputs(
                        start_dt=start_dt_str, offset=i, batch_size=inputs.summarize_batch_size
                    ),
                    start_to_close_timeout=timedelta(seconds=90),
                    retry_policy=temporalio.common.RetryPolicy(
                        initial_interval=timedelta(seconds=30), maximum_attempts=3
                    ),
                )
            )

            # Maximum allowed parallel request count to LLMs is 128 (32 * 4)
            if len(tasks) == inputs.max_parallel_requests:
                await self._process_summaries_batch(tasks, inputs.delay_between_batches, throttle_enabled=True)
                tasks = []

        if tasks:
            await self._process_summaries_batch(tasks, inputs.delay_between_batches, throttle_enabled=False)

        while True:
            res = await temporalio.workflow.execute_activity(
                batch_embed_and_sync_actions,
                BatchEmbedAndSyncActionsInputs(
                    start_dt=start_dt_str,
                    insert_batch_size=inputs.insert_batch_size,
                    embeddings_batch_size=inputs.embed_batch_size,
                    max_parallel_requests=inputs.max_parallel_requests,
                    embedding_version=inputs.embedding_versions.actions if inputs.embedding_versions else None,
                ),
                start_to_close_timeout=timedelta(minutes=30),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=timedelta(seconds=30),
                    maximum_attempts=3,
                    non_retryable_error_types=("ClientAuthenticationError",),
                ),
                # Azure requests take quite a while to complete, so we need to heartbeat to avoid timeouts.
                heartbeat_timeout=timedelta(minutes=5),
            )
            if not res.has_more:
                break

    async def _process_summaries_batch(
        self, tasks: list[Coroutine[Any, Any, Any]], delay_between_batches: int, throttle_enabled: bool | None = None
    ):
        start = temporalio.workflow.time()
        res = await asyncio.gather(*tasks, return_exceptions=True)
        end = temporalio.workflow.time()
        execution_time = end - start

        # Throttle the rate of requests to LLMs
        if throttle_enabled and delay_between_batches > execution_time:
            delay = delay_between_batches - execution_time
            logger.info("Throttling requests to LLMs", delay=delay)
            await asyncio.sleep(delay)

        for maybe_exc in res:
            if isinstance(maybe_exc, BaseException):
                raise maybe_exc
