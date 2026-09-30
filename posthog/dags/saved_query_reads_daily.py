from datetime import date, datetime, time, timedelta
from typing import Any

import dagster
from clickhouse_driver import Client

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.execute import ClickHouseExternalTable
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.clickhouse.query_tagging import Feature
from posthog.clickhouse.saved_query_reads import (
    REPLACE_SAVED_QUERY_READS_DAILY_STAGING_TABLE_SQL,
    SAVED_QUERY_READS_DAILY_STAGING_TABLE,
    SAVED_QUERY_READS_DAILY_TABLE,
    SORT_KEY_COLUMNS,
    ReadKind,
    SubjectKind,
)
from posthog.dags.common import JobOwners, settings_with_log_comment
from posthog.dataclasses import frozen

from products.data_modeling.backend.facade.api import all_saved_query_names, saved_query_ids_by_workflow_id
from products.warehouse_sources.backend.facade.api import all_queryable_table_keys
from products.web_analytics.dags.web_preaggregated_utils import (
    recreate_staging_table,
    swap_partitions_from_staging,
    sync_partitions_on_replicas,
)

QUERY_LOG_ARCHIVE_TABLE = "query_log_archive"
TEMPORAL_QUERY_KIND = "temporal"
QUERY_FINISH_TYPE = "QueryFinish"
MAX_EXECUTION_TIME_SECONDS = 600
ROLLUP_START_DATE = "2026-08-01"
SCHEDULE_HOUR_UTC = 7
CONCURRENCY_TAG = {"saved_query_reads_backfill_concurrency": "saved_query_reads_v1"}

SUBJECT_NAMES_TABLE = "subject_names"
REFRESH_SUBJECTS_TABLE = "refresh_subjects"
FROM_OR_JOIN_TARGET_PATTERN = r"(?i)\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)"

AGGREGATE_COLUMNS = (
    "uniqState(request_id) AS requests",
    "uniqState(user_id) AS users",
    "count() AS read_count",
    "sum(query_duration_ms) AS duration_ms_sum",
    "sum(read_bytes) AS read_bytes_sum",
    "quantilesState(0.5, 0.9)(query_duration_ms) AS duration_ms_quantiles",
    "quantilesState(0.5, 0.9)(read_bytes) AS read_bytes_quantiles",
    "max(event_time) AS max_event_time",
)

ARCHIVE_ROW_FILTER = f"""event_date = %(day)s
        AND event_time >= %(day_start)s AND event_time < %(day_end)s
        AND is_initial_query
        AND type = '{QUERY_FINISH_TYPE}'
        AND NOT lc_is_impersonated"""

REFRESH_ROW_FILTER = f"""lc_feature = '{Feature.DATA_MODELING.value}'
        AND lc_kind = '{TEMPORAL_QUERY_KIND}'
        AND lc_temporal__workflow_id != ''"""

TEAMS_WITH_READS_SQL = f"""
SELECT
    team_id,
    countIf(notEmpty(log_comment.saved_query_ids::Array(String))) > 0 AS has_view_reads,
    groupUniqArrayIf(lc_temporal__workflow_id, {REFRESH_ROW_FILTER}) AS refresh_workflow_ids
FROM {QUERY_LOG_ARCHIVE_TABLE}
WHERE {ARCHIVE_ROW_FILTER}
GROUP BY team_id
HAVING has_view_reads OR notEmpty(refresh_workflow_ids)
"""

daily_partitions = dagster.DailyPartitionsDefinition(start_date=ROLLUP_START_DATE, timezone="UTC")


@frozen
class TeamReadsOnDay:
    team_id: int
    has_view_reads: bool
    refresh_workflow_ids: tuple[str, ...]


def _archive_branch_sql(
    *, read_kind: ReadKind, subject_id: str, workflow_id: str, queried_names: str, array_join: str, extra_filter: str
) -> str:
    return f"""
    SELECT
        team_id,
        '{read_kind.value}' AS read_kind,
        {subject_id} AS subject_id,
        {workflow_id} AS workflow_id,
        lc_kind,
        lc_product,
        lc_feature,
        lc_access_method,
        log_comment.source::String AS source,
        log_comment.scene::String AS scene,
        lc_user_id > 0 AS has_user_id,
        if(lc_client_query_id = '', query_id, lc_client_query_id) AS request_id,
        lc_user_id AS user_id,
        query_duration_ms,
        read_bytes,
        event_time,
        {queried_names} AS queried_names
    FROM {QUERY_LOG_ARCHIVE_TABLE}
    {array_join}
    WHERE {ARCHIVE_ROW_FILTER}{extra_filter}"""


