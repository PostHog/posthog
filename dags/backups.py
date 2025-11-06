import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Optional

from django.conf import settings

import dagster
import pydantic
from clickhouse_driver import Client
from dagster_aws.s3 import S3Resource

from posthog.clickhouse.client.connection import NodeRole, Workload
from posthog.clickhouse.cluster import ClickhouseCluster

from dags.common import JobOwners, check_for_concurrent_runs

NO_SHARD_PATH = "noshard"


def get_max_backup_bandwidth() -> str:
    """
    Get max backup bandwidth based on the current environment.

    Returns different bandwidth limits based on CLOUD_DEPLOYMENT:
    - US: i7ie.metal-48xl instances (192 vCPUs, 768GB RAM, 100 Gbps network)
    - EU: m8g.8xlarge instances (32 vCPUs, 128GB RAM, 12 Gbps network)
    - DEV/E2E/None: Conservative limits for development/self-hosted

    Target: Complete backups within ~20 hours while preserving network capacity
    """
    cloud_deployment = getattr(settings, "CLOUD_DEPLOYMENT", None)

    if cloud_deployment == "US":
        # i7ie.metal-48xl instances - can handle higher bandwidth
        # 2400 MB/s = 19.2 Gbps (19% of 100 Gbps network)
        # For 208TB: ~24 hour backup time
        return "2400000000"  # 2400MB/s
    elif cloud_deployment == "EU":
        # m8g.8xlarge instances - moderate bandwidth
        # 450 MB/s = 3.6 Gbps (30% of 12 Gbps network)
        # For 48TB: ~29 hour backup time
        return "450000000"  # 450MB/s
    else:
        # DEV/self-hosted - conservative limits
        return "100000000"  # 100MB/s to prevent resource exhaustion


SHARDED_TABLES = [
    "sharded_events",
    "sharded_app_metrics",
    "sharded_app_metrics2",
    "sharded_heatmaps",
    "sharded_ingestion_warnings",
    "sharded_performance_events",
    "sharded_raw_sessions",
    "sharded_session_replay_embeddings",
    "sharded_session_replay_events",
    "sharded_sessions",
]

NON_SHARDED_TABLES = [
    "asyncdeletion",
    "channel_definition",
    "cohortpeople",
    "error_tracking_issue_fingerprint_overrides",
    "events_dead_letter_queue",
    "events_plugin_ingestion_partition_statistics_v2",
    "exchange_rate",
    "groups",
    "infi_clickhouse_orm_migrations",
    "log_entries",
    "metrics_query_log",
    "metrics_time_to_see_data",
    "pending_person_deletes_reporting",
    "person",
    "person_collapsing",
    "person_distinct_id",
    "person_distinct_id2",
    "person_distinct_id_overrides",
    "person_overrides",
    "person_static_cohort",
    "pg_embeddings",
    "plugin_log_entries",
    "swap_person_distinct_id",
]


@dataclass
class Table:
    name: str

    def is_backup_in_progress(self, client: Client) -> bool:
        # We query the processes table to check if a backup for the requested table is in progress
        rows = client.execute(
            f"""
            SELECT EXISTS(
                SELECT 1
                FROM system.processes
                WHERE query_kind = 'Backup' AND query like '%{self.name}%'
            )
            """
        )

        [[exists]] = rows
        return exists


@dataclass
class BackupStatus:
    hostname: str
    status: str
    event_time_microseconds: datetime
    error: Optional[str] = None

    def is_success(self) -> bool:
        return self.status == "BACKUP_CREATED"


