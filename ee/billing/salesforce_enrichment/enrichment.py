import sys
import time
from datetime import datetime
from urllib.parse import urlparse

from posthog.temporal.common.logger import get_internal_logger
from .harmonic_client import HarmonicClient
from .salesforce_client import SalesforceClient

# List of common personal email domains
PERSONAL_EMAIL_DOMAINS = {
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "aol.com",
    "icloud.com",
    "protonmail.com",
    "zoho.com",
    "yandex.com",
    "live.com",
    "msn.com",
    "me.com",
    "mac.com",
    "gmx.com",
    "yahoo.co.uk",
    "yahoo.co.jp",
    "yahoo.co.in",
    "yahoo.com.au",
    "yahoo.com.sg",
    "yahoo.com.ph",
    "yahoo.com.my",
    "yahoo.com.hk",
    "yahoo.com.tw",
    "yahoo.com.vn",
    "yahoo.com.br",
    "yahoo.com.ar",
    "yahoo.com.mx",
    "yahoo.com.tr",
    "yahoo.com.ua",
    "yahoo.com.eg",
    "yahoo.com.sa",
    "yahoo.com.ae",
    "yahoo.com.kr",
    "yahoo.com.cn",
    "yahoo.com.ru",
    "yahoo.com.id",
    "yahoo.com.th",
    "yahoo.com.ve",
    "yahoo.com.pe",
    "yahoo.com.cl",
    "yahoo.com.co",
    "yahoo.com.ec",
    "yahoo.com.uy",
    "yahoo.com.py",
    "yahoo.com.bo",
    "yahoo.com.do",
    "yahoo.com.pr",
    "yahoo.com.gt",
    "yahoo.com.sv",
    "yahoo.com.hn",
    "yahoo.com.ni",
    "yahoo.com.cr",
    "yahoo.com.pa",
}


def is_personal_domain(domain):
    """Check if a domain is a personal email domain."""
    if not domain:
        return True

    # Clean the domain first
    domain = domain.lower().strip()
    if domain.startswith("www."):
        domain = domain.replace("www.", "", 1)

    # Extract the main domain (last two parts)
    parts = domain.split(".")
    if len(parts) >= 2:
        main_domain = ".".join(parts[-2:])
        return main_domain in PERSONAL_EMAIL_DOMAINS

    return False


def transform_harmonic_data(company_data):
    """Transform raw Harmonic GraphQL response to expected format."""
    if not company_data or not isinstance(company_data, dict):
        return None

    # Transform the data into the expected format with safe access
    website_data = company_data.get("website") or {}
    founding_data = company_data.get("foundingDate") or {}

    transformed_data = {
        "company_info": {
            "name": company_data.get("name"),
            "type": company_data.get("companyType"),
            "website": website_data.get("url") if isinstance(website_data, dict) else None,
            "description": company_data.get("description"),
            "location": None,  # Location is null in the response
            "founding_date": founding_data.get("date") if isinstance(founding_data, dict) else None,
        },
        "funding": company_data.get("funding", {}),
        "metrics": {},
    }

    # Remove debug logging to keep output concise

    # Transform metrics data
    traction_metrics = company_data.get("tractionMetrics", {})
    for metric_name, metric_data in traction_metrics.items():
        if metric_data and metric_data.get("latestMetricValue") is not None:
            transformed_data["metrics"][metric_name] = {
                "current_value": metric_data["latestMetricValue"],
                "historical": {},
            }

            # Process historical data
            historical_data = metric_data.get("metrics", [])

            # We need to find the value closest to each target period
            # Target days for each period (looking back from today)
            target_days = {"14d": 14, "30d": 30, "90d": 90, "180d": 180, "365d": 365}

            # Initialize best matches for each period
            best_matches = {}

            for metric in historical_data:
                if not metric.get("timestamp") or metric.get("metricValue") is None:
                    continue

                date_str = metric["timestamp"].split("T")[0]
                metric_date = datetime.strptime(date_str, "%Y-%m-%d")
                days_ago = (datetime.now().date() - metric_date.date()).days

                # For each target period, find the closest match
                for period, target in target_days.items():
                    # Skip if this metric is too recent for this period
                    if days_ago < target - 7:  # Allow 7 days tolerance before target
                        continue

                    # Calculate how close this metric is to the target
                    distance = abs(days_ago - target)

                    # Update if this is closer to the target than previous best
                    if period not in best_matches or distance < best_matches[period]["distance"]:
                        best_matches[period] = {
                            "value": metric["metricValue"],
                            "distance": distance,
                            "days_ago": days_ago,
                            "date": date_str,
                        }

            # Store the best matches in the transformed data
            current_value = transformed_data["metrics"][metric_name]["current_value"]
            for period, match in best_matches.items():
                historical_value = match["value"]
                transformed_data["metrics"][metric_name].setdefault("historical", {})[period] = {
                    "value": historical_value,
                    "change": current_value - historical_value,
                    "percent_change": (
                        round((current_value - historical_value) / historical_value * 100, 2)
                        if historical_value != 0
                        else 0
                    ),
                }

    return transformed_data


