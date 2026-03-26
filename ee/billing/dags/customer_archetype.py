"""Customer Archetype Classification — Dagster ETL Pipeline.

Classifies Salesforce accounts as "AI Native", "Cloud Native", or "Unknown"
using LLM-based classification, computes use case adoption from MRR data,
and pushes results back to Salesforce.

The pipeline uses a graph_asset with DynamicOutput to process accounts in
batches (~1000 each). Each accounts batch classifies via LLM and pushes
to Salesforce immediately, so partial progress survives failures. A
Salesforce timestamp field (customer_archetype_classified_at__c) enables
incremental processing on re-runs.
"""

import os
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, TypedDict

import polars as pl
import dagster
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential, wait_random

from posthog.hogql.constants import LimitContext
from posthog.hogql.query import execute_hogql_query

from posthog.dags.common import JobOwners
from posthog.llm.gateway_client import get_llm_client
from posthog.models import Team

from ee.billing.dags.customer_archetype_prompt import SYSTEM_PROMPT
from ee.billing.salesforce_enrichment.enrichment import bulk_update_salesforce_accounts
from ee.billing.salesforce_enrichment.salesforce_client import get_salesforce_client

ARCHETYPE_TEAM_ID = 2

# MRR thresholds for use case adoption levels (in dollars)
MRR_THRESHOLD_SIGNIFICANT = 500
MRR_THRESHOLD_ADOPTED = 100


class ArchetypeClassificationConfig(dagster.Config):
    llm_max_workers: int = 20
    llm_max_concurrent_requests: int = 5
    llm_batch_size: int = 10
    accounts_batch_size: int = 1000
    skip_classified_within_days: int = 7


# All columns from the PostHog_Customer_Archetype saved query
COLUMNS = [
    "sf_account_id",
    "name",
    "posthog_organization_id",
    "harmonic_industry_c",
    "founded_year_c",
    "number_of_employees",
    "harmonic_headcount_c",
    "harmonic_headcount_engineering_c",
    "pct_engineers_c",
    "harmonic_is_yc_company_c",
    "tech_tag_c",
    "harmonic_funding_stage_c",
    "harmonic_total_funding_c",
    "total_funding_raised_c",
    "billing_country",
    "business_model_c",
    "clearbit_business_model_c",
    "clay_industry_c",
    "has_llm_analytics",
    "distinct_products_used",
    # MRR columns for use case adoption
    "latest_product_analytics_mrr",
    "latest_surveys_mrr",
    "latest_web_analytics_mrr_est",
    "latest_posthog_ai_mrr",
    "latest_feature_flags_mrr",
    "latest_session_replay_mrr",
    "latest_mobile_replay_mrr",
    "latest_error_tracking_mrr",
    "latest_logs_mrr",
    "latest_llm_analytics_mrr",
    "latest_data_warehouse_mrr",
    "latest_data_pipelines_mrr",
    "latest_batch_exports_mrr",
    "latest_realtime_destinations_mrr",
]

# Columns passed to the LLM as classification context
LLM_CONTEXT_COLUMNS = [
    "sf_account_id",
    "name",
    "harmonic_industry_c",
    "founded_year_c",
    "number_of_employees",
    "harmonic_headcount_c",
    "harmonic_headcount_engineering_c",
    "pct_engineers_c",
    "harmonic_is_yc_company_c",
    "tech_tag_c",
    "harmonic_funding_stage_c",
    "harmonic_total_funding_c",
    "total_funding_raised_c",
    "billing_country",
    "business_model_c",
    "clearbit_business_model_c",
    "clay_industry_c",
    "has_llm_analytics",
    "distinct_products_used",
]

