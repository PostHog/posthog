from dataclasses import asdict
from datetime import date, datetime, time, timedelta

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
from posthog.dags.common.common import EXECUTING_RUN_STATUSES, describe_runs
from posthog.dataclasses import frozen

from products.data_modeling.backend.facade.api import saved_query_ids_by_workflow_id
from products.web_analytics.dags.web_preaggregated_utils import (
    get_partitions,
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

REFRESH_SUBJECTS_TABLE = "refresh_subjects"
PARTITION_ID_FORMAT = "%Y%m%d"
READ_SUBJECT_ID = "read_subject_id"
DIRECTLY_READ_IDS = "log_comment.directly_read_ids::Array(String)"
SUBJECT_ID_TAGS = {
    SubjectKind.SAVED_QUERY: "saved_query_ids",
    SubjectKind.TABLE: "warehouse_table_ids",
}

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

TEAM_REFRESHES_SQL = f"""
SELECT team_id, groupUniqArray(lc_temporal__workflow_id) AS refresh_workflow_ids
FROM {QUERY_LOG_ARCHIVE_TABLE}
WHERE {ARCHIVE_ROW_FILTER}
    AND {REFRESH_ROW_FILTER}
GROUP BY team_id
"""

daily_partitions = dagster.DailyPartitionsDefinition(start_date=ROLLUP_START_DATE, timezone="UTC")


@frozen
class TeamRefreshesOnDay:
    team_id: int
    refresh_workflow_ids: tuple[str, ...]


@frozen
class RefreshSubjectRow:
    team_id: int
    workflow_id: str
    subject_id: str


def _archive_branch_sql(
    *,
    read_kind: ReadKind,
    subject_kind: SubjectKind,
    subject_id: str,
    workflow_id: str,
    read_alone: str,
    array_join: str,
    extra_filter: str,
) -> str:
    return f"""
    SELECT
        team_id,
        '{read_kind.value}' AS read_kind,
        '{subject_kind.value}' AS subject_kind,
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
        {read_alone} AS read_alone
    FROM {QUERY_LOG_ARCHIVE_TABLE}
    {array_join}
    WHERE {ARCHIVE_ROW_FILTER}{extra_filter}"""


def _subject_reads_sql(subject_kind: SubjectKind) -> str:
    return _archive_branch_sql(
        read_kind=ReadKind.READ,
        subject_kind=subject_kind,
        subject_id=READ_SUBJECT_ID,
        workflow_id="''",
        read_alone=f"{DIRECTLY_READ_IDS} = [{READ_SUBJECT_ID}]",
        array_join=f"ARRAY JOIN log_comment.{SUBJECT_ID_TAGS[subject_kind]}::Array(String) AS {READ_SUBJECT_ID}",
        extra_filter="",
    )


REFRESH_READS_SQL = _archive_branch_sql(
    read_kind=ReadKind.REFRESH,
    subject_kind=SubjectKind.SAVED_QUERY,
    subject_id="''",
    workflow_id="lc_temporal__workflow_id",
    read_alone="false",
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
        reads.subject_kind AS subject_kind,
        if(reads.read_kind = '{ReadKind.REFRESH.value}', {REFRESH_SUBJECTS_TABLE}.subject_id, reads.subject_id) AS subject_id,
        reads.workflow_id AS workflow_id,
        reads.lc_kind AS lc_kind,
        reads.lc_product AS lc_product,
        reads.lc_feature AS lc_feature,
        reads.lc_access_method AS lc_access_method,
        reads.source AS source,
        reads.scene AS scene,
        reads.has_user_id AS has_user_id,
        reads.read_alone AS read_alone,
        reads.request_id AS request_id,
        reads.user_id AS user_id,
        reads.query_duration_ms AS query_duration_ms,
        reads.read_bytes AS read_bytes,
        reads.event_time AS event_time
    FROM ({_subject_reads_sql(SubjectKind.SAVED_QUERY)}
    UNION ALL{_subject_reads_sql(SubjectKind.TABLE)}
    UNION ALL{REFRESH_READS_SQL}
    ) AS reads
    LEFT JOIN {REFRESH_SUBJECTS_TABLE}
        ON reads.team_id = {REFRESH_SUBJECTS_TABLE}.team_id AND reads.workflow_id = {REFRESH_SUBJECTS_TABLE}.workflow_id
)
WHERE subject_id != ''
GROUP BY {", ".join(SORT_KEY_COLUMNS)}
"""


def _day_query_parameters(day: date) -> dict[str, date | datetime | str]:
    day_start = datetime.combine(day, time.min)
    return {
        "day": day,
        "day_start": day_start,
        "day_end": day_start + timedelta(days=1),
    }


def find_team_refreshes(client: Client, day: date) -> list[TeamRefreshesOnDay]:
    rows = client.execute(TEAM_REFRESHES_SQL, _day_query_parameters(day))
    return [
        TeamRefreshesOnDay(team_id=team_id, refresh_workflow_ids=tuple(refresh_workflow_ids))
        for team_id, refresh_workflow_ids in rows
    ]


def _refresh_subject_rows(team: TeamRefreshesOnDay) -> list[RefreshSubjectRow]:
    return [
        RefreshSubjectRow(team_id=team.team_id, workflow_id=workflow_id, subject_id=saved_query_id)
        for workflow_id, saved_query_id in saved_query_ids_by_workflow_id(
            team.team_id, team.refresh_workflow_ids
        ).items()
    ]


def load_refresh_subjects(teams: list[TeamRefreshesOnDay]) -> list[RefreshSubjectRow]:
    return [row for team in teams for row in _refresh_subject_rows(team)]


def as_external_table(refresh_subjects: list[RefreshSubjectRow]) -> ClickHouseExternalTable:
    return ClickHouseExternalTable(
        name=REFRESH_SUBJECTS_TABLE,
        structure=[("team_id", "Int64"), ("workflow_id", "String"), ("subject_id", "String")],
        data=[asdict(row) for row in refresh_subjects],
    )


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


def refuse_to_run_beside_another_rollup(context: dagster.OpExecutionContext) -> None:
    others = describe_runs(
        context.instance, (context.job_name,), statuses=EXECUTING_RUN_STATUSES, exclude_run_id=context.run_id
    )
    if others:
        raise dagster.Failure(
            description=f"{'; '.join(others)} is executing, and every run shares one staging table. "
            "Wait for that run to finish, then run this day again."
        )


def publish_day(context: dagster.OpExecutionContext, cluster: ClickhouseCluster, day: date) -> None:
    sync_partitions_on_replicas(context, cluster, SAVED_QUERY_READS_DAILY_STAGING_TABLE)
    if get_partitions(context, cluster, SAVED_QUERY_READS_DAILY_STAGING_TABLE, filter_by_partition_window=True):
        swap_partitions_from_staging(
            context, cluster, SAVED_QUERY_READS_DAILY_TABLE, SAVED_QUERY_READS_DAILY_STAGING_TABLE
        )
        return
    drop_day_partition(cluster, day)


def drop_day_partition(cluster: ClickhouseCluster, day: date) -> None:
    cluster.any_host_by_roles(
        lambda client: client.execute(
            f"ALTER TABLE {SAVED_QUERY_READS_DAILY_TABLE} DROP PARTITION ID %(partition_id)s",
            {"partition_id": day.strftime(PARTITION_ID_FORMAT)},
        ),
        [NodeRole.DATA],
    ).result()


@dagster.op
def rollup_saved_query_reads_for_day(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> None:
    refuse_to_run_beside_another_rollup(context)
    day = date.fromisoformat(context.partition_key)
    teams = cluster.any_host_by_roles(lambda client: find_team_refreshes(client, day), [NodeRole.DATA]).result()
    refresh_subjects = load_refresh_subjects(teams)
    context.log.info(f"Rolling up saved query reads for {day}")

    recreate_staging_table(
        context, cluster, SAVED_QUERY_READS_DAILY_STAGING_TABLE, REPLACE_SAVED_QUERY_READS_DAILY_STAGING_TABLE_SQL
    )
    insert_rollup_into_staging(context, cluster, day, [as_external_table(refresh_subjects)])
    publish_day(context, cluster, day)

    context.add_output_metadata(
        {
            "refresh_teams": dagster.MetadataValue.int(len(teams)),
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
