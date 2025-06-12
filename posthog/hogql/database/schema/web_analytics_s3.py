from posthog.hogql.database.models import FieldOrTable
from posthog.hogql.database.s3_table import S3Table
from posthog.hogql.database.schema.web_analytics_preaggregated import (
    web_preaggregated_base_fields,
    web_preaggregated_base_aggregation_fields,
    WEB_BOUNCES_SPECIFIC_FIELDS,
)
from django.conf import settings
from posthog.settings.dagster import DAGSTER_DATA_EXPORT_S3_BUCKET
from posthog.settings.object_storage import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
    OBJECT_STORAGE_PREAGGREGATED_WEB_ANALYTICS_FOLDER,
)


def get_s3_url(team_id: int, table_name: str) -> str:
    if settings.DEBUG:
        s3_endpoint = "http://objectstorage:19000"
        bucket = "posthog"
        key = f"{OBJECT_STORAGE_PREAGGREGATED_WEB_ANALYTICS_FOLDER}/{table_name}"
        return f"{s3_endpoint}/{bucket}/{key}"

    base_url = f"https://{DAGSTER_DATA_EXPORT_S3_BUCKET}.s3.amazonaws.com"

    return f"{base_url}/{OBJECT_STORAGE_PREAGGREGATED_WEB_ANALYTICS_FOLDER}/{table_name}"


def get_s3_web_stats_structure() -> str:
    return """
        period_bucket DateTime,
        team_id UInt64,
        persons_uniq_state AggregateFunction(uniq, UUID),
        sessions_uniq_state AggregateFunction(uniq, String),
        pageviews_count_state AggregateFunction(sum, UInt64)
    """


def get_s3_web_bounces_structure() -> str:
    return """
        period_bucket DateTime,
        team_id UInt64,
        persons_uniq_state AggregateFunction(uniq, UUID),
        sessions_uniq_state AggregateFunction(uniq, String),
        pageviews_count_state AggregateFunction(sum, UInt64),
        bounces_count_state AggregateFunction(sum, UInt64),
        total_session_duration_state AggregateFunction(sum, Int64)
    """


# For S3 export, we only need the core fields that are actually exported
WEB_STATS_S3_FIELDS: dict[str, FieldOrTable] = {
    "period_bucket": web_preaggregated_base_fields["period_bucket"],
    "team_id": web_preaggregated_base_fields["team_id"],
    "persons_uniq_state": web_preaggregated_base_aggregation_fields["persons_uniq_state"],
    "sessions_uniq_state": web_preaggregated_base_aggregation_fields["sessions_uniq_state"],
    "pageviews_count_state": web_preaggregated_base_aggregation_fields["pageviews_count_state"],
}

WEB_BOUNCES_S3_FIELDS: dict[str, FieldOrTable] = {
    "period_bucket": web_preaggregated_base_fields["period_bucket"],
    "team_id": web_preaggregated_base_fields["team_id"],
    "persons_uniq_state": web_preaggregated_base_aggregation_fields["persons_uniq_state"],
    "sessions_uniq_state": web_preaggregated_base_aggregation_fields["sessions_uniq_state"],
    "pageviews_count_state": web_preaggregated_base_aggregation_fields["pageviews_count_state"],
    "bounces_count_state": WEB_BOUNCES_SPECIFIC_FIELDS["bounces_count_state"],
    "total_session_duration_state": WEB_BOUNCES_SPECIFIC_FIELDS["total_session_duration_state"],
}


def create_s3_web_stats_table(team_id: int) -> S3Table:
    url = get_s3_url(team_id, "web_stats_daily_export.native")

    return S3Table(
        name="web_stats_daily_s3",
        url=url,
        format="Native",
        access_key=OBJECT_STORAGE_ACCESS_KEY_ID,
        access_secret=OBJECT_STORAGE_SECRET_ACCESS_KEY,
        structure=get_s3_web_stats_structure(),
        fields=WEB_STATS_S3_FIELDS,
    )


def create_s3_web_bounces_table(team_id: int) -> S3Table:
    url = get_s3_url(team_id, "web_bounces_daily_export.native")

    return S3Table(
        name="web_bounces_daily_s3",
        url=url,
        format="Native",
        access_key=OBJECT_STORAGE_ACCESS_KEY_ID,
        access_secret=OBJECT_STORAGE_SECRET_ACCESS_KEY,
        structure=get_s3_web_bounces_structure(),
        fields=WEB_BOUNCES_S3_FIELDS,
    )