# Use case → MRR column mapping
USE_CASE_MRR_MAPPING: dict[str, list[str]] = {
    "uc_product_intelligence": [
        "latest_product_analytics_mrr",
        "latest_surveys_mrr",
        "latest_web_analytics_mrr_est",
        "latest_posthog_ai_mrr",
    ],
    "uc_release_eng": [
        "latest_feature_flags_mrr",
    ],
    "uc_observability": [
        "latest_session_replay_mrr",
        "latest_mobile_replay_mrr",
        "latest_error_tracking_mrr",
        "latest_logs_mrr",
    ],
    "uc_ai_llm_obs": [
        "latest_llm_analytics_mrr",
    ],
    "uc_data_infra": [
        "latest_data_warehouse_mrr",
        "latest_data_pipelines_mrr",
        "latest_batch_exports_mrr",
        "latest_realtime_destinations_mrr",
    ],
}

# Salesforce field name mapping for use cases
USE_CASE_SF_FIELDS: dict[str, str] = {
    "uc_product_intelligence": "customer_use_case_product_intelligence__c",
    "uc_release_eng": "customer_use_case_release_eng__c",
    "uc_observability": "customer_use_case_observability__c",
    "uc_ai_llm_obs": "customer_use_case_ai_llm_obs__c",
    "uc_data_infra": "customer_use_case_data_infra__c",
}


# --------------------------------------------------------------------------- #
# Pydantic models
# --------------------------------------------------------------------------- #


class AccountClassification(BaseModel):
    sf_account_id: str
    archetype: str  # LLM may return unexpected values; apply_deterministic_archetype normalizes this
    ai_native_score: int = Field(ge=0, le=9)
    cloud_native_score: int = Field(ge=0, le=8)
    stage: Literal["Enterprise", "Scaled", "Early / Growth", "Unknown"]
    key_signals: str


class BatchClassificationResponse(BaseModel):
    classifications: list[AccountClassification]


# --------------------------------------------------------------------------- #
# TypedDicts for op payloads
# --------------------------------------------------------------------------- #


class AccountsBatchPayload(TypedDict):
    accounts: list[dict[str, Any]]
    use_case_lookup: dict[str, dict[str, Any]]
    batch_index: int
    total_batches: int


class AccountsBatchResult(TypedDict):
    classified: int
    sf_succeeded: int
    sf_failed: int
    llm_batches_failed: int


class PipelineSummary(TypedDict):
    total: int
    skipped: int
    to_classify: int


# Salesforce expects this specific format for DateTime fields
SF_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S.000+0000"

# Global semaphore for LLM gateway concurrency control. Shared across all accounts
# batches running in parallel so the total in-flight LLM requests stays bounded
# regardless of how many batches the executor runs concurrently.
_llm_semaphore: threading.Semaphore | None = None
_llm_semaphore_limit: int | None = None
_llm_semaphore_lock = threading.Lock()


def _get_llm_semaphore(max_concurrent: int) -> threading.Semaphore:
    global _llm_semaphore, _llm_semaphore_limit
    if _llm_semaphore is None:
        with _llm_semaphore_lock:
            if _llm_semaphore is None:
                _llm_semaphore = threading.Semaphore(max_concurrent)
                _llm_semaphore_limit = max_concurrent
    elif _llm_semaphore_limit != max_concurrent:
        dagster.get_dagster_logger().warning(
            f"LLM semaphore already initialized with limit {_llm_semaphore_limit}; "
            f"requested {max_concurrent}. Restart the process to apply the new value."
        )
    return _llm_semaphore


# --------------------------------------------------------------------------- #
# Use case adoption computation
# --------------------------------------------------------------------------- #


