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
from posthog.models.ai.pg_embeddings import INSERT_BULK_PG_EMBEDDINGS_SQL
from posthog.models.cohort.cohort import Cohort
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.clickhouse import ClickHouseClient, get_client
from posthog.temporal.common.utils import get_scheduled_start_time

from ee.hogai.summarizers.chains import abatch_summarize_entity
from ee.hogai.summarizers.cohorts import CohortSummarizer
from ee.hogai.utils.embeddings import aembed_documents, get_async_azure_embeddings_client

logger = structlog.get_logger(__name__)


async def get_cohorts_qs(start_dt: datetime, offset: int | None = None, batch_size: int | None = None):
    filter_conditions = Q(
        # Only orgs that have accepted data processing
        team__organization__is_ai_data_processing_approved=True,
        # Only cohorts updated before the start date
        updated_at__lte=start_dt,
    ) & (
        # Never summarized cohorts but not deleted
        Q(last_summarized_at__isnull=True, deleted=False)
        # Cohorts updated after last summarization workflow
        | Q(updated_at__gte=F("last_summarized_at"))
        # The line below preserves the execution order of the workflow. Temporal workflows must be deterministic,
        # so activities can be executed in the same order in case of retries. If this line was removed, the execution
        # order with list slices would be non-deterministic, as the queryset would remove already processed cohorts.
        | Q(last_summarized_at=start_dt)
    )
    cohorts_to_summarize = Cohort.objects.filter(filter_conditions).order_by("id", "team_id", "updated_at")
    # cohorts_to_summarize = Cohort.objects.filter(filter_conditions).select_related("team").order_by("id", "team_id", "updated_at")
    if offset is None and batch_size is None:
        return cohorts_to_summarize
    if offset is None or batch_size is None:
        raise ValueError("Cannot provide only offset or only batch_size")
    return cohorts_to_summarize[offset : offset + batch_size]


@dataclass
class GetApproximateCohortsCountInputs:
    start_dt: str


@temporalio.activity.defn
async def get_approximate_cohorts_count(inputs: GetApproximateCohortsCountInputs) -> int:
    """
    Retrieves the approximate count of cohorts to summarize. The cohort count can change
    during the sync (updated_at > start_dt). The count is needed for batch summarization.
    """
    qs = await get_cohorts_qs(datetime.fromisoformat(inputs.start_dt))

    return await qs.acount()


@dataclass
class BatchSummarizeCohortsInputs:
    start_dt: str
    offset: int
    batch_size: int


@temporalio.activity.defn
async def batch_summarize_cohorts(inputs: BatchSummarizeCohortsInputs):
    """
    Summarizes cohorts in batches and saves their summaries to the database.

    Args:
        inputs: Inputs for the activity.
    """
    workflow_start_dt = datetime.fromisoformat(inputs.start_dt)
    cohorts_to_summarize = await get_cohorts_qs(workflow_start_dt, inputs.offset, inputs.batch_size)
    cohorts = [cohort async for cohort in cohorts_to_summarize]

    logger.info(
        "Preparing to summarize cohorts",
        offset=inputs.offset,
        batch_size=inputs.batch_size,
        start_dt=inputs.start_dt,
        cohorts_count=len(cohorts),
    )

    summaries = await abatch_summarize_entity(
        cohorts,
        summarizer_factory=lambda cohort: CohortSummarizer(team=cohort.team, cohort=cohort),
        system_prompt="You will be given a description of a cohort containing filters that define a group of users. Your goal is to summarize the cohort in a maximum of three sentences.",
        domain="cohort",
        entity_id_attr="id",
        start_dt=inputs.start_dt,
        properties={"offset": inputs.offset, "batch_size": inputs.batch_size, "start_dt": inputs.start_dt},
    )
    models_to_update = []
    for cohort, maybe_summary in zip(cohorts, summaries):
        # If a few cohorts across the batch fail, we don't want to fail the entire workflow.
        if isinstance(maybe_summary, BaseException):
            # We know OpenAI APIs might be unavailable or have token or request limits exceeded.
            # Since we spawn up to 96 parallel requests here, we should expect some requests to fail,
            # so we can retry them later. It's not practical to cancel the other 95 requests if
            # one fails, but we can retry summarization later.
            if not isinstance(maybe_summary, OpenAIAPIError):
                capture_exception(maybe_summary, additional_properties={"cohort_id": cohort.id, "tag": "max_ai"})
            logger.exception("Error summarizing cohorts", error=maybe_summary, cohort_id=cohort.id)
            continue
        cohort.last_summarized_at = workflow_start_dt
        cohort.summary = maybe_summary
        models_to_update.append(cohort)

    await Cohort.objects.abulk_update(models_to_update, ["last_summarized_at", "summary"])