@dataclass
class Backup:
    database: str
    date: str
    table: Optional[str] = None
    id: Optional[str] = None
    base_backup: Optional["Backup"] = None
    shard: Optional[int] = None

    def __post_init__(self):
        datetime.strptime(self.date, "%Y-%m-%dT%H:%M:%SZ")  # It will fail if the date is invalid

    @property
    def path(self):
        base_path = f"{self.database}"
        shard_path = self.shard if self.shard else NO_SHARD_PATH
        if self.table:
            base_path = f"{base_path}/{self.table}"

        return f"{base_path}/{shard_path}/{self.date}"

    def _bucket_base_path(self, bucket: str):
        return f"https://{bucket}.s3.amazonaws.com"

    @classmethod
    def from_s3_path(cls, path: str) -> "Backup":
        path_regex = re.compile(
            r"^(?P<database>\w+)(\/(?P<table>\w+))?\/(?P<shard>\w+)\/(?P<date>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\/$"
        )
        match = path_regex.match(path)
        if not match:
            raise ValueError(f"Could not parse backup path: {path}. It does not match the regex: {path_regex.pattern}")

        return Backup(
            database=match.group("database"),
            date=match.group("date"),
            table=match.group("table"),
            base_backup=None,
            shard=None if match.group("shard") == NO_SHARD_PATH else int(match.group("shard")),
        )

    def create(self, client: Client):
        backup_settings = {
            "async": "1",
            "max_backup_bandwidth": get_max_backup_bandwidth(),
            # There is a CH issue that makes bandwith be half than what is configured: https://github.com/ClickHouse/ClickHouse/issues/78213
            "s3_disable_checksum": "1",
            # According to CH docs, disabling this is safe enough as checksums are already made: https://clickhouse.com/docs/operations/settings/settings#s3_disable_checksum
        }
        if self.base_backup:
            backup_settings["base_backup"] = "S3('{bucket_base_path}/{path}')".format(
                bucket_base_path=self._bucket_base_path(settings.CLICKHOUSE_BACKUPS_BUCKET),
                path=self.base_backup.path,
            )

        query = """
        BACKUP {object} {name}
        TO S3('{bucket_base_path}/{path}')
        SETTINGS {settings}
        """.format(
            bucket_base_path=self._bucket_base_path(settings.CLICKHOUSE_BACKUPS_BUCKET),
            path=self.path,
            object="TABLE" if self.table else "DATABASE",
            name=self.table if self.table else self.database,
            settings=", ".join([f"{k} = {v}" for k, v in backup_settings.items()]),
        )

        client.execute(query, query_id=f"{self.id}-{self.shard if self.shard else 'noshard'}")

    def status(self, client: Client) -> Optional["BackupStatus"]:
        """
        Get the status of the backup from the backup_log table. If a same backup is found
        more than once, it will return the most recent one.

        Returns None if the backup is not found.
        """
        rows = client.execute(
            f"""
            SELECT hostname(), argMax(status, event_time_microseconds), argMax(left(error, 400), event_time_microseconds), max(event_time_microseconds)
            FROM system.backup_log
            WHERE (start_time >= (now() - toIntervalDay(7))) AND name LIKE '%{self.path}%' AND status NOT IN ('RESTORING', 'RESTORED', 'RESTORE_FAILED')
            GROUP BY hostname()
            """
        )

        if len(rows) > 0:
            (hostname, status, error, event_time_microseconds) = rows[0]

            return BackupStatus(
                hostname=hostname,
                status=status,
                error=error,
                event_time_microseconds=event_time_microseconds,
            )

    def is_done(self, client: Client) -> bool:
        # We query the processes table to check if the backup is in progress,
        # because the backup_log table could not be updated (for example, if the server is restarted)
        rows = client.execute(
            f"""
            SELECT NOT EXISTS(
                SELECT 1
                FROM system.processes
                WHERE query_kind = 'Backup' AND query like '%{self.path}%'
            )
            """
        )

        [[exists]] = rows
        return exists

    def wait(self, client: Client) -> None:
        # The query can take a little bit to appear in the system.processes table,
        # so we wait a bit before checking if the backup is done.
        time.sleep(5)

        while not self.is_done(client):
            time.sleep(120)