def compute_use_case_adoption(df: pl.DataFrame) -> pl.DataFrame:
    """Compute use case adoption levels from MRR columns.

    Adds columns: uc_product_intelligence, uc_release_eng, uc_observability,
    uc_ai_llm_obs, uc_data_infra, use_case_count.
    """
    result = df.clone()

    for use_case, mrr_cols in USE_CASE_MRR_MAPPING.items():
        total_mrr = pl.sum_horizontal(*[pl.col(c).fill_null(0) for c in mrr_cols])
        adoption = (
            pl.when(total_mrr >= MRR_THRESHOLD_SIGNIFICANT)
            .then(pl.lit("Significant"))
            .when(total_mrr >= MRR_THRESHOLD_ADOPTED)
            .then(pl.lit("Adopted"))
            .when(total_mrr > 0)
            .then(pl.lit("Experimental"))
            .otherwise(pl.lit("None"))
            .alias(use_case)
        )
        result = result.with_columns(adoption)

    # Count use cases at Adopted or above
    use_case_cols = list(USE_CASE_MRR_MAPPING.keys())
    result = result.with_columns(
        pl.sum_horizontal(*[pl.col(uc).is_in(["Adopted", "Significant"]).cast(pl.Int32) for uc in use_case_cols]).alias(
            "use_case_count"
        )
    )

    return result


# --------------------------------------------------------------------------- #
# LLM batching and parsing
# --------------------------------------------------------------------------- #


def prepare_llm_batches(df: pl.DataFrame, batch_size: int = 20) -> list[list[dict[str, Any]]]:
    """Split DataFrame into batches of account dicts for LLM classification.

    Only includes LLM_CONTEXT_COLUMNS and omits null values to reduce token usage.
    """
    batches: list[list[dict[str, Any]]] = []
    current_batch: list[dict[str, Any]] = []

    for row in df.to_dicts():
        account = {k: v for k, v in row.items() if k in LLM_CONTEXT_COLUMNS and v is not None}
        current_batch.append(account)
        if len(current_batch) >= batch_size:
            batches.append(current_batch)
            current_batch = []

    if current_batch:
        batches.append(current_batch)

    return batches


def parse_llm_response(raw: str) -> list[AccountClassification]:
    """Parse LLM JSON response into AccountClassification objects."""
    try:
        data = json.loads(raw)
        response = BatchClassificationResponse.model_validate(data)
        return response.classifications
    except Exception:
        dagster.get_dagster_logger().exception("Failed to parse LLM response: %s", raw[:500])
        return []


def apply_deterministic_archetype(
    classifications: list[AccountClassification],
) -> list[AccountClassification]:
    """Derive archetype deterministically from scores, ignoring the LLM's label."""
    result = []
    for c in classifications:
        if c.ai_native_score >= 2 and c.ai_native_score > c.cloud_native_score:
            archetype = "AI Native"
        elif c.cloud_native_score >= 2 and c.cloud_native_score > c.ai_native_score:
            archetype = "Cloud Native"
        elif c.ai_native_score >= 2 and c.ai_native_score == c.cloud_native_score:
            archetype = "AI Native"  # tie-break toward AI Native per prompt rules
        else:
            archetype = "Unknown"
        if archetype != c.archetype:
            c = c.model_copy(update={"archetype": archetype})
        result.append(c)
    return result


# --------------------------------------------------------------------------- #
# Salesforce record construction
# --------------------------------------------------------------------------- #


def build_salesforce_records(
    classifications: list[AccountClassification],
    use_case_df: pl.DataFrame,
) -> list[dict[str, Any]]:
    """Build Salesforce update records by merging LLM classifications with use case adoption."""
    # Index use case data by sf_account_id for fast lookup
    uc_lookup: dict[str, dict[str, Any]] = {}
    if "sf_account_id" in use_case_df.columns:
        for row in use_case_df.to_dicts():
            uc_lookup[row["sf_account_id"]] = row

    records = []
    for c in classifications:
        uc_data = uc_lookup.get(c.sf_account_id)

        record: dict[str, Any] = {
            "Id": c.sf_account_id,
            "customer_archetype__c": c.archetype,
            "customer_ai_native_score__c": c.ai_native_score,
            "customer_cloud_native_score__c": c.cloud_native_score,
            "customer_stage__c": c.stage,
            "customer_archetype_key_signals__c": c.key_signals,
        }

        if uc_data:
            for use_case_col, sf_field in USE_CASE_SF_FIELDS.items():
                record[sf_field] = uc_data.get(use_case_col)
            record["customer_use_case_count__c"] = uc_data.get("use_case_count")
        else:
            for sf_field in USE_CASE_SF_FIELDS.values():
                record[sf_field] = None
            record["customer_use_case_count__c"] = None

        records.append(record)

    return records


