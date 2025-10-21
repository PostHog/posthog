import json
import asyncio
from abc import ABC, abstractmethod
from collections.abc import Coroutine
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Generic, TypeVar, cast

from django.db.models import F, Model, Q, QuerySet

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
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.clickhouse import ClickHouseClient, get_client
from posthog.temporal.common.utils import get_scheduled_start_time

from ee.hogai.utils.embeddings import aembed_documents, get_async_azure_embeddings_client

logger = structlog.get_logger(__name__)

TModel = TypeVar("TModel", bound=Model)


class EntityConfig(ABC, Generic[TModel]):
    """Configuration for vectorizing a specific entity type."""

    @property
    @abstractmethod
    def domain_name(self) -> str:
        """The domain name used in ClickHouse (e.g., 'action', 'cohort')."""
        pass

    @property
    @abstractmethod
    def model_class(self) -> type[TModel]:
        """The Django model class for this entity."""
        pass

    @abstractmethod
    def get_queryset_filter(self, start_dt: datetime) -> Q:
        """Return the Q object for filtering entities to summarize."""
        pass

    @abstractmethod
    def get_queryset_ordering(self) -> list[str]:
        """Return the ordering for the queryset."""
        pass

    @abstractmethod
    def create_summarizer(self, entity: TModel) -> Any:
        """Create a summarizer for the entity."""
        pass

    @abstractmethod
    async def abatch_summarize(
        self, entities: list[TModel], start_dt: str, properties: dict[str, Any]
    ) -> list[str | BaseException]:
        """Summarize a batch of entities. Returns list of summaries or exceptions."""
        pass

    @abstractmethod
    def get_sync_values_fields(self) -> list[str]:
        """Return the fields to extract for syncing to ClickHouse."""
        pass

    @abstractmethod
    def build_clickhouse_properties(self, entity_dict: dict[str, Any]) -> dict[str, Any]:
        """Build the properties dict to store in ClickHouse."""
        pass


async def get_entities_qs(
    config: EntityConfig[TModel], start_dt: datetime, offset: int | None = None, batch_size: int | None = None
) -> QuerySet[TModel]:
    """Generic function to get entities queryset."""
    filter_conditions = config.get_queryset_filter(start_dt)
    entities_to_summarize = config.model_class.objects.filter(filter_conditions).order_by(
        *config.get_queryset_ordering()
    )
    if offset is None and batch_size is None:
        return entities_to_summarize
    if offset is None or batch_size is None:
        raise ValueError("Cannot provide only offset or only batch_size")
    return entities_to_summarize[offset : offset + batch_size]


@dataclass
class GetApproximateCountInputs:
    domain: str
    start_dt: str


@dataclass
class BatchSummarizeInputs:
    domain: str
    start_dt: str
    offset: int
    batch_size: int


@dataclass
class BatchEmbedAndSyncInputs:
    domain: str
    start_dt: str
    insert_batch_size: int
    embeddings_batch_size: int
    max_parallel_requests: int
    embedding_version: int | None = None


@dataclass
class BatchEmbedAndSyncOutputs:
    has_more: bool


# Registry for entity configs
_ENTITY_CONFIGS: dict[str, EntityConfig[Any]] = {}


def register_entity_config(config: EntityConfig[Any]) -> None:
    """Register an entity configuration."""
    _ENTITY_CONFIGS[config.domain_name] = config


def get_entity_config(domain: str) -> EntityConfig[Any]:
    """Get an entity configuration by domain name."""
    if domain not in _ENTITY_CONFIGS:
        raise ValueError(f"Unknown entity domain: {domain}")
    return _ENTITY_CONFIGS[domain]


@temporalio.activity.defn
async def get_approximate_entities_count(inputs: GetApproximateCountInputs) -> int:
    """Retrieves the approximate count of entities to summarize."""
    config = get_entity_config(inputs.domain)
    qs = await get_entities_qs(config, datetime.fromisoformat(inputs.start_dt))
    return await qs.acount()


