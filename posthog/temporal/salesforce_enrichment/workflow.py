import json
import math
import time
import typing
import asyncio
import datetime as dt
import dataclasses

from django.db import close_old_connections

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger

from ee.billing.salesforce_enrichment.constants import DEFAULT_CHUNK_SIZE, SALESFORCE_ACCOUNTS_QUERY
from ee.billing.salesforce_enrichment.enrichment import enrich_accounts_chunked_async
from ee.billing.salesforce_enrichment.redis_cache import get_cached_accounts_count, store_accounts_in_redis
from ee.billing.salesforce_enrichment.salesforce_client import get_salesforce_client

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class SalesforceEnrichmentInputs:
    """Inputs for the Salesforce enrichment workflow."""

    chunk_size: int = DEFAULT_CHUNK_SIZE
    max_chunks: int | None = None  # Optional limit for testing


@dataclasses.dataclass
class EnrichChunkInputs:
    """Inputs for enriching a single chunk of accounts."""

    chunk_number: int
    chunk_size: int
    estimated_total_chunks: int | None = None  # For progress display


@activity.defn
async def enrich_chunk_activity(inputs: EnrichChunkInputs) -> dict[str, typing.Any]:
    """Activity to enrich a single chunk of Salesforce accounts with concurrent API calls."""

    async with Heartbeater():
        logger = LOGGER.bind()
        close_old_connections()

        logger.info(
            "Starting Salesforce enrichment chunk",
            chunk_number=inputs.chunk_number,
            chunk_size=inputs.chunk_size,
        )

        try:
            result = await enrich_accounts_chunked_async(
                chunk_number=inputs.chunk_number,
                chunk_size=inputs.chunk_size,
                estimated_total_chunks=inputs.estimated_total_chunks,
            )

            return result

        except Exception as e:
            logger.exception(
                "Failed to enrich Salesforce chunk",
                chunk_number=inputs.chunk_number,
                chunk_size=inputs.chunk_size,
                error=str(e),
            )
            raise


@activity.defn
async def cache_all_accounts_activity() -> dict[str, typing.Any]:
    """Cache all Salesforce accounts in Redis for fast chunk retrieval.

    Returns dict with total_accounts count. Reuses existing cache if available."""
    close_old_connections()

    logger = LOGGER.bind()
    logger.info("Starting cache_all_accounts_activity")

    try:
        # Exit early if cache exists
        logger.info("Checking Redis cache")
        cached_count = await get_cached_accounts_count()
        if cached_count is not None:
            logger.info("Cache exists, skipping Salesforce query", cached_total=cached_count)
            return {"success": True, "total_accounts": cached_count, "cache_reused": True}
        logger.info("Cache does not exist, querying Salesforce")

        # Query all accounts
        sf_start = time.time()
        sf = get_salesforce_client()

        accounts_result = await asyncio.to_thread(sf.query_all, SALESFORCE_ACCOUNTS_QUERY)
        all_accounts = accounts_result["records"]
        total_count = len(all_accounts)
        sf_time = time.time() - sf_start

        # Store in Redis
        redis_start = time.time()
        await store_accounts_in_redis(all_accounts)
        redis_time = time.time() - redis_start

        logger.info(
            "Successfully cached accounts",
            total_count=total_count,
            sf_time=round(sf_time, 2),
            redis_time=round(redis_time, 2),
        )

        return {"success": True, "total_accounts": total_count}

    except Exception as e:
        logger.exception("Failed to cache accounts", error=str(e))
        raise


@workflow.defn(name="salesforce-enrichment-async")
class SalesforceEnrichmentAsyncWorkflow(PostHogWorkflow):
    """Async workflow to enrich Salesforce accounts with concurrent Harmonic API calls."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SalesforceEnrichmentInputs:
        loaded = json.loads(inputs[0])
        return SalesforceEnrichmentInputs(**loaded)

    @workflow.run
    async def run(self, inputs: SalesforceEnrichmentInputs) -> dict[str, typing.Any]:
        """Run the async Salesforce enrichment workflow with concurrent API calls."""

        logger = LOGGER.bind()
        logger.info(
            "Starting Salesforce enrichment workflow", chunk_size=inputs.chunk_size, max_chunks=inputs.max_chunks
        )

        # Cache all accounts in Redis (if not already cached)
        cache_result = await workflow.execute_activity(
            cache_all_accounts_activity,
            start_to_close_timeout=dt.timedelta(minutes=10),  # should take 10-30s if querying Salesforce
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        if cache_result.get("success"):
            total_accounts = cache_result.get("total_accounts", 0)
        else:
            total_accounts = 0

        estimated_total_chunks = math.ceil(total_accounts / inputs.chunk_size) if total_accounts > 0 else None

        chunk_number = 0
        total_processed = 0
        total_enriched = 0
        total_updated = 0
        all_errors: list[str] = []

        while True:
            # Check if we've hit the max chunks limit (for testing)
            if inputs.max_chunks is not None and chunk_number >= inputs.max_chunks:
                break

            chunk_inputs = EnrichChunkInputs(
                chunk_number=chunk_number,
                chunk_size=inputs.chunk_size,
                estimated_total_chunks=estimated_total_chunks,
            )

            chunk_result = await workflow.execute_activity(
                enrich_chunk_activity,
                chunk_inputs,
                start_to_close_timeout=dt.timedelta(minutes=30),  # a chunk of 5000 should take ~8-15min
                retry_policy=RetryPolicy(initial_interval=dt.timedelta(seconds=10), maximum_attempts=3),
                heartbeat_timeout=dt.timedelta(minutes=5),
            )

            # Accumulate results
            total_processed += chunk_result.get("records_processed", 0)
            total_enriched += chunk_result.get("records_enriched", 0)
            total_updated += chunk_result.get("records_updated", 0)
            all_errors.extend(chunk_result.get("errors", []))

            # If we got fewer raw accounts than the chunk size, we're done
            if chunk_result.get("total_accounts_in_chunk", 0) < inputs.chunk_size:
                break

            chunk_number += 1

        return {
            "chunks_processed": chunk_number,
            "total_processed": total_processed,
            "total_enriched": total_enriched,
            "total_updated": total_updated,
            "error_count": len(all_errors),
            "errors": all_errors[:10],  # Include first 10 errors for debugging
        }
