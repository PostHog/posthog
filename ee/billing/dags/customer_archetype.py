"""Customer Archetype Classification — Dagster ETL Pipeline.

Classifies Salesforce accounts as "AI Native", "Cloud Native", or "Unknown"
using LLM-based classification, computes use case adoption from MRR data,
and pushes results back to Salesforce.
"""

import json
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Literal, cast

import polars as pl
import dagster
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential

from posthog.hogql.constants import LimitContext
from posthog.hogql.query import execute_hogql_query

from posthog.dags.common import JobOwners
from posthog.dags.common.utils import compute_dataframe_hashes
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
    llm_batch_size: int = 10


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


def _hash_sf_record(record: dict[str, Any]) -> str:
    """Deterministic hash of a Salesforce update record for change detection."""
    serialized = json.dumps(record, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# LLM classification with retry
# --------------------------------------------------------------------------- #


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30))
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
# Dagster assets
# --------------------------------------------------------------------------- #


@dagster.asset(
    name="archetype_account_data",
    group_name="billing",
    tags={"owner": JobOwners.TEAM_BILLING.value},
)
def archetype_account_data(
    context: dagster.AssetExecutionContext,
) -> pl.DataFrame:
    """Fetch account data from the PostHog_Customer_Archetype saved query."""
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
        return pl.DataFrame(schema=dict.fromkeys(COLUMNS, pl.Object))

    df = pl.DataFrame(response.results, schema=COLUMNS, orient="row")

    has_usage = df.filter(pl.col("has_llm_analytics").is_not_null() | pl.col("distinct_products_used").is_not_null())
    context.log.info(
        f"Fetched {len(df)} accounts ({len(has_usage)} with usage data, {len(df) - len(has_usage)} without)"
    )

    context.add_output_metadata(
        {
            "total_accounts": dagster.MetadataValue.int(len(df)),
            "accounts_with_usage": dagster.MetadataValue.int(len(has_usage)),
            "source": dagster.MetadataValue.text("hogql"),
        }
    )

    return df


@dagster.asset(
    name="archetype_llm_classification",
    group_name="billing",
    tags={"owner": JobOwners.TEAM_BILLING.value},
    deps=["archetype_account_data"],
)
def archetype_llm_classification(
    context: dagster.AssetExecutionContext,
    config: ArchetypeClassificationConfig,
    archetype_account_data: pl.DataFrame,
) -> pl.DataFrame:
    """Classify all accounts using LLM."""
    df = archetype_account_data
    if df.is_empty():
        context.log.info("No accounts to classify, preserving prior metadata")
        prior_hashes, prior_classifications = _get_prior_materialization_metadata(context)
        context.add_output_metadata(
            {
                "total_classified": dagster.MetadataValue.int(0),
                "newly_classified": dagster.MetadataValue.int(0),
                "carried_forward": dagster.MetadataValue.int(0),
                "account_hashes": dagster.MetadataValue.json(prior_hashes),
                "classifications": dagster.MetadataValue.json(prior_classifications),
            }
        )
        return pl.DataFrame()

    # Incremental: hash input data and compare with prior run
    hashed_df = compute_dataframe_hashes(df.select(LLM_CONTEXT_COLUMNS))
    hashed_df = df.join(hashed_df.select("sf_account_id", "data_hash"), on="sf_account_id")
    prior_hashes, prior_classifications = _get_prior_materialization_metadata(context)

    # Determine which accounts need re-classification
    accounts_to_classify = []
    carried_forward = []
    for row in hashed_df.to_dicts():
        sf_id = row["sf_account_id"]
        current_hash = row["data_hash"]
        if sf_id in prior_hashes and prior_hashes[sf_id] == current_hash and sf_id in prior_classifications:
            carried_forward.append(prior_classifications[sf_id])
        else:
            accounts_to_classify.append(row)

    context.log.info(
        f"Classifying {len(accounts_to_classify)} changed/new accounts, carrying forward {len(carried_forward)}"
    )

    # LLM classification for changed accounts
    new_classifications: list[AccountClassification] = []
    failed_batches: list[dict] = []
    if accounts_to_classify:
        classify_df = pl.DataFrame(accounts_to_classify, infer_schema_length=None)
        batches = prepare_llm_batches(classify_df, batch_size=config.llm_batch_size)
        client = get_llm_client("customer_archetype_classification")

        context.log.info(f"Classifying {len(batches)} batches concurrently (max_workers={config.llm_max_workers})")
        with ThreadPoolExecutor(max_workers=config.llm_max_workers) as pool:
            futures = {pool.submit(_classify_batch, client, batch): i for i, batch in enumerate(batches)}
            for future in as_completed(futures):
                i = futures[future]
                try:
                    new_classifications.extend(future.result())
                except Exception:
                    batch_ids = [a.get("sf_account_id", "?") for a in batches[i]]
                    context.log.exception(
                        f"LLM batch {i + 1} failed after retries, skipping {len(batches[i])} accounts: {batch_ids}"
                    )
                    failed_batches.append({"batch": i + 1, "account_ids": batch_ids})

    new_classifications = apply_deterministic_archetype(new_classifications)

    # Merge new + carried forward
    all_classifications = new_classifications + [AccountClassification.model_validate(c) for c in carried_forward]

    # Store hashes and classifications in metadata for next run
    current_hashes = {row["sf_account_id"]: row["data_hash"] for row in hashed_df.to_dicts()}
    current_classifications = {c.sf_account_id: c.model_dump() for c in all_classifications}

    context.add_output_metadata(
        {
            "total_classified": dagster.MetadataValue.int(len(all_classifications)),
            "newly_classified": dagster.MetadataValue.int(len(new_classifications)),
            "carried_forward": dagster.MetadataValue.int(len(carried_forward)),
            "failed_batches": dagster.MetadataValue.json(failed_batches),
            "account_hashes": dagster.MetadataValue.json(current_hashes),
            "classifications": dagster.MetadataValue.json(current_classifications),
        }
    )

    # Convert to DataFrame for downstream
    if not all_classifications:
        return pl.DataFrame()

    return pl.DataFrame([c.model_dump() for c in all_classifications])