# --------------------------------------------------------------------------- #
# LLM classification with retry
# --------------------------------------------------------------------------- #


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30) + wait_random(0, 2))
def _classify_batch(client: Any, batch: list[dict[str, Any]]) -> list[AccountClassification]:
    """Call the LLM for a single batch, with automatic retry on transient errors."""
    user_prompt = json.dumps(batch)
    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=1,  # gpt-5 models only support temperature=1
        response_format={"type": "json_object"},
        timeout=180,
    )
    raw = response.choices[0].message.content or ""
    results = parse_llm_response(raw)
    if not results:
        raise ValueError(f"LLM returned empty/unparseable response for batch of {len(batch)} accounts")

    expected_ids = {a["sf_account_id"] for a in batch}
    returned_ids = [r.sf_account_id for r in results]
    returned_id_set = set(returned_ids)
    if len(returned_ids) != len(returned_id_set):
        raise ValueError(f"LLM returned duplicate sf_account_ids in batch of {len(batch)} accounts")
    if returned_id_set != expected_ids:
        missing = expected_ids - returned_id_set
        extra = returned_id_set - expected_ids
        raise ValueError(f"LLM ID mismatch: missing={missing}, extra={extra}")

    return results


# --------------------------------------------------------------------------- #
# Salesforce timestamp-based incremental helpers
# --------------------------------------------------------------------------- #


def _query_recently_classified_ids(sf: Any, cutoff: datetime) -> set[str]:
    """Query Salesforce for account IDs classified after the given cutoff."""
    cutoff_str = cutoff.strftime(SF_DATETIME_FORMAT)
    soql = f"SELECT Id FROM Account WHERE customer_archetype_classified_at__c >= {cutoff_str}"
    result = sf.query_all(soql)
    return {r["Id"] for r in result["records"]}


# --------------------------------------------------------------------------- #
# Dagster asset: account data fetch
# --------------------------------------------------------------------------- #


@dagster.asset(
    name="archetype_account_data",
    group_name="billing",
    tags={"owner": JobOwners.TEAM_BILLING.value},
)
def archetype_account_data(
    context: dagster.AssetExecutionContext,
) -> pl.DataFrame:
    """Fetch account data from the PostHog_Customer_Archetype saved query.

    Set ARCHETYPE_CSV_PATH to a local CSV file to skip the HogQL query and load
    data directly. Useful for local development and testing with exported data.
    """
    csv_path = os.environ.get("ARCHETYPE_CSV_PATH")
    if csv_path:
        context.log.info(f"Loading account data from CSV: {csv_path}")
        df = pl.read_csv(csv_path, infer_schema_length=10000)

        # Align columns: add missing ones as null, drop extras
        for col in COLUMNS:
            if col not in df.columns:
                df = df.with_columns(pl.lit(None).alias(col))
        df = df.select(COLUMNS).cast(dict.fromkeys(COLUMNS, pl.Utf8))
        source = "csv"
    else:
        context.log.info("Querying PostHog_Customer_Archetype saved query")

        team = Team.objects.get(id=ARCHETYPE_TEAM_ID)
        query = f"SELECT {', '.join(COLUMNS)} FROM PostHog_Customer_Archetype"  # nosemgrep: hogql-fstring-audit -- COLUMNS are hardcoded constants
        response = execute_hogql_query(
            query=query,
            team=team,
            query_type="archetype_account_data",
            limit_context=LimitContext.SAVED_QUERY,
        )

        if not response.results:
            context.log.info("No data found in PostHog_Customer_Archetype")
            return pl.DataFrame(schema=dict.fromkeys(COLUMNS, pl.Utf8))

        # HogQL returns mixed types (nulls, strings, numbers) so cast everything to
        # strings to avoid schema inference failures on columns like tech_tag_c.
        rows = [[str(v) if v is not None else None for v in row] for row in response.results]
        df = pl.DataFrame(rows, schema=dict.fromkeys(COLUMNS, pl.Utf8), orient="row")
        source = "hogql"

    has_usage = df.filter(pl.col("has_llm_analytics").is_not_null() | pl.col("distinct_products_used").is_not_null())
    context.log.info(
        f"Fetched {len(df)} accounts ({len(has_usage)} with usage data, {len(df) - len(has_usage)} without)"
    )

    context.add_output_metadata(
        {
            "total_accounts": dagster.MetadataValue.int(len(df)),
            "accounts_with_usage": dagster.MetadataValue.int(len(has_usage)),
            "source": dagster.MetadataValue.text(source),
        }
    )

    return df