@temporalio.activity.defn
async def batch_summarize_entities(inputs: BatchSummarizeInputs):
    """
    Summarizes entities in batches and saves their summaries to the database.

    Args:
        inputs: Inputs for the activity.
    """
    config = get_entity_config(inputs.domain)
    workflow_start_dt = datetime.fromisoformat(inputs.start_dt)
    entities_to_summarize = await get_entities_qs(config, workflow_start_dt, inputs.offset, inputs.batch_size)
    entities = [entity async for entity in entities_to_summarize]

    logger.info(
        f"Preparing to summarize {inputs.domain}s",
        domain=inputs.domain,
        offset=inputs.offset,
        batch_size=inputs.batch_size,
        start_dt=inputs.start_dt,
        entities_count=len(entities),
    )

    summaries = await config.abatch_summarize(
        entities,
        start_dt=inputs.start_dt,
        properties={"offset": inputs.offset, "batch_size": inputs.batch_size, "start_dt": inputs.start_dt},
    )
    models_to_update = []
    for entity, maybe_summary in zip(entities, summaries):
        # If a few entities across the batch fail, we don't want to fail the entire workflow.
        if isinstance(maybe_summary, BaseException):
            # We know OpenAI APIs might be unavailable or have token or request limits exceeded.
            # Since we spawn up to 96 parallel requests here, we should expect some requests to fail,
            # so we can retry them later. It's not practical to cancel the other 95 requests if
            # one fails, but we can retry summarization later.
            if not isinstance(maybe_summary, OpenAIAPIError):
                capture_exception(maybe_summary, additional_properties={"entity_id": entity.id, "tag": "max_ai"})
            logger.exception(f"Error summarizing {inputs.domain}s", error=maybe_summary, entity_id=entity.id)
            continue
        entity.last_summarized_at = workflow_start_dt
        entity.summary = maybe_summary
        models_to_update.append(entity)

    await config.model_class.objects.abulk_update(models_to_update, ["last_summarized_at", "summary"])


async def batch_embed_entities(
    domain: str, entities: list[dict[str, Any]], batch_size: int
) -> list[tuple[dict[str, Any], list[float]]]:
    """
    Embed entities in batches in parallel.

    Args:
        entities: List of all entities to embed.
        batch_size: How many entities to embed in a single batch.

    Returns:
        List of tuples containing the entity and its embedding.
    """
    logger.info(
        f"Preparing to embed {domain}s",
        domain=domain,
        entities_count=len(entities),
    )
    embeddings_client = get_async_azure_embeddings_client()

    filtered_batches = [
        [entity for entity in entities[i : i + batch_size] if entity["summary"]]
        for i in range(0, len(entities), batch_size)
    ]
    embedding_requests = [
        aembed_documents(embeddings_client, [cast(str, entity["summary"]) for entity in entity_batch])
        for entity_batch in filtered_batches
    ]
    responses = await asyncio.gather(*embedding_requests, return_exceptions=True)

    successful_batches = []
    for entity_batch, maybe_vector in zip(filtered_batches, responses):
        # Authentication exception is not retryable.
        if isinstance(maybe_vector, azure_exceptions.ClientAuthenticationError):
            raise maybe_vector
        # Rate limit raised, wait for a timeout.
        if isinstance(maybe_vector, azure_exceptions.HttpResponseError) and maybe_vector.status_code == 429:
            raise maybe_vector

        if isinstance(maybe_vector, BaseException):
            posthoganalytics.capture_exception(maybe_vector, properties={"tag": "max_ai"})
            logger.exception(f"Error embedding {domain}s", error=maybe_vector)
            continue
        for entity, embedding in zip(entity_batch, maybe_vector):
            successful_batches.append((entity, embedding))

    return successful_batches


async def sync_entity_vectors(
    config: EntityConfig[Any],
    client: ClickHouseClient,
    entities_with_embeddings: list[tuple[dict[str, Any], list[float]]],
    insert_batch_size: int,
    workflow_start_dt: datetime,
    embedding_version: int | None = None,
):
    """
    Syncs entity vectors to ClickHouse and updates the last synced timestamp.

    Args:
        config: The entity configuration.
        entities_with_embeddings: List of tuples containing the entity and its embedding.
        insert_batch_size: How many entities to insert in a single query to ClickHouse.
        workflow_start_dt: The start date of the workflow to set the timestamp to.
        embedding_version: The version of the embedding model to use.
    """
    for i in range(0, len(entities_with_embeddings), insert_batch_size):
        batch = entities_with_embeddings[i : i + insert_batch_size]

        rows: list[tuple] = []
        for entity, embedding in batch:
            properties = config.build_clickhouse_properties(entity)
            if embedding_version is not None:
                properties["embedding_version"] = embedding_version

            rows.append(
                (
                    config.domain_name,
                    entity["team_id"],
                    entity["id"],
                    embedding,
                    entity["summary"],
                    json.dumps(properties),
                    1 if entity["deleted"] else 0,
                )
            )

        if not rows:
            break

        await client.execute_query(INSERT_BULK_PG_EMBEDDINGS_SQL, *rows)

        bulk_update = []
        for entity, _ in batch:
            entity_model = config.model_class(id=entity["id"], embedding_last_synced_at=workflow_start_dt)
            if embedding_version is not None:
                entity_model.embedding_version = embedding_version
            bulk_update.append(entity_model)

        await config.model_class.objects.abulk_update(
            bulk_update,
            (
                ["embedding_last_synced_at", "embedding_version"]
                if embedding_version is not None
                else ["embedding_last_synced_at"]
            ),
        )


