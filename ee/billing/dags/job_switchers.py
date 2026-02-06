from typing import Any

import polars as pl
import dagster
from dagster import AssetKey, JsonMetadataValue, MetadataValue

from posthog.hogql.constants import LimitContext
from posthog.hogql.query import execute_hogql_query

from posthog.dags.common import JobOwners
from posthog.dags.common.resources import ClayWebhookResource
from posthog.dags.common.utils import compute_dataframe_hashes
from posthog.models import Team

# PostHog Cloud US team where JobSwitchers_v3 saved query exists
JOB_SWITCHERS_TEAM_ID = 2

# Array fields to progressively truncate when a record exceeds Clay's batch
# size limit, ordered by priority (least important truncated first).
TRUNCATABLE_FIELDS = [
    "bounce_reasons",
    "subjects",
    "removal_timestamps",
    "removal_types",
    "source_type",
    "organization_names",
    "organization_ids",
    "emails",
]

# Column definitions matching JobSwitchers_v3 schema
COLUMNS = [
    "email_domain",
    "emails",
    "bounce_count",
    "first_bounce_at",
    "last_bounce_at",
    "subjects",
    "bounce_reasons",
    "organization_ids",
    "organization_names",
    "removal_timestamps",
    "removal_types",
    "source_type",
]


def clickhouse_to_dataframe(results: list[tuple]) -> pl.DataFrame:
    """Convert ClickHouse query results to Polars DataFrame."""
    if not results:
        return pl.DataFrame(schema=dict.fromkeys(COLUMNS, pl.Object))

    return pl.DataFrame(results, schema=COLUMNS, orient="row")


def filter_changed_domains(df: pl.DataFrame, prior_hashes: dict[str, str]) -> pl.DataFrame:
    """Filter to only domains that are new or changed."""
    if not prior_hashes:
        return df

    def is_changed(domain: str, current_hash: str) -> bool:
        return domain not in prior_hashes or prior_hashes[domain] != current_hash

    mask = [is_changed(d, h) for d, h in zip(df["email_domain"].to_list(), df["data_hash"].to_list())]
    return df.filter(pl.Series(mask))


def dataframe_to_clay_payload(df: pl.DataFrame) -> list[dict[str, Any]]:
    """Convert DataFrame to Clay webhook payload format."""
    payload = []
    for row in df.to_dicts():
        payload.append(
            {
                "domain": row["email_domain"],
                "emails": row.get("emails", []) or [],
                "bounce_count": row.get("bounce_count", 0),
                "first_bounce_at": (row["first_bounce_at"].isoformat() if row["first_bounce_at"] else None),
                "last_bounce_at": (row["last_bounce_at"].isoformat() if row["last_bounce_at"] else None),
                "subjects": row.get("subjects", []) or [],
                "bounce_reasons": row.get("bounce_reasons", []) or [],
                "organization_ids": row.get("organization_ids", []) or [],
                "organization_names": row.get("organization_names", []) or [],
                "removal_timestamps": row.get("removal_timestamps", []) or [],
                "removal_types": row.get("removal_types", []) or [],
                "source_type": row.get("source_type", []) or [],
            }
        )
    return payload


def get_prior_hashes_from_metadata(
    context: dagster.AssetExecutionContext,
) -> dict[str, str]:
    """Retrieve domain hashes from the last asset materialization metadata."""
    asset_key = AssetKey(["job_switchers_to_clay"])
    last_event = context.instance.get_latest_materialization_event(asset_key)

    if not last_event or not last_event.asset_materialization:
        return {}

    metadata = last_event.asset_materialization.metadata
    domain_hashes_meta = metadata.get("domain_hashes")

    if domain_hashes_meta and isinstance(domain_hashes_meta, JsonMetadataValue):
        return domain_hashes_meta.value or {}

    return {}


