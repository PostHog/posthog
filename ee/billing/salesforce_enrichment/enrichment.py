import time
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from django.utils import timezone

import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.logger import get_logger

from .constants import (
    DEFAULT_CHUNK_SIZE,
    HARMONIC_BATCH_SIZE,
    METRIC_PERIODS,
    PERSONAL_EMAIL_DOMAINS,
    SALESFORCE_UPDATE_BATCH_SIZE,
)
from .harmonic_client import AsyncHarmonicClient
from .redis_cache import get_accounts_from_redis
from .salesforce_client import get_salesforce_client

LOGGER = get_logger(__name__)


def is_excluded_domain(domain: str | None) -> bool:
    """Check if domain should be excluded from enrichment (personal email domains, etc)."""
    if not domain:
        return True

    domain = domain.lower().strip().removeprefix("www.")

    if not domain:
        return True

    # Check full domain first (handles yahoo.co.uk, yahoo.com.au, etc.)
    if domain in PERSONAL_EMAIL_DOMAINS:
        return True

    # Fall back to main domain (last two parts) for standard domains
    parts = domain.split(".")
    if len(parts) >= 2:
        main_domain = ".".join(parts[-2:])
        return main_domain in PERSONAL_EMAIL_DOMAINS

    return False


def _calculate_historical_matches(historical_data: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Calculate best historical matches for target periods from time-series data.

    Args:
        historical_data: List of metrics with timestamp and metricValue

    Returns:
        Dict mapping period -> {value, distance, days_ago, date}
    """
    best_matches: dict[str, dict[str, Any]] = {}

    for metric in historical_data:
        if not metric.get("timestamp") or metric.get("metricValue") is None:
            continue

        date_str = metric["timestamp"].split("T")[0]
        metric_date = datetime.strptime(date_str, "%Y-%m-%d")
        days_ago = (datetime.now().date() - metric_date.date()).days

        # For each target period, find the closest match
        for period, target in METRIC_PERIODS.items():
            # Calculate how close this metric is to the target
            distance = abs(days_ago - target)

            # Skip if more than 16 days from target (data is typically monthly)
            if distance > 16:
                continue

            # Update if this is closer to the target than previous best
            if period not in best_matches or distance < best_matches[period]["distance"]:
                best_matches[period] = {
                    "value": metric["metricValue"],
                    "distance": distance,
                    "days_ago": days_ago,
                    "date": date_str,
                }

    return best_matches


def _process_single_metric(metric_data: dict[str, Any]) -> dict[str, Any] | None:
    """Process a single metric from Harmonic API response.

    Args:
        metric_data: Raw metric data from Harmonic API

    Returns:
        Processed metric with current_value and historical data, or None if invalid
    """
    if not metric_data or metric_data.get("latestMetricValue") is None:
        return None

    processed_metric = {
        "current_value": metric_data["latestMetricValue"],
        "historical": {},
    }

    historical_data = metric_data.get("metrics", [])
    if historical_data:
        best_matches = _calculate_historical_matches(historical_data)

        for period, match in best_matches.items():
            processed_metric["historical"][period] = {"value": match["value"]}

    return processed_metric


def transform_harmonic_data(company_data: dict[str, Any]) -> dict[str, Any] | None:
    """Transform Harmonic API response into Salesforce field format.

    Args:
        company_data: Raw GraphQL response from Harmonic API

    Returns:
        Dict with funding, company_info, and metrics for Salesforce update
    """
    if not company_data or not isinstance(company_data, dict):
        return None

    website_data = company_data.get("website") or {}
    founding_data = company_data.get("foundingDate") or {}

    transformed_data = {
        "company_info": {
            "name": company_data.get("name"),
            "type": company_data.get("companyType"),
            "website": website_data.get("url") if isinstance(website_data, dict) else None,
            "description": company_data.get("description"),
            "founding_date": founding_data.get("date") if isinstance(founding_data, dict) else None,
        },
        "funding": company_data.get("funding", {}) if isinstance(company_data.get("funding"), dict) else {},
        "metrics": {},
    }

    traction_metrics = (
        company_data.get("tractionMetrics", {}) if isinstance(company_data.get("tractionMetrics"), dict) else {}
    )
    for metric_name, metric_data in traction_metrics.items():
        processed_metric = _process_single_metric(metric_data)
        if processed_metric:
            transformed_data["metrics"][metric_name] = processed_metric

    return transformed_data


def prepare_salesforce_update_data(account_id: str, harmonic_data: dict[str, Any]) -> dict[str, Any] | None:
    """Convert enriched data to Salesforce field mappings for bulk update.

    Args:
        account_id: Salesforce Account.Id
        harmonic_data: Output from transform_harmonic_data()

    Returns:
        Dict ready for Salesforce sObject Collections API
    """
    if not harmonic_data:
        return None

    funding = harmonic_data.get("funding", {})
    company_info = harmonic_data.get("company_info", {})
    metrics = harmonic_data.get("metrics", {})

    current_metrics = {metric_name: metric_data.get("current_value") for metric_name, metric_data in metrics.items()}

    def get_historical_value(metric_name, period):
        metric_data = metrics.get(metric_name, {})
        historical = metric_data.get("historical", {})
        period_data = historical.get(period, {})
        return period_data.get("value")

    update_data = {
        "Id": account_id,
        # Company Info
        "harmonic_company_name__c": company_info.get("name"),
        "harmonic_company_type__c": company_info.get("type"),
        "harmonic_last_update__c": timezone.now().strftime("%Y-%m-%d"),
        "Founded_year__c": (
            int(company_info.get("founding_date", "").split("-")[0])
            if company_info.get("founding_date") and "-" in company_info.get("founding_date", "")
            else None
        ),
        # Funding Info
        "harmonic_last_funding__c": funding.get("lastFundingTotal"),
        "Last_Funding_Date__c": funding.get("lastFundingAt"),
        "Total_Funding__c": funding.get("fundingTotal"),
        "harmonic_funding_stage__c": funding.get("fundingStage"),
        # Current Metrics
        "harmonic_headcount__c": current_metrics.get("headcount"),
        "harmonic_headcountEngineering__c": current_metrics.get("headcountEngineering"),
        "harmonic_linkedinFollowerCount__c": current_metrics.get("linkedinFollowerCount"),
        "harmonic_twitterFollowerCount__c": current_metrics.get("twitterFollowerCount"),
        "harmonic_web_traffic__c": current_metrics.get("webTraffic"),
        # 90d Historical Data
        "harmonic_headcount_90d__c": get_historical_value("headcount", "90d"),
        "harmonic_headcountEngineering_90d__c": get_historical_value("headcountEngineering", "90d"),
        "harmonic_linkedinFollowerCount_90d__c": get_historical_value("linkedinFollowerCount", "90d"),
        "harmonic_twitterFollowerCount_90d__c": get_historical_value("twitterFollowerCount", "90d"),
        "harmonic_web_traffic_90d__c": get_historical_value("webTraffic", "90d"),
        # 180d Historical Data
        "harmonic_headcount_180d__c": get_historical_value("headcount", "180d"),
        "harmonic_headcountEngineering_180d__c": get_historical_value("headcountEngineering", "180d"),
        "harmonic_linkedinFollowerCount_180d__c": get_historical_value("linkedinFollowerCount", "180d"),
        "harmonic_twitterFollowerCount_180d__c": get_historical_value("twitterFollowerCount", "180d"),
        "harmonic_web_traffic_180d__c": get_historical_value("webTraffic", "180d"),
    }

    # Remove None values to avoid Salesforce errors
    filtered_update_data = {k: v for k, v in update_data.items() if v is not None}

    return filtered_update_data


def bulk_update_salesforce_accounts(sf, update_records):
    """Update Salesforce accounts in batches of 200 using sObject Collections API.

    Args:
        sf: simple_salesforce.Salesforce client
        update_records: List of dicts with Id + field updates
    """
    logger = LOGGER.bind()

    if not update_records:
        return

    # Split records into batches of 200 (Salesforce sObject Collections API limit)
    batches = [
        update_records[i : i + SALESFORCE_UPDATE_BATCH_SIZE]
        for i in range(0, len(update_records), SALESFORCE_UPDATE_BATCH_SIZE)
    ]

    total_success = 0
    total_errors = 0

    for batch_idx, batch in enumerate(batches):
        try:
            records_with_attributes = [{**record, "attributes": {"type": "Account"}} for record in batch]

            response = sf.restful(
                "composite/sobjects",
                method="PATCH",
                json={
                    "allOrNone": False,
                    "records": records_with_attributes,
                },
            )

            batch_success = 0
            batch_errors = 0

            for i, result in enumerate(response):
                # Check for success field first (proper sObject Collections response)
                if result.get("success"):
                    batch_success += 1
                elif result.get("id"):  # Fallback - record has an ID
                    batch_success += 1
                else:
                    batch_errors += 1
                    errors = result.get("errors", [])
                    if errors:
                        error_msg = errors[0].get("message", "Unknown error")
                        error_fields = errors[0].get("fields", [])
                        logger.exception(
                            "Record update error", record_index=i + 1, error=error_msg, fields=error_fields
                        )
                    else:
                        logger.exception(
                            "Record update error", record_index=i + 1, error="Unknown error", result=result
                        )

            total_success += batch_success
            total_errors += batch_errors

        except Exception as e:
            logger.exception("Batch processing failed", batch_number=batch_idx + 1, error=str(e))
            capture_exception(e)
            total_errors += len(batch)

    success_rate = (total_success / len(update_records) * 100) if len(update_records) > 0 else 0
    logger.info(
        "Bulk update completed",
        total_success=total_success,
        total_records=len(update_records),
        success_rate=round(success_rate, 1),
    )


async def query_salesforce_accounts_chunk_async(sf, offset=0, limit=5000):
    """
    Async version of Salesforce account querying with Redis cache-first approach.

    Args:
        sf: Salesforce client (sync)
        offset: Starting index for pagination
        limit: Number of accounts to retrieve
    """
    logger = LOGGER.bind()

    # Try Redis cache first
    cache_start = time.time()
    try:
        cached_accounts = await get_accounts_from_redis(offset, limit)
        cache_time = time.time() - cache_start

        if cached_accounts is not None:
            logger.info("Redis cache hit", accounts_count=len(cached_accounts), cache_time=round(cache_time, 3))
            return cached_accounts
    except Exception as e:
        cache_time = time.time() - cache_start
        logger.exception("Redis cache error", error=str(e), cache_time=round(cache_time, 3))
        capture_exception(e)

    # Fallback to Salesforce query
    query = """
        SELECT Id, Name, Website, CreatedDate
        FROM Account
        WHERE Website != null
        ORDER BY CreatedDate DESC
    """

    try:
        accounts = sf.query_all(query)

        start_idx = offset
        end_idx = min(offset + limit, len(accounts["records"]))

        if start_idx >= len(accounts["records"]):
            return []

        chunk_records = accounts["records"][start_idx:end_idx]

        return chunk_records
    except Exception as e:
        logger.exception("Salesforce query failed", error=str(e))
        capture_exception(e)
        return []


def _build_result(
    chunk_number: int,
    start_time: float,
    records_processed: int = 0,
    records_enriched: int = 0,
    records_updated: int = 0,
    total_accounts_in_chunk: int = 0,
    errors: list[str] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Build consistent result object for chunk processing.

    Note: total_accounts_in_chunk is needed for workflow stopping logic.
    """
    success_rate = round(records_enriched / records_processed * 100, 1) if records_processed > 0 else 0
    return {
        "chunk_number": chunk_number,
        "records_processed": records_processed,
        "records_enriched": records_enriched,
        "records_updated": records_updated,
        "success_rate": success_rate,
        "total_time": round(time.time() - start_time, 2),
        "total_accounts_in_chunk": total_accounts_in_chunk,
        "errors": errors or ([error] if error else []),
    }


async def enrich_accounts_chunked_async(
    chunk_number: int = 0,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    estimated_total_chunks: int | None = None,
) -> dict[str, Any]:
    """Enrich Salesforce accounts with Harmonic data using concurrent API calls.

    Main workflow function that:
    1. Queries chunk of Salesforce accounts (with global Redis caching)
    2. Enriches business domains with Harmonic API (5 concurrent requests)
    3. Updates Salesforce in batches of 200 using sObject Collections

    Args:
        chunk_number: Zero-based chunk index
        chunk_size: Accounts per chunk (default: 5000)
        estimated_total_chunks: For progress logging

    Returns:
        Dict with total_accounts_in_chunk (critical for workflow control), records_processed,
        records_enriched, records_updated, success_rate, errors
    """
    logger = LOGGER.bind()
    start_time = time.time()
    offset = chunk_number * chunk_size

    log_context = {"chunk_number": chunk_number, "chunk_size": chunk_size}
    if estimated_total_chunks:
        log_context["estimated_total_chunks"] = estimated_total_chunks

    # Initialize Salesforce client
    try:
        sf = get_salesforce_client()
    except Exception as e:
        logger.exception("Failed to connect to Salesforce", error=str(e))
        capture_exception(e)
        return _build_result(chunk_number, start_time, error=str(e))

    # Query accounts
    try:
        accounts = await query_salesforce_accounts_chunk_async(sf, offset, chunk_size)
        if not accounts:
            return _build_result(chunk_number, start_time)
    except Exception as e:
        logger.exception("Failed to query accounts", error=str(e))
        capture_exception(e)
        return _build_result(chunk_number, start_time, error=str(e))

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

        if is_excluded_domain(domain):
            continue

        account_data.append({"account_id": account_id, "domain": domain, "account": account})

    if not account_data:
        return _build_result(chunk_number, start_time, total_accounts_in_chunk=len(accounts))

    total_enriched = 0
    total_failed = 0
    update_records = []

    # Process in batches with rate limiting (5 req/sec)
    async with AsyncHarmonicClient() as harmonic_client:
        for batch_start in range(0, len(account_data), HARMONIC_BATCH_SIZE):
            batch_end = min(batch_start + HARMONIC_BATCH_SIZE, len(account_data))
            batch = account_data[batch_start:batch_end]

            # Extract domains for this batch
            batch_domains = [item["domain"] for item in batch]

            # Make concurrent Harmonic API calls
            harmonic_results = await harmonic_client.enrich_companies_batch(batch_domains)

            for account_info, harmonic_result in zip(batch, harmonic_results):
                account_id = account_info["account_id"]

                if harmonic_result:
                    # Transform the raw GraphQL response
                    harmonic_data = transform_harmonic_data(harmonic_result)

                    if harmonic_data:
                        total_enriched += 1
                        # Prepare update_data
                        update_data = prepare_salesforce_update_data(account_id, harmonic_data)
                        if update_data:
                            update_records.append(update_data)
                        else:
                            total_failed += 1
                    else:
                        total_failed += 1
                else:
                    total_failed += 1

    # Update Salesforce accounts
    if update_records:
        bulk_update_salesforce_accounts(sf, update_records)

    result = _build_result(
        chunk_number=chunk_number,
        start_time=start_time,
        records_processed=len(account_data),
        records_enriched=total_enriched,
        records_updated=len(update_records),
        total_accounts_in_chunk=len(accounts),
    )

    if result["records_processed"] > 0 or result["errors"]:
        logger.info("Chunk completed", **{**log_context, **result})

        try:
            posthoganalytics.capture(
                distinct_id="internal_billing_events",
                event="salesforce_enrichment_chunk_completed",
                properties={
                    **log_context,
                    **result,
                    "errors_count": len(result.get("errors", [])),
                },
            )
        except Exception:
            pass

    return result