def prepare_salesforce_update_data(account_id, harmonic_data):
    """Prepare Salesforce update data for bulk update."""
    if not harmonic_data:
        return None

    # Get funding info, company info, and metrics
    funding = harmonic_data.get("funding", {})
    company_info = harmonic_data.get("company_info", {})
    metrics = harmonic_data.get("metrics", {})

    current_metrics = {metric_name: metric_data.get("current_value") for metric_name, metric_data in metrics.items()}

    # Get historical data for specific periods
    def get_historical_value(metric_name, period):
        metric_data = metrics.get(metric_name, {})
        historical = metric_data.get("historical", {})
        period_data = historical.get(period, {})
        return period_data.get("value")

    # Prepare update data
    update_data = {
        "Id": account_id,
        # Company Info
        "harmonic_company_name__c": company_info.get("name"),
        "harmonic_company_type__c": company_info.get("type"),
        "harmonic_last_update__c": datetime.now().strftime("%Y-%m-%d"),
        "Founded_year__c": (
            int(company_info.get("founding_date", "").split("-")[0]) if company_info.get("founding_date") else None
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
    """Update Salesforce accounts using sObject Collections for optimal bulk updates."""
    logger = get_internal_logger()

    if not update_records:
        logger.info("No records to update")
        return

    logger.info("Starting optimized bulk update", total_records=len(update_records))

    # Split into batches of 200 (sObject Collections limit - 8x more efficient than Composite API)
    batch_size = 200
    batches = [update_records[i : i + batch_size] for i in range(0, len(update_records), batch_size)]

    total_success = 0
    total_errors = 0

    for batch_num, batch in enumerate(batches, 1):
        logger.info("Processing batch", batch_number=batch_num, total_batches=len(batches), batch_size=len(batch))

        try:
            # Use sObject Collections API for bulk updates (more efficient than Composite API)
            # This allows up to 200 records per API call vs 25 for Composite API
            # Using correct endpoint: composite/sobjects with PATCH method and attributes
            records_with_attributes = [{**record, "attributes": {"type": "Account"}} for record in batch]

            response = sf.restful(
                "composite/sobjects",
                method="PATCH",
                json={
                    "allOrNone": False,  # Continue processing even if some records fail
                    "records": records_with_attributes,
                },
            )

            # Process results from sObject Collections response
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
                    # Log errors for debugging
                    errors = result.get("errors", [])
                    if errors:
                        error_msg = errors[0].get("message", "Unknown error")
                        error_fields = errors[0].get("fields", [])
                        logger.error("Record update error", record_index=i + 1, error=error_msg, fields=error_fields)
                    else:
                        logger.error("Record update error", record_index=i + 1, error="Unknown error", result=result)

            total_success += batch_success
            total_errors += batch_errors

            if batch_errors > 0:
                logger.warning(
                    "Batch completed with errors",
                    batch_number=batch_num,
                    success_count=batch_success,
                    error_count=batch_errors,
                )

        except Exception as e:
            logger.exception("Batch processing failed", batch_number=batch_num, error=str(e))
            total_errors += len(batch)

    success_rate = (total_success / len(update_records) * 100) if len(update_records) > 0 else 0
    logger.info(
        "Bulk update completed",
        total_success=total_success,
        total_records=len(update_records),
        success_rate=round(success_rate, 1),
    )


def query_salesforce_accounts_chunk(sf, offset=0, limit=5000, workflow_id=None):
    """
    Query Salesforce accounts in chunks with Redis cache-first approach.

    Args:
        sf: Salesforce client
        offset: Starting index for pagination
        limit: Number of accounts to retrieve
        workflow_id: Optional workflow ID for Redis cache retrieval
    """

    # Redis cache not available in sync context, fallback to Salesforce

    # Fallback to traditional Salesforce query
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
        time.time() - sf_start

        # Paginate in memory
        start_idx = offset
        end_idx = min(offset + limit, len(accounts["records"]))

        if start_idx >= len(accounts["records"]):
            return []

        chunk_records = accounts["records"][start_idx:end_idx]

        return chunk_records
    except Exception:
        return []


def enrich_accounts_chunked(
    chunk_number: int = 0,
    chunk_size: int = 5000,
    estimated_total_chunks: int | None = None,
    workflow_id: str | None = None,
):
    get_internal_logger()
    """
    Enrich Salesforce accounts with Harmonic data.

    Args:
        chunk_number: Which chunk to process (0-based index)
        chunk_size: Number of accounts per chunk

    Returns:
        dict: Results with statistics
    """
    start_time = time.time()
    offset = chunk_number * chunk_size

    # Display chunk progress with estimated total
    if estimated_total_chunks:
        pass
    else:
        pass

    # Initialize Salesforce client
    time.time()
    try:
        sf_client = SalesforceClient()
        sf = sf_client.client  # Get the underlying simple-salesforce client
    except Exception:
        return

    # Initialize Harmonic client
    time.time()
    try:
        harmonic_client = HarmonicClient()
    except Exception:
        return

    try:
        # Query accounts in this chunk (with Redis cache-first approach)
        query_start = time.time()
        accounts = query_salesforce_accounts_chunk(sf, offset, chunk_size, workflow_id)
        query_time = time.time() - query_start
        if not accounts:
            return

        # Track statistics
        total_processed = 0
        total_enriched = 0
        total_failed = 0
        update_records = []
        enrichment_time = 0

        # Process each account and collect data
        processing_start = time.time()
        for i, account in enumerate(accounts):
            account_id = account["Id"]
            website = account["Website"]

            # Progress indicator every 10 accounts
            if (i + 1) % 10 == 0:
                pass

            try:
                parsed = urlparse(website if website.startswith(("http://", "https://")) else f"https://{website}")
                domain = parsed.netloc
            except Exception:
                continue

            # Skip personal domains
            if is_personal_domain(domain):
                continue

            total_processed += 1

            # Get enrichment data from Harmonic
            try:
                api_start = time.time()
                company_data = harmonic_client.enrich_company_by_domain(domain)
                api_time = time.time() - api_start
                enrichment_time += api_time

                if company_data:
                    # Transform the raw GraphQL response to expected format
                    harmonic_data = transform_harmonic_data(company_data)

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
            except Exception:
                total_failed += 1

            # Print progress stats every 200 accounts
            if (i + 1) % 200 == 0:
                elapsed = time.time() - processing_start
                avg_time = elapsed / (i + 1)
                remaining = len(accounts) - (i + 1)
                remaining * avg_time
                (total_enriched / total_processed * 100) if total_processed > 0 else 0

        # Perform batch update
        if update_records:
            update_start = time.time()
            bulk_update_salesforce_accounts(sf, update_records)
            update_time = time.time() - update_start
        else:
            update_time = 0

        # Print final statistics with timing
        total_time = time.time() - start_time
        processing_time = time.time() - processing_start
        avg_enrichment_time = enrichment_time / total_processed if total_processed > 0 else 0

        # Return results dictionary
        return {
            "chunk_number": chunk_number,
            "chunk_size": chunk_size,
            "total_accounts_in_chunk": len(accounts),
            "total_processed": total_processed,
            "total_enriched": total_enriched,
            "records_updated": len(update_records),
            "success_rate": round(total_enriched / total_processed * 100, 1) if total_processed > 0 else 0,
            "timing": {
                "total_time": round(total_time, 2),
                "salesforce_query_time": round(query_time, 2),
                "processing_time": round(processing_time, 2),
                "enrichment_time": round(enrichment_time, 2),
                "avg_enrichment_time": round(avg_enrichment_time, 2),
                "update_time": round(update_time, 2),
            },
        }

    except Exception as e:
        return {"chunk_number": chunk_number, "chunk_size": chunk_size, "error": str(e), "success_rate": 0}


if __name__ == "__main__":
    # Simple argument parsing
    chunk_number = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    chunk_size = int(sys.argv[2]) if len(sys.argv) > 2 else 5000

    result = enrich_accounts_chunked(chunk_number, chunk_size)
    if result:
        pass
