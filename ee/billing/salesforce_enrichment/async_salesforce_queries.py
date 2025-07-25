"""
Async Salesforce account querying with Redis cache support.

This module provides async versions of Salesforce queries that can properly
integrate with Redis caching in async contexts.
"""

import time

from posthog.temporal.common.logger import get_internal_logger


async def query_salesforce_accounts_chunk_async(sf, offset=0, limit=5000, workflow_id=None):
    logger = get_internal_logger()
    """
    Async version of Salesforce account querying with Redis cache-first approach.

    Args:
        sf: Salesforce client (sync)
        offset: Starting index for pagination
        limit: Number of accounts to retrieve
        workflow_id: Optional workflow ID for Redis cache retrieval
    """
    # Try Redis cache first if workflow_id is provided
    if workflow_id:
        cache_start = time.time()
        try:
            from ee.billing.salesforce_enrichment.redis_cache import get_accounts_from_redis

            cached_accounts = await get_accounts_from_redis(workflow_id, offset, limit)
            cache_time = time.time() - cache_start

            if cached_accounts is not None:
                logger.info("Redis cache hit", accounts_count=len(cached_accounts), cache_time=round(cache_time, 3))
                return cached_accounts
        except Exception as e:
            cache_time = time.time() - cache_start
            logger.warning("Redis cache error", error=str(e), cache_time=round(cache_time, 3))

    # Fallback to Salesforce query
    sf_start = time.time()
    query = """
        SELECT Id, Name, Website, CreatedDate
        FROM Account
        WHERE Website != null
        ORDER BY CreatedDate DESC
    """

    try:
        # Use query_all to get all accounts
        accounts = sf.query_all(query)
        sf_time = time.time() - sf_start
        logger.info("Salesforce query complete", total_accounts=accounts["totalSize"], query_time=round(sf_time, 2))

        # Paginate in memory
        start_idx = offset
        end_idx = min(offset + limit, len(accounts["records"]))

        if start_idx >= len(accounts["records"]):
            return []

        chunk_records = accounts["records"][start_idx:end_idx]

        return chunk_records
    except Exception as e:
        logger.exception("Salesforce query failed", error=str(e))
        return []
