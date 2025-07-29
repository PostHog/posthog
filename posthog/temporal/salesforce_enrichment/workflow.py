import dataclasses
import datetime as dt
import json
import math
import time
import typing

from django.db import close_old_connections
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_internal_logger
from posthog.exceptions_capture import capture_exception

# Salesforce query to get all accounts with websites
SALESFORCE_ACCOUNTS_QUERY = """
    SELECT Id, Name, Website, CreatedDate
    FROM Account
    WHERE Website != null
    ORDER BY CreatedDate DESC
"""


@dataclasses.dataclass
class SalesforceEnrichmentInputs:
    """Inputs for the Salesforce enrichment workflow."""

    chunk_size: int = 1000
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

    from posthog.temporal.common.heartbeat import Heartbeater

    async with Heartbeater():
        logger = get_internal_logger()
        close_old_connections()

        logger.info(
            "Starting Salesforce enrichment chunk",
            chunk_number=inputs.chunk_number,
            chunk_size=inputs.chunk_size,
        )

        try:
            # Import here to avoid circular imports
            from ee.billing.salesforce_enrichment.enrichment import enrich_accounts_chunked_async

            # Call the async business logic - it returns dict with correct field names
            result = await enrich_accounts_chunked_async(
                chunk_number=inputs.chunk_number,
                chunk_size=inputs.chunk_size,
                estimated_total_chunks=inputs.estimated_total_chunks,
            )

            logger.info("Completed Salesforce enrichment chunk", **result)
            return result

        except Exception as e:
            logger.exception(
                "Failed to enrich Salesforce chunk",
                chunk_number=inputs.chunk_number,
                chunk_size=inputs.chunk_size,
                error=str(e),
            )
            capture_exception(e)

            return {
                "total_accounts_in_chunk": 0,
                "records_processed": 0,
                "records_enriched": 0,
                "records_updated": 0,
                "errors": [str(e)],
            }


@activity.defn
async def cache_all_accounts_activity() -> dict[str, typing.Any]:
    """Cache all Salesforce accounts in Redis for fast chunk retrieval."""
    logger = get_internal_logger()
    workflow_id = activity.info().workflow_id

    try:
        close_old_connections()

        # Import here to avoid circular imports
        from ee.billing.salesforce_enrichment.salesforce_client import SalesforceClient
        from ee.billing.salesforce_enrichment.redis_cache import store_accounts_in_redis, get_cached_accounts_count

        logger.info("Starting to cache Salesforce accounts", workflow_id=workflow_id)

        # Simple cache check - if cache exists, return the total count
        cached_count = await get_cached_accounts_count()
        if cached_count is not None:
            logger.info("Cache exists, skipping Salesforce query", workflow_id=workflow_id, cached_total=cached_count)
            return {"success": True, "total_accounts": cached_count, "cache_reused": True}

        # Query all accounts
        sf_start = time.time()
        sf = SalesforceClient()

        accounts_result = sf.query_all(SALESFORCE_ACCOUNTS_QUERY)
        all_accounts = accounts_result["records"]
        total_count = len(all_accounts)
        sf_time = time.time() - sf_start

        # Store in Redis
        redis_start = time.time()
        await store_accounts_in_redis(all_accounts)
        redis_time = time.time() - redis_start

        logger.info(
            "Successfully cached accounts",
            workflow_id=workflow_id,
            total_count=total_count,
            sf_time=round(sf_time, 2),
            redis_time=round(redis_time, 2),
        )

        return {"success": True, "total_accounts": total_count}

    except Exception as e:
        logger.exception("Failed to cache accounts", workflow_id=workflow_id, error=str(e))
        capture_exception(e)
        return {"success": False, "error": str(e)}


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

        # Cache all accounts in Redis for fast chunk retrieval
        cache_result = await workflow.execute_activity(
            cache_all_accounts_activity,
            start_to_close_timeout=dt.timedelta(minutes=10),  # Allow time for large query
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        if not cache_result.get("success"):
            # If caching fails, disable chunk estimation and process sequentially
            total_accounts = 0
        else:
            # Use cached count
            total_accounts = cache_result.get("total_accounts", 0)

        # Ensure total_accounts is always an integer
        total_accounts = int(total_accounts) if total_accounts else 0

        # Calculate estimated total chunks
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

            # Prepare chunk inputs
            chunk_inputs = EnrichChunkInputs(
                chunk_number=chunk_number,
                chunk_size=inputs.chunk_size,
                estimated_total_chunks=estimated_total_chunks,
            )

            # Execute the chunk enrichment activity (with concurrent API calls)
            chunk_result = await workflow.execute_activity(
                enrich_chunk_activity,
                chunk_inputs,
                start_to_close_timeout=dt.timedelta(minutes=30),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(minutes=2),
                    maximum_attempts=3,
                    non_retryable_error_types=["ValueError", "KeyError"],
                ),
            )

            # Accumulate results
            total_processed += chunk_result.get("records_processed", 0)
            total_enriched += chunk_result.get("records_enriched", 0)
            total_updated += chunk_result.get("records_updated", 0)
            all_errors.extend(chunk_result.get("errors", []))

            # If we got fewer raw accounts than the chunk size, we're done
            if chunk_result.get("total_accounts_in_chunk", 0) < inputs.chunk_size:
                break

            # Move to next chunk
            chunk_number += 1

        # Return final results
        return {
            "chunks_processed": chunk_number,
            "total_processed": total_processed,
            "total_enriched": total_enriched,
            "total_updated": total_updated,
            "error_count": len(all_errors),
            "errors": all_errors[:10],  # Include first 10 errors for debugging
        }