VIEW_READS_SQL = _archive_branch_sql(
    read_kind=ReadKind.READ,
    subject_id="viewed_saved_query_id",
    workflow_id="''",
    queried_names="arrayDistinct(extractAll(lc_query__query, %(from_or_join_target_pattern)s))",
    array_join="ARRAY JOIN log_comment.saved_query_ids::Array(String) AS viewed_saved_query_id",
    extra_filter="",
)

REFRESH_READS_SQL = _archive_branch_sql(
    read_kind=ReadKind.REFRESH,
    subject_id="''",
    workflow_id="lc_temporal__workflow_id",
    queried_names="CAST([], 'Array(String)')",
    array_join="",
    extra_filter=f"\n        AND {REFRESH_ROW_FILTER}",
)

INSERT_ROLLUP_SQL = f"""
INSERT INTO {SAVED_QUERY_READS_DAILY_STAGING_TABLE}
SELECT
    {", ".join(SORT_KEY_COLUMNS)},
    {", ".join(AGGREGATE_COLUMNS)}
FROM (
    SELECT
        reads.team_id AS team_id,
        toDate(%(day)s) AS day,
        reads.read_kind AS read_kind,
        '{SubjectKind.SAVED_QUERY.value}' AS subject_kind,
        if(reads.read_kind = '{ReadKind.REFRESH.value}', {REFRESH_SUBJECTS_TABLE}.subject_id, reads.subject_id) AS subject_id,
        reads.workflow_id AS workflow_id,
        reads.lc_kind AS lc_kind,
        reads.lc_product AS lc_product,
        reads.lc_feature AS lc_feature,
        reads.lc_access_method AS lc_access_method,
        reads.source AS source,
        reads.scene AS scene,
        reads.has_user_id AS has_user_id,
        arrayFilter(
            name -> (reads.team_id, name) IN (SELECT team_id, name FROM {SUBJECT_NAMES_TABLE}),
            reads.queried_names
        ) AS known_queried_names,
        notEmpty(known_queried_names) AND arrayAll(
            name -> (reads.team_id, subject_id, name) IN (SELECT team_id, subject_id, name FROM {SUBJECT_NAMES_TABLE}),
            known_queried_names
        ) AS names_only_this_subject,
        reads.request_id AS request_id,
        reads.user_id AS user_id,
        reads.query_duration_ms AS query_duration_ms,
        reads.read_bytes AS read_bytes,
        reads.event_time AS event_time
    FROM ({VIEW_READS_SQL}
    UNION ALL{REFRESH_READS_SQL}
    ) AS reads
    LEFT JOIN {REFRESH_SUBJECTS_TABLE}
        ON reads.team_id = {REFRESH_SUBJECTS_TABLE}.team_id AND reads.workflow_id = {REFRESH_SUBJECTS_TABLE}.workflow_id
)
WHERE subject_id != ''
GROUP BY {", ".join(SORT_KEY_COLUMNS)}
"""


def _day_query_parameters(day: date) -> dict[str, Any]:
    day_start = datetime.combine(day, time.min)
    return {
        "day": day,
        "day_start": day_start,
        "day_end": day_start + timedelta(days=1),
        "from_or_join_target_pattern": FROM_OR_JOIN_TARGET_PATTERN,
    }


def find_teams_with_reads(client: Client, day: date) -> list[TeamReadsOnDay]:
    rows = client.execute(TEAMS_WITH_READS_SQL, _day_query_parameters(day))
    return [
        TeamReadsOnDay(
            team_id=team_id, has_view_reads=bool(has_view_reads), refresh_workflow_ids=tuple(refresh_workflow_ids)
        )
        for team_id, has_view_reads, refresh_workflow_ids in rows
    ]