@dagster.asset(
    name="job_switchers_to_clay",
    group_name="billing",
    tags={"owner": JobOwners.TEAM_BILLING.value},
)
def job_switchers_to_clay(
    context: dagster.AssetExecutionContext,
    clay_webhook_job_switchers: dagster.ResourceParam[ClayWebhookResource],
) -> None:
    """
    Incrementally sync job switchers to Clay webhook.

    Uses Dagster asset metadata to track domain hashes between runs,
    only syncing new or changed domains to preserve Clay's 50k lifetime
    submission limit. Batches are sent sequentially to respect Clay's
    rate limits.
    """
    context.log.info("Querying JobSwitchers_v3 saved query")

    team = Team.objects.get(id=JOB_SWITCHERS_TEAM_ID)
    query = f"""
        SELECT {", ".join(COLUMNS)}
        FROM JobSwitchers_v3
    """
    response = execute_hogql_query(
        query=query,
        team=team,
        query_type="job_switchers_query",
        limit_context=LimitContext.SAVED_QUERY,
    )
    results = response.results

    if not results:
        context.log.info("No data found in JobSwitchers_v3")
        prior_hashes = get_prior_hashes_from_metadata(context)
        context.add_output_metadata(
            {
                "domain_hashes": MetadataValue.json(prior_hashes),
                "domains_synced": MetadataValue.int(0),
                "total_domains": MetadataValue.int(0),
            }
        )
        return

    # Convert to Polars DataFrame
    df = clickhouse_to_dataframe(results)
    context.log.info("Found %d total domains", len(df))

    # Compute hashes for change detection
    df = compute_dataframe_hashes(df)

    # Get previously synced hashes from last materialization metadata
    prior_hashes = get_prior_hashes_from_metadata(context)
    if not prior_hashes:
        context.log.info("No previous sync state found, will sync all domains")
    else:
        context.log.info("Found %d previously synced domains", len(prior_hashes))

    # Filter to only changed domains
    changed_df = filter_changed_domains(df, prior_hashes)

    # Build current hashes dict for metadata storage
    current_hashes = {
        row["email_domain"]: row["data_hash"] for row in df.select(["email_domain", "data_hash"]).to_dicts()
    }

    if len(changed_df) == 0:
        context.log.info("No new or changed domains to sync")
        context.add_output_metadata(
            {
                "domain_hashes": MetadataValue.json(current_hashes),
                "domains_synced": MetadataValue.int(0),
                "total_domains": MetadataValue.int(len(df)),
            }
        )
        return

    context.log.info("Sending %d new/changed domains to Clay webhook", len(changed_df))

    # Convert to payload and create batches
    payload = dataframe_to_clay_payload(changed_df)
    batch_result = clay_webhook_job_switchers.create_batches(
        payload, logger=context.log, truncatable_fields=TRUNCATABLE_FIELDS
    )

    # Send batches sequentially
    for i, batch in enumerate(batch_result.batches):
        clay_webhook_job_switchers.send(batch)
        context.log.info("Sent batch %d/%d with %d records", i + 1, len(batch_result.batches), len(batch))

    context.log.info("Sent %d batches to Clay webhook", len(batch_result.batches))

    # Store domain hashes in asset metadata for next run
    context.add_output_metadata(
        {
            "domain_hashes": MetadataValue.json(current_hashes),
            "domains_synced": MetadataValue.int(len(changed_df)),
            "total_domains": MetadataValue.int(len(df)),
            "batches_sent": MetadataValue.int(len(batch_result.batches)),
            "records_truncated": MetadataValue.int(batch_result.truncated_count),
            "records_skipped": MetadataValue.int(batch_result.skipped_count),
        }
    )

    context.log.info("Synced %d domains, stored %d hashes in metadata", len(changed_df), len(current_hashes))


job_switchers_job = dagster.define_asset_job(
    name="job_switchers_to_clay_job",
    selection=["job_switchers_to_clay"],
    tags={"owner": JobOwners.TEAM_BILLING.value},
)


# Daily schedule at 6 AM UTC
@dagster.schedule(
    cron_schedule="0 6 * * *",
    job=job_switchers_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_BILLING.value},
)
def job_switchers_daily_schedule(context: dagster.ScheduleEvaluationContext):
    """Run job switchers to Clay webhook daily at 6 AM UTC."""
    context.log.info("Triggering daily job switchers sync to Clay")
    return dagster.RunRequest()