# --------------------------------------------------------------------------- #
# Graph asset ops
# --------------------------------------------------------------------------- #


@dagster.op(
    out={"accounts_batches": dagster.DynamicOut(), "summary": dagster.Out()},
)
def prepare_and_fan_out(
    context: dagster.OpExecutionContext,
    config: ArchetypeClassificationConfig,
    account_data: pl.DataFrame,
):
    """Prepare account data, filter recently classified accounts, and fan out accounts batches."""
    if account_data.is_empty():
        context.log.info("No accounts to classify")
        yield dagster.Output({"total": 0, "skipped": 0, "to_classify": 0}, output_name="summary")
        return

    # Verify Salesforce is reachable before spending LLM credits — classifications
    # are only persisted in SF, so there's no point classifying if we can't upload.
    sf = get_salesforce_client()
    cutoff = datetime.now(UTC) - timedelta(days=config.skip_classified_within_days)
    recently_classified_ids = _query_recently_classified_ids(sf, cutoff)
    context.log.info(
        f"Found {len(recently_classified_ids)} accounts classified "
        f"within the last {config.skip_classified_within_days} days"
    )

    # Filter out recently classified accounts
    all_ids = set(account_data["sf_account_id"].to_list())
    skipped_count = len(all_ids & recently_classified_ids)
    accounts_to_classify = account_data.filter(~pl.col("sf_account_id").is_in(recently_classified_ids))

    context.log.info(
        f"Classifying {len(accounts_to_classify)} accounts "
        f"(skipping {skipped_count} recently classified, {len(account_data)} total)"
    )

    if accounts_to_classify.is_empty():
        context.log.info("All accounts recently classified, nothing to do")
        yield dagster.Output(
            {"total": len(account_data), "skipped": skipped_count, "to_classify": 0}, output_name="summary"
        )
        return

    # Cast MRR columns and compute use case adoption
    mrr_cols = [col for cols in USE_CASE_MRR_MAPPING.values() for col in cols]
    accounts_typed = accounts_to_classify.with_columns([pl.col(c).cast(pl.Float64, strict=False) for c in mrr_cols])
    use_case_df = compute_use_case_adoption(accounts_typed)

    # Build use_case_lookup for all accounts to classify
    use_case_lookup: dict[str, dict[str, Any]] = {}
    for row in use_case_df.to_dicts():
        use_case_lookup[row["sf_account_id"]] = row

    # Split into accounts batches and yield DynamicOutput for each
    all_rows = accounts_to_classify.to_dicts()
    total_batches = (len(all_rows) + config.accounts_batch_size - 1) // config.accounts_batch_size

    for i in range(0, len(all_rows), config.accounts_batch_size):
        chunk = all_rows[i : i + config.accounts_batch_size]
        chunk_ids = {row["sf_account_id"] for row in chunk}
        chunk_use_case = {sf_id: use_case_lookup[sf_id] for sf_id in chunk_ids if sf_id in use_case_lookup}

        batch_index = i // config.accounts_batch_size
        payload: AccountsBatchPayload = {
            "accounts": chunk,
            "use_case_lookup": chunk_use_case,
            "batch_index": batch_index,
            "total_batches": total_batches,
        }
        yield dagster.DynamicOutput(
            value=payload,
            mapping_key=str(batch_index),
            output_name="accounts_batches",
        )

    summary: PipelineSummary = {
        "total": len(account_data),
        "skipped": skipped_count,
        "to_classify": len(accounts_to_classify),
    }
    yield dagster.Output(summary, output_name="summary")


