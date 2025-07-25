import dataclasses
import datetime as dt
import json
import time
import typing

from django.db import close_old_connections
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.common.logger import get_internal_logger
import math


@dataclasses.dataclass
class SalesforceEnrichmentInputs:
    """Inputs for the Salesforce enrichment workflow."""

    chunk_size: int = 1000
    max_chunks: int | None = None  # Optional limit for testing
    workflow_id: str | None = None  # Optional workflow ID for Redis caching (auto-generated if not provided)

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "chunk_size": self.chunk_size,
            "max_chunks": self.max_chunks,
            "workflow_id": self.workflow_id,
        }


@dataclasses.dataclass
class EnrichChunkInputs:
    """Inputs for enriching a single chunk of accounts."""

    chunk_number: int
    chunk_size: int
    estimated_total_chunks: int | None = None  # For progress display
    workflow_id: str | None = None  # For Redis cache retrieval

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "chunk_number": self.chunk_number,
            "chunk_size": self.chunk_size,
            "estimated_total_chunks": self.estimated_total_chunks,
            "workflow_id": self.workflow_id,
        }


@dataclasses.dataclass
class EnrichChunkResult:
    """Result from enriching a single chunk."""

    total_accounts_in_chunk: int  # Raw account count for stopping logic
    records_processed: int  # Business domains processed
    records_enriched: int
    records_updated: int
    errors: list[str]

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "total_accounts_in_chunk": self.total_accounts_in_chunk,
            "records_processed": self.records_processed,
            "records_enriched": self.records_enriched,
            "records_updated": self.records_updated,
            "error_count": len(self.errors),
        }


@activity.defn
def enrich_chunk_activity(inputs: EnrichChunkInputs) -> EnrichChunkResult:
    """Activity to enrich a single chunk of Salesforce accounts (sync version)."""

    with HeartbeaterSync():
        logger = get_internal_logger()
        close_old_connections()

        logger.info(
            "Starting Salesforce enrichment chunk",
            chunk_number=inputs.chunk_number,
            chunk_size=inputs.chunk_size,
        )

        try:
            # Import here to avoid circular imports
            from ee.billing.salesforce_enrichment.enrichment import enrich_accounts_chunked

            # Call the existing business logic
            result = enrich_accounts_chunked(
                chunk_number=inputs.chunk_number,
                chunk_size=inputs.chunk_size,
                estimated_total_chunks=inputs.estimated_total_chunks,
                workflow_id=inputs.workflow_id,
            )

            # Handle error case
            if "error" in result:
                return EnrichChunkResult(
                    total_accounts_in_chunk=0,
                    records_processed=0,
                    records_enriched=0,
                    records_updated=0,
                    errors=[result["error"]],
                )

            # Transform result to match our dataclass
            chunk_result = EnrichChunkResult(
                total_accounts_in_chunk=result.get("total_accounts_in_chunk", 0),
                records_processed=result.get("total_processed", 0),
                records_enriched=result.get("total_enriched", 0),
                records_updated=result.get("records_updated", 0),
                errors=[],  # No errors if we got here
            )

            logger.info(
                "Completed Salesforce enrichment chunk",
                **chunk_result.properties_to_log,
            )

            return chunk_result

        except Exception as e:
            logger.exception(
                "Failed to enrich Salesforce chunk",
                chunk_number=inputs.chunk_number,
                chunk_size=inputs.chunk_size,
                error=str(e),
            )

            return EnrichChunkResult(
                total_accounts_in_chunk=0,
                records_processed=0,
                records_enriched=0,
                records_updated=0,
                errors=[str(e)],
            )