@temporalio.activity.defn
async def batch_embed_and_sync_entities(inputs: BatchEmbedAndSyncInputs) -> BatchEmbedAndSyncOutputs:
    """
    Embeds entities in batches and syncs them to ClickHouse.

    Args:
        inputs: Inputs for the activity.

    Returns:
        Outputs for the activity: whether there are more entities to sync.
    """
    config = get_entity_config(inputs.domain)
    tag_queries(product=Product.MAX_AI)
    workflow_start_dt = datetime.fromisoformat(inputs.start_dt)

    query = (
        # Include only updated entities.
        Q(last_summarized_at__gt=F("embedding_last_synced_at"))
        # Or entities that haven't never been synced but have summaries.
        | (Q(embedding_last_synced_at__isnull=True) & Q(last_summarized_at__isnull=False))
    )

    # Backward compatibility: Temporal workflows must be deterministic, so we won't
    # look for embedding versions if the version is not set in the inputs.
    if inputs.embedding_version is not None:
        query |= (
            # Or entities that don't have an embedding version.
            Q(embedding_version__isnull=True)
            # Or entities with an old embedding version.
            | Q(embedding_version__lt=inputs.embedding_version)
        )

    entities_to_sync_qs = (
        config.model_class.objects.filter(
            Q(
                last_summarized_at__lte=workflow_start_dt,
                summary__isnull=False,
            )
            & query
        )
        .select_related("team")
        .order_by("updated_at", "id")
        .values(*config.get_sync_values_fields())
    )

    entities_batch_size = inputs.embeddings_batch_size * inputs.max_parallel_requests
    offset = 0
    embedded_entities: list[tuple[dict[str, Any], list[float]]] = []

    while offset < inputs.insert_batch_size:
        temporalio.activity.heartbeat()

        qs_slice = [
            cast(dict[str, Any], entity) async for entity in entities_to_sync_qs[offset : offset + entities_batch_size]
        ]
        if not qs_slice:
            break

        offset += len(qs_slice)
        embedded_entities += await batch_embed_entities(inputs.domain, qs_slice, inputs.embeddings_batch_size)

        if len(qs_slice) != entities_batch_size:
            break

    if not embedded_entities:
        return BatchEmbedAndSyncOutputs(has_more=False)

    logger.info(
        f"Syncing {inputs.domain} vectors",
        domain=inputs.domain,
        insert_batch_size=inputs.insert_batch_size,
        start_dt=inputs.start_dt,
        entities_count=len(embedded_entities),
    )
    temporalio.activity.heartbeat()

    async with get_client() as client:
        await sync_entity_vectors(
            config, client, embedded_entities, inputs.insert_batch_size, workflow_start_dt, inputs.embedding_version
        )

    # Returning True as we can't tell that there are no more entities to sync without doing one additional run.
    return BatchEmbedAndSyncOutputs(has_more=True)


@dataclass
class EmbeddingVersion:
    """The version of the embedding model to use per a domain."""

    actions: int


@dataclass
class SyncEntityVectorsInputs:
    domain: str
    """The entity domain to sync (e.g., 'action', 'cohort')."""
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


@temporalio.workflow.defn(name="ai-sync-entity-vectors")
class SyncEntityVectorsWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> SyncEntityVectorsInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return SyncEntityVectorsInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: SyncEntityVectorsInputs):
        start_dt_str = inputs.start_dt or get_scheduled_start_time().isoformat()

        approximate_count = await temporalio.workflow.execute_activity(
            get_approximate_entities_count,
            GetApproximateCountInputs(domain=inputs.domain, start_dt=start_dt_str),
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=temporalio.common.RetryPolicy(initial_interval=timedelta(seconds=30), maximum_attempts=3),
        )

        tasks = []
        for i in range(0, approximate_count, inputs.summarize_batch_size):
            tasks.append(
                temporalio.workflow.execute_activity(
                    batch_summarize_entities,
                    BatchSummarizeInputs(
                        domain=inputs.domain, start_dt=start_dt_str, offset=i, batch_size=inputs.summarize_batch_size
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
                batch_embed_and_sync_entities,
                BatchEmbedAndSyncInputs(
                    domain=inputs.domain,
                    start_dt=start_dt_str,
                    insert_batch_size=inputs.insert_batch_size,
                    embeddings_batch_size=inputs.embed_batch_size,
                    max_parallel_requests=inputs.max_parallel_requests,
                    embedding_version=inputs.embedding_version if inputs.embedding_versions else None,
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