class BackupConfig(dagster.Config):
    incremental: bool = pydantic.Field(
        default=False,
        description="If true, the backup will be incremental. If false, the backup will be full.",
    )
    database: str = pydantic.Field(
        default=settings.CLICKHOUSE_DATABASE,
        description="The database to backup",
    )
    table: str = pydantic.Field(
        default="",
        description="The table to backup. If not specified, the entire database will be backed up.",
    )
    workload: Workload = Workload.OFFLINE


def get_most_recent_status(statuses: list[BackupStatus]) -> Optional[BackupStatus]:
    """
    Since we can retry backups and we only can identify them by their name (or path to S3),
    in case we retry several times, we can have the same backup failed in one node and
    succeeded in another one.

    This function will raise an error only if the most recent one didn't succeed
    """
    statuses = [status for status in statuses if status is not None]
    if statuses:
        return max(statuses, key=lambda x: x.event_time_microseconds)


@dagster.op(out=dagster.DynamicOut())
def get_shards(cluster: dagster.ResourceParam[ClickhouseCluster]):
    for shard in cluster.shards:
        yield dagster.DynamicOutput(shard, mapping_key=f"shard_{shard}")


@dagster.op
def check_running_backup_for_table(
    config: BackupConfig, cluster: dagster.ResourceParam[ClickhouseCluster]
) -> Optional[Table]:
    """
    Check if a backup for the requested table is in progress (it shouldn't, so fail if that's the case).
    """
    table = Table(name=config.table)
    is_running_backup = (
        cluster.map_hosts_by_role(table.is_backup_in_progress, node_role=NodeRole.DATA, workload=config.workload)
        .result()
        .values()
    )
    if any(is_running_backup):
        raise dagster.Failure(
            description=f"A backup for table {table.name} is still in progress, this run shouldn't have been triggered. Review concurrency limits / schedule triggering logic. If there is not Dagster job running and there is a backup going on, it's worth checking what happened."
        )

    return table


@dagster.op
def get_latest_backups(
    context: dagster.OpExecutionContext,
    config: BackupConfig,
    s3: S3Resource,
    running_backup: Optional[Table] = None,
    shard: Optional[int] = None,
) -> list[Backup]:
    """
    Get the latest 15 backups metadata for a ClickHouse database / table from S3.

    They are sorted from most recent to oldest.
    """
    shard_path = shard if shard else NO_SHARD_PATH

    base_prefix = f"{config.database}/"
    if config.table:
        base_prefix = f"{base_prefix}{config.table}/"
    base_prefix = f"{base_prefix}{shard_path}/"

    backups = s3.get_client().list_objects_v2(
        Bucket=settings.CLICKHOUSE_BACKUPS_BUCKET, Prefix=base_prefix, Delimiter="/", MaxKeys=15
    )

    if "CommonPrefixes" not in backups:
        return []

    latest_backups = [
        Backup.from_s3_path(backup["Prefix"])
        for backup in sorted(backups["CommonPrefixes"], key=lambda x: x["Prefix"], reverse=True)
    ]
    context.log.info(f"Found {len(latest_backups)} latest backups: {latest_backups}")
    return latest_backups


