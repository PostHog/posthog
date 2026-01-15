import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from django.utils import timezone

import posthoganalytics
from dateutil import parser
from simple_salesforce.format import format_soql

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


def _extract_domain(url: str | None) -> str | None:
    """Extract and normalize domain from URL or domain string.

    Returns:
        Normalized domain (lowercase, no www prefix, no port) or None if invalid
    """
    if not url:
        return None

    try:
        parsed = urlparse(url if url.startswith(("http://", "https://")) else f"https://{url}")
        # Use hostname to get domain without port, fallback to netloc if hostname is None
        domain = parsed.hostname or parsed.netloc or url
    except Exception:
        domain = url

    normalized = domain.lower().strip().removeprefix("www.")
    return normalized or None


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
        "tags": company_data.get("tags", []) if isinstance(company_data.get("tags"), list) else [],
        "tagsV2": company_data.get("tagsV2", []) if isinstance(company_data.get("tagsV2"), list) else [],
    }

    traction_metrics = (
        company_data.get("tractionMetrics", {}) if isinstance(company_data.get("tractionMetrics"), dict) else {}
    )
    for metric_name, metric_data in traction_metrics.items():
        processed_metric = _process_single_metric(metric_data)
        if processed_metric:
            transformed_data["metrics"][metric_name] = processed_metric

    return transformed_data


