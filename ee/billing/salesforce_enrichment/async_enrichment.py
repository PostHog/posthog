import asyncio
import sys
import time
from urllib.parse import urlparse

from posthog.temporal.common.logger import get_internal_logger

from .async_harmonic_client import AsyncHarmonicClient
from .salesforce_client import SalesforceClient
from .enrichment import (
    # Import existing utility functions
    is_personal_domain,
    transform_harmonic_data,
    prepare_salesforce_update_data,
    bulk_update_salesforce_accounts,
)
from .async_salesforce_queries import query_salesforce_accounts_chunk_async


async def enrich_accounts_chunked_async(
    chunk_number: int = 0,
    chunk_size: int = 5000,
    estimated_total_chunks: int | None = None,
    workflow_id: str | None = None,
):
    logger = get_internal_logger()
    """
    Async version of account enrichment with concurrent Harmonic API calls.

    Uses PostHog's async patterns:
    - AsyncHarmonicClient with semaphore for 5 concurrent requests
    - Batch processing in groups of 100 accounts
    - asyncio.gather with return_exceptions=True
    """
    start_time = time.time()
    offset = chunk_number * chunk_size

    # Display chunk progress with estimated total
    if estimated_total_chunks:
        logger.info(
            "Starting async chunk",
            chunk_number=chunk_number,
            estimated_total_chunks=estimated_total_chunks,
            offset=offset,
            end_offset=offset + chunk_size - 1,
        )
    else:
        logger.info(
            "Starting async chunk", chunk_number=chunk_number, offset=offset, end_offset=offset + chunk_size - 1
        )

    # Initialize Salesforce client (still sync)
    sf_start = time.time()
    try:
        sf_client = SalesforceClient()
        sf = sf_client.client
        logger.info("Connected to Salesforce", connection_time=round(time.time() - sf_start, 2))
    except Exception as e:
        logger.exception("Failed to connect to Salesforce", error=str(e))
        return {"chunk_number": chunk_number, "chunk_size": chunk_size, "error": str(e), "success_rate": 0}

    # Query accounts
    query_start = time.time()
    try:
        accounts = await query_salesforce_accounts_chunk_async(sf, offset, chunk_size, workflow_id)
        if not accounts:
            logger.info("No accounts found in this chunk")
            return {
                "chunk_number": chunk_number,
                "chunk_size": chunk_size,
                "total_accounts_in_chunk": 0,
                "total_processed": 0,
                "total_enriched": 0,
                "records_updated": 0,
                "success_rate": 0,
                "timing": {"total_time": time.time() - start_time},
            }

        logger.info(
            "Found accounts to process",
            total_accounts=len(accounts),
            chunk_number=chunk_number,
            query_time=round(time.time() - query_start, 2),
        )
    except Exception as e:
        logger.exception("Failed to query accounts", error=str(e))
        return {"chunk_number": chunk_number, "chunk_size": chunk_size, "error": str(e), "success_rate": 0}

    # Prepare account data for async processing
    processing_start = time.time()
    enrichment_time = 0

    # Extract domains and prepare account info
    account_data = []
    for account in accounts:
        account_id = account["Id"]
        website = account["Website"]

        try:
            parsed = urlparse(website if website.startswith(("http://", "https://")) else f"https://{website}")
            domain = parsed.netloc
        except Exception:
            continue

        # Skip personal domains
        if is_personal_domain(domain):
            continue

        account_data.append({"account_id": account_id, "domain": domain, "account": account})

    logger.info(
        "Processing business domains",
        business_domains=len(account_data),
        total_accounts=len(accounts),
        filter_ratio=round(len(account_data) / len(accounts) * 100, 1),
    )

    if not account_data:
        logger.info("No business domains to process")
        return {
            "chunk_number": chunk_number,
            "chunk_size": chunk_size,
            "total_accounts_in_chunk": len(accounts),
            "total_processed": 0,
            "total_enriched": 0,
            "records_updated": 0,
            "success_rate": 0,
            "timing": {"total_time": time.time() - start_time},
        }

    # Process in batches of 100 with 5 concurrent requests each
    BATCH_SIZE = 100
    total_enriched = 0
    total_failed = 0
    update_records = []

    # Use async harmonic client
    async with AsyncHarmonicClient(max_concurrent_requests=5) as harmonic_client:
        logger.info("Connected to Harmonic async client", concurrent_requests=5)

        # Process accounts in batches
        for batch_start in range(0, len(account_data), BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, len(account_data))
            batch = account_data[batch_start:batch_end]

            batch_num = batch_start // BATCH_SIZE + 1
            total_batches = (len(account_data) + BATCH_SIZE - 1) // BATCH_SIZE
            logger.info(
                "Processing batch",
                batch_number=batch_num,
                total_batches=total_batches,
                batch_size=len(batch),
                chunk_number=chunk_number,
            )

            # Extract domains for this batch
            batch_domains = [item["domain"] for item in batch]

            # Make concurrent Harmonic API calls
            batch_start_time = time.time()
            harmonic_results = await harmonic_client.enrich_companies_batch(batch_domains)
            batch_api_time = time.time() - batch_start_time
            enrichment_time += batch_api_time

            # Process results
            for _i, (account_info, harmonic_result) in enumerate(zip(batch, harmonic_results)):
                account_id = account_info["account_id"]

                if harmonic_result:
                    # Transform the raw GraphQL response
                    harmonic_data = transform_harmonic_data(harmonic_result)

                    if harmonic_data:
                        total_enriched += 1
                        # Prepare update data
                        update_data = prepare_salesforce_update_data(account_id, harmonic_data)
                        if update_data:
                            update_records.append(update_data)
                        else:
                            total_failed += 1
                    else:
                        total_failed += 1
                else:
                    total_failed += 1

            # Progress update
            processed_so_far = min(batch_end, len(account_data))
            success_rate = (total_enriched / processed_so_far * 100) if processed_so_far > 0 else 0
            avg_time_per_batch = enrichment_time / ((batch_start // BATCH_SIZE) + 1)
            remaining_batches = ((len(account_data) - processed_so_far) + BATCH_SIZE - 1) // BATCH_SIZE
            eta = remaining_batches * avg_time_per_batch

            logger.info(
                "Chunk progress",
                chunk_number=chunk_number,
                processed=processed_so_far,
                total=len(account_data),
                enriched=total_enriched,
                success_rate=round(success_rate, 1),
                batch_time=round(batch_api_time, 2),
                eta_minutes=round(eta / 60, 1),
            )

    # Perform batch update
    if update_records:
        logger.info("Starting batch update", total_records=len(update_records))
        update_start = time.time()
        bulk_update_salesforce_accounts(sf, update_records)
        update_time = time.time() - update_start
    else:
        logger.info("No records to update")
        update_time = 0

    # Print final statistics
    total_time = time.time() - start_time
    processing_time = time.time() - processing_start
    avg_enrichment_time = enrichment_time / len(account_data) if len(account_data) > 0 else 0

    logger.info(
        "Async chunk summary",
        chunk_number=chunk_number,
        total_processed=len(account_data),
        total_enriched=total_enriched,
        failed_enrichments=total_failed,
        success_rate=round(total_enriched / len(account_data) * 100, 1) if len(account_data) > 0 else 0,
        records_updated=len(update_records),
        timing={
            "total_time": round(total_time, 2),
            "processing_time": round(processing_time, 2),
            "enrichment_time": round(enrichment_time, 2),
            "avg_enrichment_time": round(avg_enrichment_time, 2),
            "update_time": round(update_time, 2),
        },
    )

    # Return results dictionary
    return {
        "chunk_number": chunk_number,
        "chunk_size": chunk_size,
        "total_accounts_in_chunk": len(accounts),
        "total_processed": len(account_data),
        "total_enriched": total_enriched,
        "records_updated": len(update_records),
        "success_rate": round(total_enriched / len(account_data) * 100, 1) if len(account_data) > 0 else 0,
        "timing": {
            "total_time": round(total_time, 2),
            "processing_time": round(processing_time, 2),
            "enrichment_time": round(enrichment_time, 2),
            "avg_enrichment_time": round(avg_enrichment_time, 2),
            "update_time": round(update_time, 2),
        },
    }


if __name__ == "__main__":
    # Simple argument parsing
    chunk_number = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    chunk_size = int(sys.argv[2]) if len(sys.argv) > 2 else 5000

    # Run async function
    result = asyncio.run(enrich_accounts_chunked_async(chunk_number, chunk_size))
    if result:
        # Logger is only available within the async function context
        pass