@activity.defn
async def cache_all_accounts_activity(workflow_id: str) -> dict[str, typing.Any]:
    """Cache all Salesforce accounts in Redis for fast chunk retrieval."""
    logger = get_internal_logger()

    try:
        close_old_connections()

        # Import here to avoid circular imports
        from ee.billing.salesforce_enrichment.salesforce_client import SalesforceClient
        from ee.billing.salesforce_enrichment.redis_cache import store_accounts_in_redis

        logger.info("🔄 REDIS CACHING: Starting to cache all Salesforce accounts", workflow_id=workflow_id)

        # Check if global cache already exists
        from ee.billing.salesforce_enrichment.redis_cache import get_accounts_from_redis

        try:
            # Quick check for existing global cache (get small sample to check total count)
            test_accounts = await get_accounts_from_redis(workflow_id, 0, 5)
            if test_accounts is not None:
                # Get the total count from the cache by checking a larger range
                full_check = await get_accounts_from_redis(workflow_id, 0, 100000)  # Large enough to get all
                total_count = len(full_check) if full_check else 0
                logger.info(
                    "✅ GLOBAL CACHE EXISTS: Skipping Salesforce query",
                    workflow_id=workflow_id,
                    cached_total=total_count,
                )
                return {
                    "success": True,
                    "total_accounts": total_count,
                    "workflow_id": workflow_id,
                    "cache_reused": True,
                }
        except Exception as e:
            logger.info("🔍 Global cache check failed, proceeding with fresh query", error=str(e))

        # Query all accounts (same query as current implementation)
        sf_start = time.time()
        sf_client = SalesforceClient()
        sf = sf_client.client

        query = """
            SELECT Id, Name, Website, CreatedDate
            FROM Account
            WHERE Website != null
            ORDER BY CreatedDate DESC
        """

        # Get all accounts
        accounts_result = sf.query_all(query)
        all_accounts = accounts_result["records"]
        total_count = len(all_accounts)
        sf_time = time.time() - sf_start

        logger.info(f"📊 SALESFORCE: Fetched {total_count} accounts in {sf_time:.2f}s, now storing in Redis")

        # Store in Redis with compression
        redis_start = time.time()
        await store_accounts_in_redis(workflow_id, all_accounts)
        redis_time = time.time() - redis_start

        logger.info(
            f"✅ REDIS CACHE: Successfully stored {total_count} accounts in {redis_time:.2f}s",
            workflow_id=workflow_id,
            total_count=total_count,
        )

        return {
            "success": True,
            "total_accounts": total_count,
            "workflow_id": workflow_id,
        }

    except Exception as e:
        logger.exception("Failed to cache accounts in Redis", workflow_id=workflow_id, error=str(e))
        return {
            "success": False,
            "error": str(e),
            "workflow_id": workflow_id,
        }


@activity.defn
async def get_total_account_count_activity() -> int:
    """Get the total count of accounts with websites for chunk estimation."""
    logger = get_internal_logger()

    try:
        close_old_connections()

        # Import here to avoid circular imports
        from ee.billing.salesforce_enrichment.salesforce_client import SalesforceClient

        # Quick query to get total count
        sf_client = SalesforceClient()
        sf = sf_client.client

        # Count accounts with websites
        count_query = """
            SELECT COUNT(Id)
            FROM Account
            WHERE Website != null
        """

        result = sf.query(count_query)
        total_count = result["totalSize"]

        logger.info(f"Total accounts with websites: {total_count}")
        return total_count

    except Exception as e:
        logger.exception("Failed to get total account count", error=str(e))
        return 0  # Return 0 on error, will disable chunk estimation


@activity.defn
async def enrich_chunk_activity_async(inputs: EnrichChunkInputs) -> EnrichChunkResult:
    """Async activity to enrich a single chunk of Salesforce accounts with concurrent API calls."""

    from posthog.temporal.common.heartbeat import Heartbeater

    async with Heartbeater():
        logger = get_internal_logger()
        close_old_connections()

        logger.info(
            "Starting async Salesforce enrichment chunk",
            chunk_number=inputs.chunk_number,
            chunk_size=inputs.chunk_size,
        )

        try:
            # Import here to avoid circular imports
            from ee.billing.salesforce_enrichment.async_enrichment import enrich_accounts_chunked_async

            # Call the async business logic
            result = await enrich_accounts_chunked_async(
                chunk_number=inputs.chunk_number,
                chunk_size=inputs.chunk_size,
                estimated_total_chunks=inputs.estimated_total_chunks,
                workflow_id=inputs.workflow_id,
            )

            # Handle error case
            if "error" in result:
                return EnrichChunkResult(
                    total_accounts_in_chunk=0,
                    records_processed=0,
                    records_enriched=0,
                    records_updated=0,
                    errors=[result["error"]],
                )

            # Transform result to match our dataclass
            chunk_result = EnrichChunkResult(
                total_accounts_in_chunk=result.get("total_accounts_in_chunk", 0),
                records_processed=result.get("total_processed", 0),
                records_enriched=result.get("total_enriched", 0),
                records_updated=result.get("records_updated", 0),
                errors=[],  # No errors if we got here
            )

            logger.info(
                "Completed async Salesforce enrichment chunk",
                **chunk_result.properties_to_log,
            )

            return chunk_result

        except Exception as e:
            logger.exception(
                "Failed to enrich Salesforce chunk (async)",
                chunk_number=inputs.chunk_number,
                chunk_size=inputs.chunk_size,
                error=str(e),
            )

            return EnrichChunkResult(
                total_accounts_in_chunk=0,
                records_processed=0,
                records_enriched=0,
                records_updated=0,
                errors=[str(e)],
            )


