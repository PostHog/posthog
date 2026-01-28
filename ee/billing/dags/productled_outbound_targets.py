from datetime import timedelta
from typing import Any

from django.db.models import Count
from django.utils import timezone

import polars as pl
import dagster
from dagster import AssetKey, JsonMetadataValue, MetadataValue

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.dags.common import JobOwners
from posthog.dags.common.resources import ClayWebhookResource
from posthog.models import Team
from posthog.models.organization import OrganizationMembership

# The PostHog internal team used for executing HogQL queries against the ProductLed_Outbound saved query.
PLO_TEAM_ID = 2

# Array fields to progressively truncate when a record exceeds Clay's batch
# size limit, ordered by priority (least important truncated first).
TRUNCATABLE_FIELDS = ["users"]


BASE_COLUMNS = [
    "business_model",
    "company_tags",
    "company_type",
    "domain",
    "headcount",
    "headcount_engineering",
    "icp_score",
    "industry",
    "last_3m_avg_mrr",
    "organization_created_at",
    "organization_id",
    "organization_name",
    "peak_arr",
    "peak_mrr",
    "trailing_12m_revenue",
    "vitally_churned_at",
    "vitally_owner",
]

SIGNAL_COLUMNS = ["multi_product_count", "event_growth_pct", "new_user_count", "new_products"]

PAYLOAD_COLUMNS = BASE_COLUMNS + SIGNAL_COLUMNS

PRODUCT_FLAGS = [
    "session_recording_opt_in",
    "surveys_opt_in",
    "heatmaps_opt_in",
    "autocapture_exceptions_opt_in",
]

TEAM_PRODUCT_SCHEMA = {
    "team_id": pl.Int64,
    "organization_id": pl.Utf8,
    "session_recording_opt_in": pl.Boolean,
    "surveys_opt_in": pl.Boolean,
    "heatmaps_opt_in": pl.Boolean,
    "autocapture_exceptions_opt_in": pl.Boolean,
}

PRODUCT_EVENT_MAP = {
    "session_recording_opt_in": ("$snapshot", "session_recording"),
    "surveys_opt_in": ("survey sent", "surveys"),
    "heatmaps_opt_in": ("$heatmap", "heatmaps"),
    "autocapture_exceptions_opt_in": ("$exception", "autocapture_exceptions"),
}


def build_team_product_df(org_ids: list[str]) -> pl.DataFrame:
    """Fetch team-level product flags from ClickHouse ETL table for the given orgs."""
    if not org_ids:
        return pl.DataFrame(schema=TEAM_PRODUCT_SCHEMA)

    query = """
        SELECT
            id,
            organization_id,
            session_recording_opt_in,
            surveys_opt_in,
            heatmaps_opt_in,
            autocapture_exceptions_opt_in
        FROM posthog_team
        WHERE organization_id IN %(org_ids)s
    """
    results = sync_execute(query, {"org_ids": org_ids})

    if not results:
        return pl.DataFrame(schema=TEAM_PRODUCT_SCHEMA)

    return pl.DataFrame(
        results,
        schema=[
            "team_id",
            "organization_id",
            "session_recording_opt_in",
            "surveys_opt_in",
            "heatmaps_opt_in",
            "autocapture_exceptions_opt_in",
        ],
        orient="row",
    )


def compute_multi_product_usage(team_df: pl.DataFrame) -> dict[str, int]:
    """Count distinct products enabled per org (at least one team has the flag on)."""
    if len(team_df) == 0:
        return {}

    return dict(
        team_df.group_by("organization_id")
        .agg([pl.col(f).any().cast(pl.Int64) for f in PRODUCT_FLAGS])
        .with_columns(pl.sum_horizontal(PRODUCT_FLAGS).alias("count"))
        .select("organization_id", "count")
        .iter_rows()
    )


def compute_event_growth(team_df: pl.DataFrame) -> dict[str, float | None]:
    """Compute month-over-month event growth percentage per org."""
    if len(team_df) == 0:
        return {}

    team_ids = team_df["team_id"].to_list()
    team = Team.objects.get(id=PLO_TEAM_ID)

    query = """
        SELECT
            properties.$team_id as team_id,
            countIf(timestamp >= now() - interval 30 day) as current_count,
            countIf(timestamp >= now() - interval 60 day AND timestamp < now() - interval 30 day) as prior_count
        FROM events
        WHERE properties.$team_id IN {team_ids}
          AND timestamp >= now() - interval 60 day
        GROUP BY team_id
    """

    response = execute_hogql_query(
        query=query,
        team=team,
        query_type="plo_event_growth",
        limit_context=LimitContext.SAVED_QUERY,
        placeholders={"team_ids": ast.Tuple(exprs=[ast.Constant(value=t) for t in team_ids])},
    )

    # Build team_id → org_id mapping
    team_to_org = dict(zip(team_df["team_id"].to_list(), team_df["organization_id"].to_list()))

    # Aggregate per org
    org_current: dict[str, int] = {}
    org_prior: dict[str, int] = {}
    for row in response.results or []:
        tid, current, prior = row[:3]
        org_id = team_to_org.get(tid)
        if org_id:
            org_current[org_id] = org_current.get(org_id, 0) + current
            org_prior[org_id] = org_prior.get(org_id, 0) + prior

    result: dict[str, float | None] = {}
    for org_id in org_current.keys() | org_prior.keys():
        current = org_current.get(org_id, 0)
        prior = org_prior.get(org_id, 0)
        if prior == 0:
            result[org_id] = None
        else:
            result[org_id] = (current - prior) / prior * 100
    return result