def _extract_first_tag(tag_list: list, type_filter: str | None = None) -> str | None:
    """Extract first tag with non-empty displayValue, optionally filtered by type."""
    for tag in tag_list:
        if isinstance(tag, dict) and (not type_filter or tag.get("type") == type_filter):
            if value := tag.get("displayValue"):
                return value
    return None


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
    tags = harmonic_data.get("tags", [])
    tags_v2 = harmonic_data.get("tagsV2", [])

    current_metrics = {metric_name: metric_data.get("current_value") for metric_name, metric_data in metrics.items()}

    def get_historical_value(metric_name, period):
        metric_data = metrics.get(metric_name, {})
        historical = metric_data.get("historical", {})
        period_data = historical.get(period, {})
        return period_data.get("value")

    # Extract primary tag from tags array (prefer isPrimaryTag=true, fallback to first tag, then tagsV2)
    primary_tag = None

    if tags:
        # First try isPrimaryTag, then first valid tag
        for tag in tags:
            if isinstance(tag, dict) and tag.get("isPrimaryTag") and (value := tag.get("displayValue")):
                primary_tag = value
                break
        if not primary_tag:
            primary_tag = _extract_first_tag(tags)

    # Fallback to tagsV2: MARKET_VERTICAL first, then any
    if not primary_tag and tags_v2:
        primary_tag = _extract_first_tag(tags_v2, "MARKET_VERTICAL") or _extract_first_tag(tags_v2)

    update_data = {
        "Id": account_id,
        # Company Info
        "harmonic_company_name__c": company_info.get("name"),
        "harmonic_company_type__c": company_info.get("type"),
        "harmonic_industry__c": primary_tag,
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
    logger = LOGGER.bind(function="bulk_update_salesforce_accounts")

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
                        logger.error("Record update error", record_index=i + 1, error=error_msg, fields=error_fields)
                    else:
                        logger.error("Record update error", record_index=i + 1, error="Unknown error", result=result)

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


def get_salesforce_accounts_by_domain(domain: str) -> list[dict[str, Any]]:
    """Query Salesforce for all accounts matching the given domain.

    Args:
        domain: Domain to search for (e.g., "posthog.com")

    Returns:
        List of account record dicts with Id, Name, Website (empty list if none found)
    """
    logger = LOGGER.bind(function="get_salesforce_accounts_by_domain", domain=domain)

    try:
        sf = get_salesforce_client()
    except Exception as e:
        logger.exception("Failed to connect to Salesforce", error=str(e))
        capture_exception(e)
        return []

    # Normalize domain using the same helper function for consistency
    normalized_domain = _extract_domain(domain)
    if not normalized_domain:
        logger.info("Invalid domain provided", domain=domain)
        return []

    # Query pattern: exact match OR subdomain match (with leading dot)
    # Matches: "example.com", "www.example.com", "api.example.com"
    # Does NOT match: "notexample.com", "example.com.evil.com"
    query = format_soql(
        """SELECT Id, Name, Domain__c, CreatedDate
           FROM Account
           WHERE Domain__c = {} OR Domain__c LIKE '%{:like}'
           ORDER BY CreatedDate DESC""",
        normalized_domain,
        f".{normalized_domain}",
    )

    try:
        result = sf.query_all(query)
        accounts = result["records"]
        if accounts:
            logger.info("Found Salesforce accounts", account_count=len(accounts), domain=domain)
            for account in accounts:
                logger.info("  Account", account_id=account["Id"], account_name=account["Name"])
        else:
            logger.info("No Salesforce accounts found for domain", domain=domain)
        return accounts
    except Exception as e:
        logger.exception("Failed to query Salesforce for domain", domain=domain, error=str(e))
        capture_exception(e)
        return []


async def query_salesforce_accounts_chunk_async(sf, offset=0, limit=5000):
    """
    Async version of Salesforce account querying with Redis cache-first approach.

    Args:
        sf: Salesforce client (sync)
        offset: Starting index for pagination
        limit: Number of accounts to retrieve
    """
    logger = LOGGER.bind(function="query_salesforce_accounts_chunk_async", offset=offset, limit=limit)

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


def _fetch_updated_account_fields(
    sf, accounts: list[dict[str, Any]], update_records: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Fetch updated fields from Salesforce accounts after update.

    Dynamically queries only the fields that were actually sent in update_records,
    avoiding errors from querying fields that don't exist in Salesforce.

    Args:
        sf: Salesforce client
        accounts: List of account dicts with at least "Id" key
        update_records: List of dicts we sent to Salesforce (to know which fields to fetch)

    Returns:
        List of dicts containing the updated fields for each account
    """
    logger = LOGGER.bind(function="_fetch_updated_account_fields")

    if not accounts or not update_records:
        return []

    account_ids = [acc["Id"] for acc in accounts]

    # Collect all unique fields from update_records (excluding Id and attributes)
    fields_to_fetch = {"Id", "Name", "Domain__c"}  # Always include these base fields
    for record in update_records:
        for field in record.keys():
            if field not in ("Id", "attributes"):
                fields_to_fetch.add(field)

    fields_list = ", ".join(sorted(fields_to_fetch))

    try:
        query = format_soql(
            f"SELECT {fields_list} FROM Account WHERE Id IN {{}}",
            account_ids,
        )
        result = sf.query_all(query)

        # Return records with only the fields we queried
        return [{field: record.get(field) for field in fields_to_fetch} for record in result["records"]]
    except Exception as e:
        logger.warning(
            "Failed to fetch updated account data",
            account_ids=account_ids,
            fields=fields_list,
            error=str(e),
        )
        return []


def _normalize_datetime_string(value: str) -> datetime | None:
    """Parse a datetime string into a UTC datetime object for comparison."""
    try:
        parsed = parser.parse(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (ValueError, parser.ParserError):
        return None


def _values_match(sent_value: Any, fetched_value: Any) -> bool:
    """Compare two values, handling datetime format differences.

    Salesforce returns dates like "2025-07-23T00:00:00.000+0000"
    but we send them as "2025-07-23T00:00:00Z". These are equivalent.
    """
    if sent_value == fetched_value:
        return True

    # Try datetime comparison if both are strings
    if isinstance(sent_value, str) and isinstance(fetched_value, str):
        sent_dt = _normalize_datetime_string(sent_value)
        fetched_dt = _normalize_datetime_string(fetched_value)
        if sent_dt is not None and fetched_dt is not None:
            return sent_dt == fetched_dt

    return False


def _compare_update_with_fetched(
    update_records: list[dict[str, Any]],
    fetched_accounts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare what we sent to Salesforce with what we got back to detect mismatches.

    Helps catch field name typos and update failures.

    Args:
        update_records: List of dicts we sent to Salesforce (from prepare_salesforce_update_data)
        fetched_accounts: List of dicts fetched back from Salesforce after update

    Returns:
        Dict with comparison results including any mismatches found
    """
    logger = LOGGER.bind(function="_compare_update_with_fetched")

    # Build lookup by account ID
    fetched_by_id = {acc["Id"]: acc for acc in fetched_accounts}
    update_by_id = {rec["Id"]: rec for rec in update_records}

    mismatches = []
    missing_accounts = []

    for account_id, sent_data in update_by_id.items():
        fetched_data = fetched_by_id.get(account_id)

        if not fetched_data:
            missing_accounts.append(account_id)
            continue

        account_mismatches = []
        for field, sent_value in sent_data.items():
            if field in ("Id", "attributes"):
                continue

            fetched_value = fetched_data.get(field)

            # Check if field exists in fetched data
            if field not in fetched_data:
                account_mismatches.append(
                    {
                        "field": field,
                        "issue": "field_not_in_response",
                        "sent": sent_value,
                        "hint": "Possible field name typo - field not returned by Salesforce",
                    }
                )
            elif not _values_match(sent_value, fetched_value):
                account_mismatches.append(
                    {
                        "field": field,
                        "issue": "value_mismatch",
                        "sent": sent_value,
                        "fetched": fetched_value,
                    }
                )

        if account_mismatches:
            mismatches.append(
                {
                    "account_id": account_id,
                    "mismatches": account_mismatches,
                }
            )

    # Log warnings for any issues found
    if mismatches:
        logger.warning(
            "Field mismatches detected between sent and fetched Salesforce data",
            mismatch_count=len(mismatches),
            mismatches=mismatches[:5],
        )

    if missing_accounts:
        logger.warning(
            "Some accounts could not be fetched after update",
            missing_count=len(missing_accounts),
            missing_accounts=missing_accounts,
        )

    return {
        "all_fields_match": len(mismatches) == 0 and len(missing_accounts) == 0,
        "mismatches": mismatches,
        "missing_accounts": missing_accounts,
    }


async def _enrich_specific_domain_debug(
    domain: str,
    chunk_number: int,
    start_time: float,
) -> dict[str, Any]:
    """Debug mode: Enrich a specific domain and update all matching SF accounts.

    Args:
        domain: Already normalized domain to enrich
        chunk_number: For result building
        start_time: For result building

    Returns:
        Dict with enrichment results, summary, and Harmonic data
    """
    logger = LOGGER.bind(domain=domain, mode="debug")

    # Query Salesforce for all accounts matching domain
    accounts = get_salesforce_accounts_by_domain(domain)

    if not accounts:
        return {
            **_build_result(chunk_number, start_time, records_processed=1),
            "summary": {
                "harmonic_data_found": False,
                "salesforce_update_succeeded": False,
                "salesforce_accounts_count": 0,
                "domain": domain,
                "error": "No Salesforce accounts found",
            },
            "error": f"No Salesforce accounts found for domain '{domain}'",
        }

    # Enrich with Harmonic API (once for the domain)
    async with AsyncHarmonicClient() as harmonic_client:
        harmonic_results = await harmonic_client.enrich_companies_batch([domain])
        harmonic_result = harmonic_results[0] if harmonic_results else None

        if not harmonic_result:
            return {
                **_build_result(chunk_number, start_time, records_processed=len(accounts)),
                "summary": {
                    "harmonic_data_found": False,
                    "salesforce_update_succeeded": False,
                    "salesforce_accounts_count": len(accounts),
                    "salesforce_accounts": [f"{acc['Name']} ({acc['Id']})" for acc in accounts],
                    "domain": domain,
                    "error": "No Harmonic data found",
                },
                "error": f"No Harmonic data found for domain '{domain}'",
            }

        # Transform Harmonic data
        harmonic_data = transform_harmonic_data(harmonic_result)

        if not harmonic_data:
            return {
                **_build_result(chunk_number, start_time, records_processed=len(accounts)),
                "summary": {
                    "harmonic_data_found": False,
                    "salesforce_update_succeeded": False,
                    "salesforce_accounts_count": len(accounts),
                    "salesforce_accounts": [f"{acc['Name']} ({acc['Id']})" for acc in accounts],
                    "domain": domain,
                    "error": "Failed to transform Harmonic data",
                },
                "error": f"Failed to transform Harmonic data for domain '{domain}'",
            }

        # Prepare Salesforce updates for all matching accounts
        update_records = []
        for account in accounts:
            update_data = prepare_salesforce_update_data(account["Id"], harmonic_data)
            if update_data:
                update_records.append(update_data)

        # Execute bulk update for all accounts
        salesforce_updated = False
        update_error = None
        records_updated = 0
        updated_salesforce_accounts = []
        field_comparison = None

        try:
            if update_records:
                sf = get_salesforce_client()
                bulk_update_salesforce_accounts(sf, update_records)
                salesforce_updated = True
                records_updated = len(update_records)
                logger.info(
                    "Successfully updated Salesforce accounts",
                    accounts_updated=records_updated,
                )

                updated_salesforce_accounts = _fetch_updated_account_fields(sf, accounts, update_records)

                # Compare what we sent with what we got back to detect field mismatches
                field_comparison = _compare_update_with_fetched(update_records, updated_salesforce_accounts)
            else:
                update_error = "Failed to prepare Salesforce update data for any accounts"
        except Exception as e:
            update_error = f"Salesforce update failed: {str(e)}"
            logger.exception(
                "Failed to update Salesforce",
                accounts_count=len(accounts),
                error=str(e),
            )
            capture_exception(e)

        summary = {
            "harmonic_data_found": True,
            "salesforce_update_succeeded": salesforce_updated,
            "salesforce_accounts_count": len(accounts),
            "salesforce_accounts": [f"{acc['Name']} ({acc['Id']})" for acc in accounts],
            "accounts_updated": records_updated,
            "domain": domain,
            "all_fields_match": field_comparison["all_fields_match"] if field_comparison else None,
        }
        if update_error:
            summary["error"] = update_error

        return {
            **_build_result(
                chunk_number,
                start_time,
                records_processed=len(accounts),
                records_enriched=1,
                records_updated=records_updated,
            ),
            "summary": summary,
            "enriched_data": harmonic_data,
            "raw_harmonic_response": harmonic_result,
            "updated_salesforce_accounts": updated_salesforce_accounts,
            "field_comparison": field_comparison,
            "error": update_error,
        }


async def enrich_accounts_chunked_async(
    chunk_number: int,
    chunk_size: int,
    estimated_total_chunks: int | None,
    start_time: float,
) -> dict[str, Any]:
    """Production mode: Enrich a chunk of Salesforce accounts with Harmonic data.

    Standard workflow that:
    1. Queries chunk of Salesforce accounts (from global Redis cache)
    2. Enriches business domains with Harmonic API (default: 5 concurrent requests)
    3. Updates Salesforce in batches of 200 using sObject Collections

    Args:
        chunk_number: Zero-based chunk index
        chunk_size: Accounts per chunk (default: 5000)
        estimated_total_chunks: For progress logging
        start_time: For timing calculations

    Returns:
        Dict with total_accounts_in_chunk, records_processed, records_enriched, etc.
    """
    logger = LOGGER.bind(function="enrich_accounts_chunked_async", chunk_number=chunk_number)
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

    # Query accounts from Redis cache
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

        domain = _extract_domain(website)
        if not domain or is_excluded_domain(domain):
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
                    harmonic_data = transform_harmonic_data(harmonic_result)

                    if harmonic_data:
                        total_enriched += 1
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


async def enrich_accounts_async(
    chunk_number: int = 0,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    estimated_total_chunks: int | None = None,
    specific_domain: str | None = None,
) -> dict[str, Any]:
    """Entry point for Salesforce account enrichment.

    Routes to either:
    - Production mode: Process a chunk of accounts from Salesforce
    - Debug mode: Enrich a specific domain and update matching SF accounts

    Args:
        chunk_number: Zero-based chunk index (production mode)
        chunk_size: Accounts per chunk (production mode)
        estimated_total_chunks: For progress logging (production mode)
        specific_domain: Domain to enrich directly (debug mode)

    Returns:
        Dict with enrichment results. Structure varies by mode.
    """
    start_time = time.time()

    # Debug mode: enrich specific domain
    if specific_domain:
        domain = _extract_domain(specific_domain)

        if not domain or is_excluded_domain(domain):
            return {
                **_build_result(chunk_number, start_time, records_processed=1),
                "summary": {
                    "harmonic_data_found": False,
                    "salesforce_update_succeeded": False,
                    "domain": domain,
                    "error": "Domain excluded (personal email domain)",
                },
                "error": f"Domain '{domain}' is excluded (personal email domain)",
            }

        return await _enrich_specific_domain_debug(domain, chunk_number, start_time)

    # Production mode: process chunk of accounts
    return await enrich_accounts_chunked_async(chunk_number, chunk_size, estimated_total_chunks, start_time)
