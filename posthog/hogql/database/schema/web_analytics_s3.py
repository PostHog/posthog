from posthog.hogql.database.models import FieldOrTable
from posthog.hogql.database.s3_table import S3Table
from posthog.hogql.database.schema.web_analytics_preaggregated import (
    WEB_BOUNCES_SPECIFIC_FIELDS,
    web_preaggregated_base_aggregation_fields,
    web_preaggregated_base_fields,
)

from posthog.settings.base_variables import DEBUG
from posthog.settings.object_storage import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_EXTERNAL_WEB_ANALYTICS_BUCKET,
    OBJECT_STORAGE_REGION,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
)


def get_s3_function_args(s3_path: str) -> str:
    if DEBUG:
        return f"'{s3_path}', '{OBJECT_STORAGE_ACCESS_KEY_ID}', '{OBJECT_STORAGE_SECRET_ACCESS_KEY}', 'Native'"
    else:
        return f"'{s3_path}', 'Native'"


def get_s3_url(table_name: str, team_id: int) -> str:
    if DEBUG:
        s3_endpoint = "http://objectstorage:19000"
        bucket = "posthog"
        key = f"{table_name}/{team_id}/data.native"
        return f"{s3_endpoint}/{bucket}/{key}"

    base_url = f"https://{OBJECT_STORAGE_EXTERNAL_WEB_ANALYTICS_BUCKET}.s3.{OBJECT_STORAGE_REGION}.amazonaws.com"

    return f"{base_url}/{table_name}/{team_id}/data.native"


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
        total_session_duration_state AggregateFunction(sum, UInt64)
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


def _get_s3_credentials() -> tuple[str | None, str | None]:
    if DEBUG:
        return OBJECT_STORAGE_ACCESS_KEY_ID, OBJECT_STORAGE_SECRET_ACCESS_KEY
    return None, None


def _create_s3_web_table(team_id: int, table_name: str, s3_name: str, structure_func, fields: dict) -> S3Table:
    url = get_s3_url(table_name=table_name, team_id=team_id)
    access_key, access_secret = _get_s3_credentials()

    return S3Table(
        name=s3_name,
        url=url,
        format="Native",
        access_key=access_key,
        access_secret=access_secret,
        structure=structure_func(),
        fields=fields,
    )


def create_s3_web_stats_table(team_id: int) -> S3Table:
    return _create_s3_web_table(
        team_id=team_id,
        table_name="web_stats_daily_export",
        s3_name="web_stats_daily_s3",
        structure_func=get_s3_web_stats_structure,
        fields=WEB_STATS_S3_FIELDS,
    )


def create_s3_web_bounces_table(team_id: int) -> S3Table:
    return _create_s3_web_table(
        team_id=team_id,
        table_name="web_bounces_daily_export",
        s3_name="web_bounces_daily_s3",
        structure_func=get_s3_web_bounces_structure,
        fields=WEB_BOUNCES_S3_FIELDS,
    )