# abatch_summarize_entity is imported from ee.hogai.summarizers.chains


async def batch_embed_cohorts(
    cohorts: list[dict[str, Any]], batch_size: int
) -> list[tuple[dict[str, Any], list[float]]]:
    """
    Embed cohorts in batches in parallel.

    Args:
        cohorts: List of all cohorts to embed.
        batch_size: How many cohorts to embed in a single batch.

    Returns:
        List of tuples containing the cohort and its embedding.
    """
    logger.info(
        "Preparing to embed cohorts",
        cohorts_count=len(cohorts),
    )
    embeddings_client = get_async_azure_embeddings_client()

    filtered_batches = [
        [cohort for cohort in cohorts[i : i + batch_size] if cohort["summary"]]
        for i in range(0, len(cohorts), batch_size)
    ]
    embedding_requests = [
        aembed_documents(embeddings_client, [cast(str, cohort["summary"]) for cohort in cohort_batch])
        for cohort_batch in filtered_batches
    ]
    responses = await asyncio.gather(*embedding_requests, return_exceptions=True)

    successful_batches = []
    for cohort_batch, maybe_vector in zip(filtered_batches, responses):
        # Authentication exception is not retryable.
        if isinstance(maybe_vector, azure_exceptions.ClientAuthenticationError):
            raise maybe_vector
        # Rate limit raised, wait for a timeout.
        if isinstance(maybe_vector, azure_exceptions.HttpResponseError) and maybe_vector.status_code == 429:
            raise maybe_vector

        if isinstance(maybe_vector, BaseException):
            posthoganalytics.capture_exception(maybe_vector, properties={"tag": "max_ai"})
            logger.exception("Error embedding cohorts", error=maybe_vector)
            continue
        for cohort, embedding in zip(cohort_batch, maybe_vector):
            successful_batches.append((cohort, embedding))

    return successful_batches


async def sync_cohort_vectors(
    client: ClickHouseClient,
    cohorts_with_embeddings: list[tuple[dict[str, Any], list[float]]],
    insert_batch_size: int,
    workflow_start_dt: datetime,
    embedding_version: int | None = None,
):
    """
    Syncs cohort vectors to ClickHouse and updates the last synced timestamp.

    Args:
        cohorts_with_embeddings: List of tuples containing the cohort and its embedding.
        insert_batch_size: How many cohorts to insert in a single query to ClickHouse.
        workflow_start_dt: The start date of the workflow to set the timestamp to.
    """
    for i in range(0, len(cohorts_with_embeddings), insert_batch_size):
        batch = cohorts_with_embeddings[i : i + insert_batch_size]

        rows: list[tuple] = []
        for cohort, embedding in batch:
            properties = {
                "name": cohort["name"],
                "description": cohort["description"],
                "is_static": cohort["is_static"],
                "count": cohort["count"],
            }
            if embedding_version is not None:
                properties["embedding_version"] = embedding_version

            rows.append(
                (
                    "cohort",
                    cohort["team_id"],
                    cohort["id"],
                    embedding,
                    cohort["summary"],
                    json.dumps(properties),
                    1 if cohort["deleted"] else 0,
                )
            )

        if not rows:
            break

        await client.execute_query(INSERT_BULK_PG_EMBEDDINGS_SQL, *rows)

        bulk_update = []
        for cohort, _ in batch:
            cohort_model = Cohort(id=cohort["id"], embedding_last_synced_at=workflow_start_dt)
            if embedding_version is not None:
                cohort_model.embedding_version = embedding_version
            bulk_update.append(cohort_model)

        await Cohort.objects.abulk_update(
            bulk_update,
            (
                ["embedding_last_synced_at", "embedding_version"]
                if embedding_version is not None
                else ["embedding_last_synced_at"]
            ),
        )


@dataclass
class BatchEmbedAndSyncCohortsInputs:
    start_dt: str
    insert_batch_size: int
    embeddings_batch_size: int
    max_parallel_requests: int
    embedding_version: int | None = None


@dataclass
class BatchEmbedAndSyncCohortsOutputs:
    has_more: bool