@dagster.op
def check_latest_backup_status(
    context: dagster.OpExecutionContext,
    config: BackupConfig,
    latest_backups: list[Backup],
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> Optional[Backup]:
    """
    Checks the latest succesful backup to use it as a base backup.
    """
    if not latest_backups or not config.incremental:
        context.log.info("No latest backup found or a full backup was requested. Skipping status check.")
        return

    def map_hosts(func: Callable[[Client], Any]):
        if latest_backup.shard:
            return cluster.map_hosts_in_shard_by_role(
                fn=func, shard_num=latest_backup.shard, node_role=NodeRole.DATA, workload=config.workload
            )
        return cluster.map_hosts_by_role(fn=func, node_role=NodeRole.DATA, workload=config.workload)

    context.log.info(f"Find latest successful created backup")
    for latest_backup in latest_backups:
        context.log.info(f"Checking status of backup: {latest_backup.path}")
        most_recent_status = get_most_recent_status(map_hosts(latest_backup.status).result().values())
        if most_recent_status and not most_recent_status.is_success():
            context.log.warning(
                f"Backup {latest_backup.path} finished with an unexpected status: {most_recent_status.status} on the host {most_recent_status.hostname}. Checking next backup."
            )
        else:
            context.log.info(
                f"Backup {latest_backup.path} finished successfully. Using it as the base backup for the new backup."
            )
            return latest_backup

    raise dagster.Failure(
        f"All {len(latest_backups)} latest backups finished with an unexpected status. Please review them before launching a new one."
    )


@dagster.op
def run_backup(
    context: dagster.OpExecutionContext,
    config: BackupConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    latest_backup: Optional[Backup],
    shard: Optional[int] = None,
):
    """
    Run the incremental or full backup
    """
    if config.incremental:
        if not latest_backup:
            raise ValueError("Latest backup not found and an incremental backup was requested")

    backup = Backup(
        id=context.run_id,
        database=config.database,
        table=config.table,
        date=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        base_backup=latest_backup if config.incremental else None,
        shard=shard,
    )

    context.log.info(f"Running backup for table {config.table} in path: {backup.path}")

    if backup.shard:
        cluster.map_any_host_in_shards_by_role(
            {backup.shard: backup.create},
            node_role=NodeRole.DATA,
            workload=config.workload,
        ).result()
    else:
        cluster.any_host_by_role(
            backup.create,
            node_role=NodeRole.DATA,
            workload=config.workload,
        ).result()

    return backup


@dagster.op
def wait_for_backup(
    context: dagster.OpExecutionContext,
    config: BackupConfig,
    backup: Optional[Backup],
    cluster: dagster.ResourceParam[ClickhouseCluster],
):
    """
    Wait for a backup to finish.
    """

    def map_hosts(func: Callable[[Client], Any]):
        if backup.shard:
            return cluster.map_hosts_in_shard_by_role(
                fn=func, shard_num=backup.shard, node_role=NodeRole.DATA, workload=config.workload
            )
        return cluster.map_hosts_by_role(fn=func, node_role=NodeRole.DATA, workload=config.workload)

    done = False
    tries = 0
    if backup:
        while not done:
            tries += 1
            map_hosts(backup.wait).result().values()
            most_recent_status = get_most_recent_status(map_hosts(backup.status).result().values())
            if most_recent_status and most_recent_status.status == "CREATING_BACKUP":
                continue
            if most_recent_status and most_recent_status.status == "BACKUP_CREATED":
                context.log.info(f"Backup for table {backup.table} in path {backup.path} finished successfully")
                done = True
            if (most_recent_status and most_recent_status.status != "BACKUP_CREATED") or (
                most_recent_status and tries >= 5
            ):
                raise ValueError(
                    f"Backup {backup.path} finished with an unexpected status: {most_recent_status.status} on the host {most_recent_status.hostname}."
                )
    else:
        context.log.info("No backup to wait for")


@dagster.job(
    executor_def=dagster.multiprocess_executor.configured({"max_concurrent": 2}),
)
def sharded_backup():
    """
    Backup ClickHouse database / table to S3 once per shard.

    The job, under the hood, will dynamically launch the same backup for each shard (running the ops once per shard). Shards are dynamically loaded from the ClickHouse cluster.

    For each backup, the logic is exactly the same as the described in the `non_sharded_backup` job.
    """

    def run_backup_for_shard(shard: int):
        latest_backups = get_latest_backups(check_running_backup_for_table(), shard=shard)
        checked_backup = check_latest_backup_status(latest_backups=latest_backups)
        new_backup = run_backup(latest_backup=checked_backup, shard=shard)
        wait_for_backup(backup=new_backup)

    shards: dagster.DynamicOutput = get_shards()
    shards.map(run_backup_for_shard)


@dagster.job(
    executor_def=dagster.multiprocess_executor.configured({"max_concurrent": 8}),
)
def non_sharded_backup():
    """
    Backup ClickHouse database / table to S3 once (chooses a random shard)

    First, it will get the latest backup metadata from S3. This will be useful to check if the requested backup was already done, is in progress or it failed.
    If it failed, it will raise an error. If it is in progress, it will wait for it to finish.

    Then, it will run the backup. If the requested backup is the same as the latest backup, it will skip the run.
    Otherwise, if the requested backup is incremental, it will use the latest backup as the base backup for this new one.

    Finally, it will wait for the backup to complete.

    If the backup fails, it will raise an error.

    Since we don't want to keep the state about which host was selected to run the backup, we always search backups by their name in every node.
    When we find it in one of the nodes, we keep waiting on it only in that node. This is handy when we retry the job and a backup is in progress in any node, as we'll always wait for it to finish.
    """
    latest_backups = get_latest_backups(check_running_backup_for_table())
    new_backup = run_backup(check_latest_backup_status(latest_backups=latest_backups))
    wait_for_backup(new_backup)


def prepare_run_config(config: BackupConfig) -> dagster.RunConfig:
    return dagster.RunConfig(
        {
            op.name: {"config": config.model_dump(mode="json")}
            for op in [get_latest_backups, run_backup, check_latest_backup_status, wait_for_backup]
        }
    )


def run_backup_request(
    table: str, incremental: bool, context: dagster.ScheduleEvaluationContext
) -> dagster.RunRequest | dagster.SkipReason:
    skip_reason = check_for_concurrent_runs(
        context,
        tags={
            "table": table,
        },
    )
    if skip_reason:
        return skip_reason

    timestamp = datetime.now(UTC)
    config = BackupConfig(
        database=settings.CLICKHOUSE_DATABASE,
        date=timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        table=table,
        incremental=incremental,
    )

    return dagster.RunRequest(
        run_key=f"{timestamp.strftime('%Y%m%d')}-{table}",
        run_config=prepare_run_config(config),
        tags={
            "backup_type": "incremental" if incremental else "full",
            "table": table,
            "owner": JobOwners.TEAM_CLICKHOUSE.value,
        },
    )


@dagster.schedule(
    job=sharded_backup,
    cron_schedule=settings.CLICKHOUSE_FULL_BACKUP_SCHEDULE,
    default_status=dagster.DefaultScheduleStatus.RUNNING,
)
def full_sharded_backup_schedule(context: dagster.ScheduleEvaluationContext):
    """Launch a full backup for sharded tables"""
    for table in SHARDED_TABLES:
        yield run_backup_request(table, incremental=False, context=context)


@dagster.schedule(
    job=non_sharded_backup,
    cron_schedule=settings.CLICKHOUSE_FULL_BACKUP_SCHEDULE,
    default_status=dagster.DefaultScheduleStatus.RUNNING,
)
def full_non_sharded_backup_schedule(context: dagster.ScheduleEvaluationContext):
    """Launch a full backup for non-sharded tables"""
    for table in NON_SHARDED_TABLES:
        yield run_backup_request(table, incremental=False, context=context)


@dagster.schedule(
    job=sharded_backup,
    cron_schedule=settings.CLICKHOUSE_INCREMENTAL_BACKUP_SCHEDULE,
    default_status=dagster.DefaultScheduleStatus.RUNNING,
)
def incremental_sharded_backup_schedule(context: dagster.ScheduleEvaluationContext):
    """Launch an incremental backup for sharded tables"""
    for table in SHARDED_TABLES:
        yield run_backup_request(table, incremental=True, context=context)


@dagster.schedule(
    job=non_sharded_backup,
    cron_schedule=settings.CLICKHOUSE_INCREMENTAL_BACKUP_SCHEDULE,
    default_status=dagster.DefaultScheduleStatus.RUNNING,
)
def incremental_non_sharded_backup_schedule(context: dagster.ScheduleEvaluationContext):
    """Launch an incremental backup for non-sharded tables"""
    for table in NON_SHARDED_TABLES:
        yield run_backup_request(table, incremental=True, context=context)