@dagster.op
def classify_and_push_accounts_batch(
    context: dagster.OpExecutionContext,
    config: ArchetypeClassificationConfig,
    accounts_batch: dict,
) -> dict:
    """Classify a batch of accounts via LLM and push results to Salesforce."""
    accounts = accounts_batch["accounts"]
    use_case_lookup = accounts_batch["use_case_lookup"]
    batch_index = accounts_batch["batch_index"]
    total_batches = accounts_batch["total_batches"]

    context.log.info(f"Accounts batch {batch_index + 1}/{total_batches}: classifying {len(accounts)} accounts")

    # Prepare LLM batches from the accounts batch
    classify_df = pl.DataFrame(accounts, infer_schema_length=None)
    llm_batches = prepare_llm_batches(classify_df, batch_size=config.llm_batch_size)

    # Classify LLM batches with global concurrency control. The semaphore is shared
    # across all accounts batches running in parallel so the total in-flight LLM
    # requests stays bounded regardless of executor parallelism.
    client = get_llm_client("customer_archetype_classification")
    semaphore = _get_llm_semaphore(config.llm_max_concurrent_requests)
    new_classifications: list[AccountClassification] = []
    failed_batches: list[dict[str, Any]] = []
    completed = 0
    total_llm_batches = len(llm_batches)

    def _throttled_classify(batch: list[dict[str, Any]]) -> list[AccountClassification]:
        with semaphore:
            return _classify_batch(client, batch)

    with ThreadPoolExecutor(max_workers=min(config.llm_max_workers, config.llm_max_concurrent_requests)) as pool:
        futures = {pool.submit(_throttled_classify, batch): i for i, batch in enumerate(llm_batches)}
        for future in as_completed(futures):
            i = futures[future]
            completed += 1
            try:
                new_classifications.extend(future.result())
            except Exception:
                batch_ids = [a.get("sf_account_id", "?") for a in llm_batches[i]]
                context.log.exception(
                    f"LLM batch {i + 1} failed after retries, skipping {len(llm_batches[i])} accounts: {batch_ids}"
                )
                failed_batches.append({"batch": i + 1, "account_ids": batch_ids})
            if completed % 50 == 0 or completed == total_llm_batches:
                context.log.info(
                    f"Accounts batch {batch_index + 1}: {completed}/{total_llm_batches} LLM batches "
                    f"({completed * 100 // total_llm_batches}%, {len(failed_batches)} failed)"
                )

    new_classifications = apply_deterministic_archetype(new_classifications)

    # Build Salesforce records with use case adoption data
    use_case_rows = [
        use_case_lookup[c.sf_account_id] for c in new_classifications if c.sf_account_id in use_case_lookup
    ]
    use_case_df = pl.DataFrame(use_case_rows, infer_schema_length=None) if use_case_rows else pl.DataFrame()
    records = build_salesforce_records(new_classifications, use_case_df)

    # Stamp each record with the classification timestamp
    classified_at = datetime.now(UTC).strftime(SF_DATETIME_FORMAT)
    for record in records:
        record["customer_archetype_classified_at__c"] = classified_at

    # Push to Salesforce (fresh client per batch to avoid session timeouts)
    sf = get_salesforce_client()
    succeeded, failed = bulk_update_salesforce_accounts(sf, records) if records else (0, 0)

    context.log.info(
        f"Accounts batch {batch_index + 1}/{total_batches}: "
        f"classified {len(new_classifications)}, SF succeeded {succeeded}, SF failed {failed}, "
        f"LLM batches failed {len(failed_batches)}"
    )

    return {
        "classified": len(new_classifications),
        "sf_succeeded": succeeded,
        "sf_failed": failed,
        "llm_batches_failed": len(failed_batches),
    }