@temporalio.activity.defn
async def batch_embed_and_sync_cohorts(inputs: BatchEmbedAndSyncCohortsInputs) -> BatchEmbedAndSyncCohortsOutputs:
    """
    Embeds cohorts in batches and syncs them to ClickHouse.

    Args:
        inputs: Inputs for the activity.

    Returns:
        Outputs for the activity: whether there are more cohorts to sync.
    """
    tag_queries(product=Product.MAX_AI)
    workflow_start_dt = datetime.fromisoformat(inputs.start_dt)

    query = (
        # Include only updated cohorts.
        Q(last_summarized_at__gt=F("embedding_last_synced_at"))
        # Or cohorts that haven't never been synced but have summaries.
        | (Q(embedding_last_synced_at__isnull=True) & Q(last_summarized_at__isnull=False))
    )

    # Backward compatibility: Temporal workflows must be deterministic, so we won't
    # look for embedding versions if the version is not set in the inputs.
    if inputs.embedding_version is not None:
        query |= (
            # Or cohorts that don't have an embedding version.
            Q(embedding_version__isnull=True)
            # Or cohorts with an old embedding version.
            | Q(embedding_version__lt=inputs.embedding_version)
        )

    cohorts_to_sync_qs = (
        Cohort.objects.filter(
            Q(
                # Include only cohorts that have been summarized.
                last_summarized_at__lte=workflow_start_dt,
                # And they must have a summary to prevent infinite loops.
                summary__isnull=False,
            )
            & query
        )
        .order_by("updated_at", "id")
        .values("team_id", "id", "summary", "name", "description", "deleted", "is_static", "count")
    )

    cohorts_batch_size = inputs.embeddings_batch_size * inputs.max_parallel_requests
    offset = 0
    embedded_cohorts: list[tuple[dict[str, Any], list[float]]] = []

    while offset < inputs.insert_batch_size:
        temporalio.activity.heartbeat()

        qs_slice = [
            cast(dict[str, Any], cohort) async for cohort in cohorts_to_sync_qs[offset : offset + cohorts_batch_size]
        ]
        if not qs_slice:
            break

        offset += len(qs_slice)
        embedded_cohorts += await batch_embed_cohorts(qs_slice, inputs.embeddings_batch_size)

        # Exit early if we don't have enough cohorts to fill the batch.
        if len(qs_slice) != cohorts_batch_size:
            break

    if not embedded_cohorts:
        return BatchEmbedAndSyncCohortsOutputs(has_more=False)

    logger.info(
        "Syncing cohort vectors",
        insert_batch_size=inputs.insert_batch_size,
        start_dt=inputs.start_dt,
        cohorts_count=len(embedded_cohorts),
    )
    temporalio.activity.heartbeat()

    async with get_client() as client:
        await sync_cohort_vectors(
            client, embedded_cohorts, inputs.insert_batch_size, workflow_start_dt, inputs.embedding_version
        )

    # Returning True as we can't tell that there are no more cohorts to sync without doing one additional run.
    return BatchEmbedAndSyncCohortsOutputs(has_more=True)


@dataclass
class EmbeddingVersion:
    """The version of the embedding model to use per a domain."""

    cohorts: int


@dataclass
class SyncCohortVectorsInputs:
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


@temporalio.workflow.defn(name="ai-sync-cohort-vectors")
class SyncCohortVectorsWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> SyncCohortVectorsInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return SyncCohortVectorsInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: SyncCohortVectorsInputs):
        start_dt_str = inputs.start_dt or get_scheduled_start_time().isoformat()

        approximate_cohorts_count = await temporalio.workflow.execute_activity(
            get_approximate_cohorts_count,
            GetApproximateCohortsCountInputs(start_dt=start_dt_str),
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=temporalio.common.RetryPolicy(initial_interval=timedelta(seconds=30), maximum_attempts=3),
        )

        tasks = []
        for i in range(0, approximate_cohorts_count, inputs.summarize_batch_size):
            tasks.append(
                temporalio.workflow.execute_activity(
                    batch_summarize_cohorts,
                    BatchSummarizeCohortsInputs(
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
                batch_embed_and_sync_cohorts,
                BatchEmbedAndSyncCohortsInputs(
                    start_dt=start_dt_str,
                    insert_batch_size=inputs.insert_batch_size,
                    embeddings_batch_size=inputs.embed_batch_size,
                    max_parallel_requests=inputs.max_parallel_requests,
                    embedding_version=inputs.embedding_versions.cohorts if inputs.embedding_versions else None,
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