@dagster.asset(
    name="archetype_to_salesforce",
    group_name="billing",
    tags={"owner": JobOwners.TEAM_BILLING.value},
    deps=["archetype_llm_classification", "archetype_account_data"],
)
def archetype_to_salesforce(
    context: dagster.AssetExecutionContext,
    archetype_llm_classification: pl.DataFrame,
    archetype_account_data: pl.DataFrame,
) -> None:
    """Push archetype classifications and use case adoption to Salesforce."""
    if archetype_llm_classification.is_empty():
        context.log.info("No classifications to push")
        return

    # Compute use case adoption from MRR data
    use_case_df = compute_use_case_adoption(archetype_account_data)

    # Reconstruct classifications from DataFrame
    classifications = [AccountClassification.model_validate(row) for row in archetype_llm_classification.to_dicts()]

    # Build Salesforce update records and filter to only changed ones
    all_records = build_salesforce_records(classifications, use_case_df)
    prior_sf_hashes = _get_prior_sf_record_hashes(context)

    current_sf_hashes: dict[str, str] = {}
    changed_records: list[dict[str, Any]] = []
    for record in all_records:
        sf_id = record["Id"]
        record_hash = _hash_sf_record(record)
        current_sf_hashes[sf_id] = record_hash
        if prior_sf_hashes.get(sf_id) != record_hash:
            changed_records.append(record)

    context.log.info(f"{len(changed_records)} of {len(all_records)} records changed, pushing to Salesforce")

    succeeded, failed = 0, 0
    if changed_records:
        sf = get_salesforce_client()
        succeeded, failed = bulk_update_salesforce_accounts(sf, changed_records)

    context.add_output_metadata(
        {
            "records_considered": dagster.MetadataValue.int(len(all_records)),
            "records_changed": dagster.MetadataValue.int(len(changed_records)),
            "records_succeeded": dagster.MetadataValue.int(succeeded),
            "records_failed": dagster.MetadataValue.int(failed),
            "sf_record_hashes": dagster.MetadataValue.json(current_sf_hashes),
        }
    )

    if failed:
        raise RuntimeError(f"Salesforce update had {failed} failures out of {len(changed_records)} records")


# --------------------------------------------------------------------------- #
# Incremental processing helpers
# --------------------------------------------------------------------------- #


def _get_prior_materialization_metadata(
    context: dagster.AssetExecutionContext,
) -> tuple[dict[str, str], dict[str, dict]]:
    """Retrieve account hashes and classifications from the last materialization."""
    asset_key = dagster.AssetKey(["archetype_llm_classification"])
    last_event = context.instance.get_latest_materialization_event(asset_key)
    if not last_event or not last_event.asset_materialization:
        return {}, {}
    metadata = last_event.asset_materialization.metadata

    hashes: dict[str, str] = {}
    hashes_meta = metadata.get("account_hashes")
    if hashes_meta and isinstance(hashes_meta, dagster.JsonMetadataValue):
        hashes = cast(dict[str, str], hashes_meta.value or {})

    classifications: dict[str, dict] = {}
    classifications_meta = metadata.get("classifications")
    if classifications_meta and isinstance(classifications_meta, dagster.JsonMetadataValue):
        classifications = cast(dict[str, dict], classifications_meta.value or {})

    return hashes, classifications


def _get_prior_sf_record_hashes(context: dagster.AssetExecutionContext) -> dict[str, str]:
    """Retrieve Salesforce record hashes from the last archetype_to_salesforce materialization."""
    asset_key = dagster.AssetKey(["archetype_to_salesforce"])
    last_event = context.instance.get_latest_materialization_event(asset_key)
    if not last_event or not last_event.asset_materialization:
        return {}
    metadata = last_event.asset_materialization.metadata
    hashes_meta = metadata.get("sf_record_hashes")
    if hashes_meta and isinstance(hashes_meta, dagster.JsonMetadataValue):
        return cast(dict[str, str], hashes_meta.value or {})
    return {}


# --------------------------------------------------------------------------- #
# Job and schedule
# --------------------------------------------------------------------------- #


archetype_job = dagster.define_asset_job(
    name="customer_archetype_job",
    selection=["archetype_account_data", "archetype_llm_classification", "archetype_to_salesforce"],
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