@dagster.op
def collect_results(
    context: dagster.OpExecutionContext,
    batch_results: list[dict],
    summary: dict,
) -> None:
    """Aggregate results from all accounts batches and store lightweight metadata.

    SF failures are logged as warnings rather than raised as exceptions. Raising
    would mark the entire asset as failed, preventing Dagster from recording a
    materialization — which means the next run would re-process accounts that
    already succeeded. Since each accounts batch already pushed its successes to SF,
    the data is safely persisted regardless.
    """
    total_classified = sum(r["classified"] for r in batch_results)
    total_sf_succeeded = sum(r["sf_succeeded"] for r in batch_results)
    total_sf_failed = sum(r["sf_failed"] for r in batch_results)
    total_llm_failed = sum(r["llm_batches_failed"] for r in batch_results)

    context.log.info(
        f"Pipeline complete: {summary['total']} total accounts, {summary['skipped']} skipped, "
        f"{total_classified} classified, SF succeeded {total_sf_succeeded}, SF failed {total_sf_failed}"
    )

    context.add_output_metadata(
        {
            "total_accounts": dagster.MetadataValue.int(summary["total"]),
            "accounts_skipped": dagster.MetadataValue.int(summary["skipped"]),
            "accounts_to_classify": dagster.MetadataValue.int(summary["to_classify"]),
            "total_classified": dagster.MetadataValue.int(total_classified),
            "batches_completed": dagster.MetadataValue.int(len(batch_results)),
            "sf_succeeded": dagster.MetadataValue.int(total_sf_succeeded),
            "sf_failed": dagster.MetadataValue.int(total_sf_failed),
            "llm_batches_failed": dagster.MetadataValue.int(total_llm_failed),
        }
    )

    if total_sf_failed:
        context.log.warning(
            f"Salesforce update had {total_sf_failed} failures "
            f"out of {total_sf_succeeded + total_sf_failed} records across {len(batch_results)} accounts batches. "
            f"Failed accounts will be retried on the next run (their timestamps were not updated)."
        )


# --------------------------------------------------------------------------- #
# Graph asset: classify and sync to Salesforce
# --------------------------------------------------------------------------- #


@dagster.graph_asset(
    name="archetype_classify_and_sync",
    group_name="billing",
    tags={
        "owner": JobOwners.TEAM_BILLING.value,
        "dagster/max_runtime": str(12 * 60 * 60),
    },
)
def archetype_classify_and_sync(archetype_account_data: pl.DataFrame):
    accounts_batches, summary = prepare_and_fan_out(archetype_account_data)
    results = accounts_batches.map(classify_and_push_accounts_batch)
    return collect_results(results.collect(), summary)


# --------------------------------------------------------------------------- #
# Job and schedule
# --------------------------------------------------------------------------- #


archetype_job = dagster.define_asset_job(
    name="customer_archetype_job",
    selection=["archetype_account_data", "archetype_classify_and_sync"],
    tags={"owner": JobOwners.TEAM_BILLING.value},
)


@dagster.schedule(
    cron_schedule="0 5 * * 1",
    job=archetype_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_BILLING.value},
)
def archetype_weekly_schedule(context: dagster.ScheduleEvaluationContext):
    return dagster.RunRequest()