def _subject_name_rows(team_id: int) -> list[dict[str, Any]]:
    view_rows = [
        {"team_id": team_id, "subject_id": saved_query_id, "name": name}
        for saved_query_id, name in all_saved_query_names(team_id).items()
    ]
    table_rows = [
        {"team_id": team_id, "subject_id": str(table_id), "name": name}
        for table_id, table_names in all_queryable_table_keys(team_id).items()
        for name in {table_names.row_name, table_names.queryable_key}
    ]
    return view_rows + table_rows


def _refresh_subject_rows(team: TeamReadsOnDay) -> list[dict[str, Any]]:
    return [
        {"team_id": team.team_id, "workflow_id": workflow_id, "subject_id": saved_query_id}
        for workflow_id, saved_query_id in saved_query_ids_by_workflow_id(
            team.team_id, team.refresh_workflow_ids
        ).items()
    ]


def load_subject_names(teams: list[TeamReadsOnDay]) -> list[dict[str, Any]]:
    return [row for team in teams if team.has_view_reads for row in _subject_name_rows(team.team_id)]


def load_refresh_subjects(teams: list[TeamReadsOnDay]) -> list[dict[str, Any]]:
    return [row for team in teams if team.refresh_workflow_ids for row in _refresh_subject_rows(team)]


def as_external_tables(
    subject_names: list[dict[str, Any]], refresh_subjects: list[dict[str, Any]]
) -> list[ClickHouseExternalTable]:
    return [
        ClickHouseExternalTable(
            name=SUBJECT_NAMES_TABLE,
            structure=[("team_id", "Int64"), ("subject_id", "String"), ("name", "String")],
            data=subject_names,
        ),
        ClickHouseExternalTable(
            name=REFRESH_SUBJECTS_TABLE,
            structure=[("team_id", "Int64"), ("workflow_id", "String"), ("subject_id", "String")],
            data=refresh_subjects,
        ),
    ]


def insert_rollup_into_staging(
    context: dagster.OpExecutionContext,
    cluster: ClickhouseCluster,
    day: date,
    external_tables: list[ClickHouseExternalTable],
) -> None:
    query_settings = {**settings_with_log_comment(context), "max_execution_time": MAX_EXECUTION_TIME_SECONDS}
    cluster.any_host_by_roles(
        lambda client: client.execute(
            INSERT_ROLLUP_SQL, _day_query_parameters(day), settings=query_settings, external_tables=external_tables
        ),
        [NodeRole.DATA],
    ).result()


@dagster.op
def rollup_saved_query_reads_for_day(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> None:
    day = date.fromisoformat(context.partition_key)
    teams = cluster.any_host_by_roles(lambda client: find_teams_with_reads(client, day), [NodeRole.DATA]).result()
    refresh_subjects = load_refresh_subjects(teams)
    context.log.info(f"Rolling up saved query reads for {day} across {len(teams)} teams")

    recreate_staging_table(
        context, cluster, SAVED_QUERY_READS_DAILY_STAGING_TABLE, REPLACE_SAVED_QUERY_READS_DAILY_STAGING_TABLE_SQL
    )
    insert_rollup_into_staging(context, cluster, day, as_external_tables(load_subject_names(teams), refresh_subjects))
    sync_partitions_on_replicas(context, cluster, SAVED_QUERY_READS_DAILY_STAGING_TABLE)
    swap_partitions_from_staging(context, cluster, SAVED_QUERY_READS_DAILY_TABLE, SAVED_QUERY_READS_DAILY_STAGING_TABLE)

    context.add_output_metadata(
        {
            "teams": dagster.MetadataValue.int(len(teams)),
            "refresh_workflows": dagster.MetadataValue.int(sum(len(team.refresh_workflow_ids) for team in teams)),
            "resolved_refresh_workflows": dagster.MetadataValue.int(len(refresh_subjects)),
        }
    )


@dagster.job(
    partitions_def=daily_partitions,
    tags={"owner": JobOwners.TEAM_DATA_MODELING.value, **CONCURRENCY_TAG},
)
def saved_query_reads_daily_job() -> None:
    rollup_saved_query_reads_for_day()


saved_query_reads_daily_schedule = dagster.build_schedule_from_partitioned_job(
    saved_query_reads_daily_job,
    hour_of_day=SCHEDULE_HOUR_UTC,
    minute_of_hour=0,
    default_status=dagster.DefaultScheduleStatus.STOPPED,
)