def compute_new_users_30d(org_ids: list[str]) -> dict[str, int]:
    """Count new OrganizationMembership records in the last 30 days per org."""
    if not org_ids:
        return {}

    cutoff = timezone.now() - timedelta(days=30)
    rows = (
        OrganizationMembership.objects.filter(
            organization_id__in=org_ids,
            joined_at__gte=cutoff,
        )
        .values("organization_id")
        .annotate(new_user_count=Count("id"))
    )

    return {str(row["organization_id"]): row["new_user_count"] for row in rows}


def compute_new_product_this_month(team_df: pl.DataFrame) -> dict[str, str]:
    """Detect products newly adopted this month (events this month but not last month, with flag on)."""
    if len(team_df) == 0:
        return {}

    team_ids = team_df["team_id"].to_list()
    team = Team.objects.get(id=PLO_TEAM_ID)

    all_events = [ev for ev, _ in PRODUCT_EVENT_MAP.values()]

    query = """
        SELECT
            properties.$team_id as team_id,
            event,
            countIf(timestamp >= toStartOfMonth(now())) as this_month,
            countIf(timestamp >= toStartOfMonth(now()) - interval 1 month AND timestamp < toStartOfMonth(now())) as prior_month
        FROM events
        WHERE properties.$team_id IN {team_ids}
          AND event IN {events}
          AND timestamp >= toStartOfMonth(now()) - interval 1 month
        GROUP BY team_id, event
    """

    response = execute_hogql_query(
        query=query,
        team=team,
        query_type="plo_new_product",
        limit_context=LimitContext.SAVED_QUERY,
        placeholders={
            "team_ids": ast.Tuple(exprs=[ast.Constant(value=t) for t in team_ids]),
            "events": ast.Tuple(exprs=[ast.Constant(value=e) for e in all_events]),
        },
    )

    # Build team_id → (org_id, flags) mapping
    team_to_org: dict[Any, str] = {}
    team_flags: dict[Any, dict[str, bool]] = {}
    for row in team_df.to_dicts():
        tid = row["team_id"]
        team_to_org[tid] = row["organization_id"]
        team_flags[tid] = {f: row[f] for f in PRODUCT_FLAGS}

    # Event → flag mapping (reverse of PRODUCT_EVENT_MAP)
    event_to_flag = {ev: flag for flag, (ev, _) in PRODUCT_EVENT_MAP.items()}

    # Collect new products per org
    org_new_products: dict[str, set[str]] = {}
    for row in response.results or []:
        tid, event, this_month, prior_month = row[:4]
        if this_month > 0 and prior_month == 0:
            flag = event_to_flag.get(event)
            if flag and team_flags.get(tid, {}).get(flag, False):
                org_id = team_to_org.get(tid)
                if org_id:
                    _, product_name = PRODUCT_EVENT_MAP[flag]
                    org_new_products.setdefault(org_id, set()).add(product_name)

    return {org_id: ",".join(sorted(products)) for org_id, products in org_new_products.items()}