@workflow.defn(name="salesforce-enrichment")
class SalesforceEnrichmentWorkflow(PostHogWorkflow):
    """Workflow to enrich Salesforce accounts with Harmonic data in chunks."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SalesforceEnrichmentInputs:
        loaded = json.loads(inputs[0])
        return SalesforceEnrichmentInputs(**loaded)

    @workflow.run
    async def run(self, inputs: SalesforceEnrichmentInputs) -> dict[str, typing.Any]:
        """Run the Salesforce enrichment workflow."""

        # Generate workflow ID for Redis caching if not provided
        from ee.billing.salesforce_enrichment.redis_cache import generate_workflow_id

        workflow_id = inputs.workflow_id or generate_workflow_id()

        # Cache all accounts in Redis for fast chunk retrieval
        cache_result = await workflow.execute_activity(
            cache_all_accounts_activity,
            workflow_id,
            start_to_close_timeout=dt.timedelta(minutes=10),  # Allow time for large query
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        if not cache_result.get("success"):
            # If caching fails, fall back to traditional chunk queries
            total_accounts = await workflow.execute_activity(
                get_total_account_count_activity,
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        else:
            # Use cached count
            total_accounts = cache_result.get("total_accounts", 0)

        # Ensure total_accounts is always an integer (handle legacy string values)
        if isinstance(total_accounts, str):
            try:
                total_accounts = int(total_accounts) if total_accounts.isdigit() else 0
            except (ValueError, AttributeError):
                total_accounts = 0

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
                workflow_id=workflow_id,
            )

            # Execute the chunk enrichment activity
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
            total_processed += chunk_result.records_processed
            total_enriched += chunk_result.records_enriched
            total_updated += chunk_result.records_updated
            all_errors.extend(chunk_result.errors)

            # If we got fewer raw accounts than the chunk size, we're done
            if chunk_result.total_accounts_in_chunk < inputs.chunk_size:
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

        # Generate workflow ID for Redis caching if not provided
        from ee.billing.salesforce_enrichment.redis_cache import generate_workflow_id

        workflow_id = inputs.workflow_id or generate_workflow_id()

        # Cache all accounts in Redis for fast chunk retrieval
        cache_result = await workflow.execute_activity(
            cache_all_accounts_activity,
            workflow_id,
            start_to_close_timeout=dt.timedelta(minutes=10),  # Allow time for large query
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        if not cache_result.get("success"):
            # If caching fails, fall back to traditional chunk queries
            total_accounts = await workflow.execute_activity(
                get_total_account_count_activity,
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        else:
            # Use cached count
            total_accounts = cache_result.get("total_accounts", 0)

        # Ensure total_accounts is always an integer (handle legacy string values)
        if isinstance(total_accounts, str):
            try:
                total_accounts = int(total_accounts) if total_accounts.isdigit() else 0
            except (ValueError, AttributeError):
                total_accounts = 0

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
                workflow_id=workflow_id,
            )

            # Execute the ASYNC chunk enrichment activity
            chunk_result = await workflow.execute_activity(
                enrich_chunk_activity_async,  # Use async activity
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
            total_processed += chunk_result.records_processed
            total_enriched += chunk_result.records_enriched
            total_updated += chunk_result.records_updated
            all_errors.extend(chunk_result.errors)

            # If we got fewer raw accounts than the chunk size, we're done
            if chunk_result.total_accounts_in_chunk < inputs.chunk_size:
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