def fetch_org_users(org_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Fetch active members for each organization, keyed by org ID."""
    if not org_ids:
        return {}

    memberships = (
        OrganizationMembership.objects.filter(
            organization_id__in=org_ids,
            user__is_active=True,
        )
        .select_related("user")
        .values_list("organization_id", "user__first_name", "user__last_name", "user__email", "joined_at")
    )
    result: dict[str, list[dict[str, Any]]] = {}
    for org_id, first_name, last_name, email, joined_at in memberships:
        result.setdefault(str(org_id), []).append(
            {
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "joined_at": joined_at.isoformat() if joined_at else None,
            }
        )
    return result


def filter_qualified(df: pl.DataFrame) -> pl.DataFrame:
    """Filter to rows that meet at least one qualifying signal threshold."""
    has_multi_product = pl.col("multi_product_count") >= 2
    has_event_growth = pl.col("event_growth_pct") > 30
    has_new_users = pl.col("new_user_count") >= 2
    has_new_product = pl.col("new_products").is_not_null() & (pl.col("new_products") != "")

    return df.filter(has_multi_product | has_event_growth | has_new_users | has_new_product)


def dataframe_to_plo_clay_payload(df: pl.DataFrame, org_users: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Convert enriched PLO DataFrame to Clay webhook payload with user data attached."""
    return [
        {**record, "users": org_users.get(record["organization_id"], [])}
        for record in df.select(PAYLOAD_COLUMNS).to_dicts()
    ]


def get_plo_prior_hashes(context: dagster.AssetExecutionContext) -> dict[str, str]:
    """Retrieve org hashes from the last plo_qualified_to_clay materialization."""
    asset_key = AssetKey(["plo_qualified_to_clay"])
    last_event = context.instance.get_latest_materialization_event(asset_key)

    if not last_event or not last_event.asset_materialization:
        return {}

    metadata = last_event.asset_materialization.metadata
    org_hashes_meta = metadata.get("org_hashes")

    if org_hashes_meta and isinstance(org_hashes_meta, JsonMetadataValue):
        return org_hashes_meta.value or {}

    return {}


@dagster.asset(
    name="plo_base_targets",
    group_name="billing",
    tags={"owner": JobOwners.TEAM_BILLING.value},
)
def plo_base_targets(
    context: dagster.AssetExecutionContext,
) -> pl.DataFrame:
    """Fetch base targets from the ProductLed_Outbound saved query."""
    context.log.info("Querying ProductLed_Outbound saved query")

    team = Team.objects.get(id=PLO_TEAM_ID)
    query = f"""
        SELECT {", ".join(BASE_COLUMNS)}
        FROM ProductLed_Outbound
        """  # nosemgrep: hogql-fstring-audit -- BASE_COLUMNS are hardcoded constants, not user input
    response = execute_hogql_query(
        query=query,
        team=team,
        query_type="plo_base_targets",
        limit_context=LimitContext.SAVED_QUERY,
    )

    if not response.results:
        context.log.info("No data found in ProductLed_Outbound")
        return pl.DataFrame(
            schema={
                "business_model": pl.Utf8,
                "company_tags": pl.Utf8,
                "company_type": pl.Utf8,
                "domain": pl.Utf8,
                "headcount": pl.Int64,
                "headcount_engineering": pl.Int64,
                "icp_score": pl.Int64,
                "industry": pl.Utf8,
                "last_3m_avg_mrr": pl.Float64,
                "organization_created_at": pl.Utf8,
                "organization_id": pl.Utf8,
                "organization_name": pl.Utf8,
                "peak_arr": pl.Float64,
                "peak_mrr": pl.Float64,
                "trailing_12m_revenue": pl.Float64,
                "vitally_churned_at": pl.Utf8,
                "vitally_owner": pl.Utf8,
            }
        )

    df = pl.DataFrame(response.results, schema=BASE_COLUMNS, orient="row")
    context.log.info("Found %d base targets", len(df))
    return df


@dagster.asset(
    name="qualify_signals",
    group_name="billing",
    tags={"owner": JobOwners.TEAM_BILLING.value},
    deps=["plo_base_targets"],
)
def qualify_signals(
    context: dagster.AssetExecutionContext,
    plo_base_targets: pl.DataFrame,
) -> pl.DataFrame:
    """Enrich base targets with qualifying signals."""
    if len(plo_base_targets) == 0:
        context.log.info("No base targets to enrich")
        return plo_base_targets.with_columns(
            pl.lit(0).alias("multi_product_count"),
            pl.lit(0.0).alias("event_growth_pct"),
            pl.lit(0).alias("new_user_count"),
            pl.lit("").alias("new_products"),
        )

    org_ids = plo_base_targets["organization_id"].unique().to_list()
    context.log.info("Enriching %d orgs with qualifying signals", len(org_ids))

    # Shared: fetch team→org mapping with product flags
    team_df = build_team_product_df(org_ids)
    context.log.info("Found %d teams across target orgs", len(team_df))

    # Signal 1: Multi-product usage
    multi_product = compute_multi_product_usage(team_df)
    context.log.info("Computed multi-product usage for %d orgs", len(multi_product))

    # Signal 2: Event growth MoM
    event_growth = compute_event_growth(team_df)
    context.log.info("Computed event growth for %d orgs", len(event_growth))

    # Signal 3: New users in last 30 days
    new_users = compute_new_users_30d(org_ids)
    context.log.info("Computed new users for %d orgs", len(new_users))

    # Signal 4: New product this month
    new_products = compute_new_product_this_month(team_df)
    context.log.info("Computed new products for %d orgs", len(new_products))

    # Join signals onto base targets
    org_id_list = plo_base_targets["organization_id"].to_list()
    df = plo_base_targets.with_columns(
        pl.Series("multi_product_count", [multi_product.get(oid, 0) for oid in org_id_list]),
        pl.Series("event_growth_pct", [event_growth.get(oid, 0.0) for oid in org_id_list]),
        pl.Series("new_user_count", [new_users.get(oid, 0) for oid in org_id_list]),
        pl.Series("new_products", [new_products.get(oid, "") for oid in org_id_list]),
    )

    context.log.info("Enrichment complete: %d rows with signal columns", len(df))
    return df


@dagster.asset(
    name="plo_qualified_to_clay",
    group_name="billing",
    tags={"owner": JobOwners.TEAM_BILLING.value},
    deps=["qualify_signals"],
)
def plo_qualified_to_clay(
    context: dagster.AssetExecutionContext,
    clay_webhook_plo: dagster.ResourceParam[ClayWebhookResource],
    qualify_signals: pl.DataFrame,
) -> None:
    """Filter qualified targets and send to Clay with incremental hash-based change detection."""
    from posthog.dags.common.utils import compute_dataframe_hashes

    # Filter to qualified rows
    qualified_df = filter_qualified(qualify_signals)
    context.log.info("Filtered to %d qualified targets from %d total", len(qualified_df), len(qualify_signals))

    if len(qualified_df) == 0:
        prior_hashes = get_plo_prior_hashes(context)
        context.add_output_metadata(
            {
                "org_hashes": MetadataValue.json(prior_hashes),
                "orgs_synced": MetadataValue.int(0),
                "total_qualified": MetadataValue.int(0),
            }
        )
        return

    # Compute hashes for change detection
    qualified_df = compute_dataframe_hashes(qualified_df)

    # Get prior hashes
    prior_hashes = get_plo_prior_hashes(context)
    if not prior_hashes:
        context.log.info("No previous sync state found, will sync all qualified targets")
    else:
        context.log.info("Found %d previously synced orgs", len(prior_hashes))

    # Filter to changed rows using organization_id as key
    mask = [
        prior_hashes.get(o) != h
        for o, h in zip(qualified_df["organization_id"].to_list(), qualified_df["data_hash"].to_list())
    ]
    changed_df = qualified_df.filter(pl.Series(mask))

    # Build current hashes for metadata
    current_hashes = dict(zip(qualified_df["organization_id"].to_list(), qualified_df["data_hash"].to_list()))

    if len(changed_df) == 0:
        context.log.info("No new or changed qualified targets to sync")
        context.add_output_metadata(
            {
                "org_hashes": MetadataValue.json(current_hashes),
                "orgs_synced": MetadataValue.int(0),
                "total_qualified": MetadataValue.int(len(qualified_df)),
            }
        )
        return

    context.log.info("Sending %d new/changed qualified targets to Clay", len(changed_df))

    org_ids = changed_df["organization_id"].to_list()
    org_users = fetch_org_users(org_ids)
    payload = dataframe_to_plo_clay_payload(changed_df, org_users)
    batch_result = clay_webhook_plo.create_batches(payload, logger=context.log, truncatable_fields=TRUNCATABLE_FIELDS)

    for i, batch in enumerate(batch_result.batches):
        clay_webhook_plo.send(batch)
        context.log.info("Sent batch %d/%d with %d records", i + 1, len(batch_result.batches), len(batch))

    context.log.info("Sent %d batches to Clay", len(batch_result.batches))

    context.add_output_metadata(
        {
            "org_hashes": MetadataValue.json(current_hashes),
            "orgs_synced": MetadataValue.int(len(changed_df)),
            "total_qualified": MetadataValue.int(len(qualified_df)),
            "batches_sent": MetadataValue.int(len(batch_result.batches)),
            "records_truncated": MetadataValue.int(batch_result.truncated_count),
            "records_skipped": MetadataValue.int(batch_result.skipped_count),
        }
    )

    context.log.info("Synced %d orgs, stored %d hashes in metadata", len(changed_df), len(current_hashes))


plo_job = dagster.define_asset_job(
    name="product_led_outbound_job",
    selection=["plo_base_targets", "qualify_signals", "plo_qualified_to_clay"],
    tags={"owner": JobOwners.TEAM_BILLING.value},
)


@dagster.schedule(
    cron_schedule="0 7 * * *",
    job=plo_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_BILLING.value},
)
def plo_daily_schedule(context: dagster.ScheduleEvaluationContext):
    """Run product-led outbound targeting pipeline daily at 7 AM UTC."""
    context.log.info("Triggering daily PLO targeting pipeline")
    return dagster.RunRequest()
