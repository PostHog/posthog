from dataclasses import dataclass
from datetime import datetime, UTC
import re
import time
from typing import Any, Optional
from collections.abc import Callable
from clickhouse_driver import Client
import dagster
from django.conf import settings
import pydantic
from dags.common import JobOwners
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import ClickhouseCluster

from dagster_aws.s3 import S3Resource

NO_SHARD_PATH = "noshard"

SHARDED_TABLES = [
    "sharded_app_metrics",
    "sharded_app_metrics2",
    "sharded_heatmaps",
    "sharded_ingestion_warnings",
    "sharded_performance_events",
    "sharded_person_distinct_id",
    "sharded_raw_sessions",
    "sharded_session_replay_embeddings",
    "sharded_session_replay_events",
    "sharded_session_replay_events_v2_test",
    "sharded_sessions",
    "sharded_events",
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
    "infi_clickhouse_orm_migrations_tmp",
    "log_entries",
    "metrics_query_log",
    "metrics_time_to_see_data",
    "pending_person_deletes_reporting",
    "person",
    "person_collapsing",
    "person_distinct_id",
    "person_distinct_id2",
    "person_distinct_id_backup",
    "person_distinct_id_overrides",
    "person_overrides",
    "person_static_cohort",
    "pg_embeddings",
    "plugin_log_entries",
    "swap_person_distinct_id",
]


@dataclass
class BackupStatus:
    hostname: str
    status: str
    event_time_microseconds: datetime
    error: Optional[str] = None


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
            WHERE (start_time >= (now() - toIntervalDay(7))) AND name LIKE '%{self.path}%'
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
    date: str = pydantic.Field(
        default=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        description="The date to backup. If not specified, the current date will be used.",
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
        validate_default=True,
    )


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
def get_latest_backup(
    config: BackupConfig,
    s3: S3Resource,
    shard: Optional[int] = None,
) -> Optional[Backup]:
    """
    Get the latest backup metadata for a ClickHouse database / table from S3.
    """
    shard_path = shard if shard else NO_SHARD_PATH

    base_prefix = f"{config.database}/"
    if config.table:
        base_prefix = f"{base_prefix}{config.table}/"
    base_prefix = f"{base_prefix}{shard_path}/"

    backups = s3.get_client().list_objects_v2(
        Bucket=settings.CLICKHOUSE_BACKUPS_BUCKET, Prefix=base_prefix, Delimiter="/"
    )

    if "CommonPrefixes" not in backups:
        return None

    latest_backup = sorted(backups["CommonPrefixes"], key=lambda x: x["Prefix"])[-1]["Prefix"]
    return Backup.from_s3_path(latest_backup)


@dagster.op
def check_latest_backup_status(
    context: dagster.OpExecutionContext,
    latest_backup: Optional[Backup],
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> Optional[Backup]:
    """
    Check if the latest backup is done.
    """
    if not latest_backup:
        context.log.info("No latest backup found. Skipping status check.")
        return

    def map_hosts(func: Callable[[Client], Any]):
        if latest_backup.shard:
            return cluster.map_all_hosts_in_shard(fn=func, shard_num=latest_backup.shard)
        return cluster.map_all_hosts(fn=func)

    is_done = map_hosts(latest_backup.is_done).result().values()
    if not all(is_done):
        context.log.info(f"Latest backup {latest_backup.path} is still in progress, waiting for it to finish")
        map_hosts(latest_backup.wait).result()
    else:
        most_recent_status = get_most_recent_status(map_hosts(latest_backup.status).result().values())
        if most_recent_status and most_recent_status.status != "BACKUP_CREATED":
            raise ValueError(
                f"Latest backup {latest_backup.path} finished with an unexpected status: {most_recent_status.status} on the host {most_recent_status.hostname}. Please clean it from S3 before running a new backup."
            )
        else:
            context.log.info(f"Latest backup {latest_backup.path} finished successfully")

    return latest_backup


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
        date=config.date,
        base_backup=latest_backup if config.incremental else None,
        shard=shard,
    )

    if latest_backup and latest_backup.path == backup.path:
        context.log.warning(
            f"This backup directory exists in S3. Skipping its run, if you want to run it again, remove the data from {backup.path}"
        )
        return

    if backup.shard:
        cluster.map_any_host_in_shards({backup.shard: backup.create}).result()
    else:
        cluster.any_host_by_role(backup.create, NodeRole.DATA).result()

    return backup


@dagster.op
def wait_for_backup(
    context: dagster.OpExecutionContext,
    backup: Optional[Backup],
    cluster: dagster.ResourceParam[ClickhouseCluster],
):
    """
    Wait for a backup to finish.
    """

    def map_hosts(func: Callable[[Client], Any]):
        if backup.shard:
            return cluster.map_all_hosts_in_shard(fn=func, shard_num=backup.shard)
        return cluster.map_all_hosts(fn=func)

    if backup:
        map_hosts(backup.wait).result().values()
        most_recent_status = get_most_recent_status(map_hosts(backup.status).result().values())
        if most_recent_status and most_recent_status.status != "BACKUP_CREATED":
            raise ValueError(
                f"Latest backup {backup.path} finished with an unexpected status: {most_recent_status.status} on the host {most_recent_status.hostname}. Please clean it from S3 before running a new backup."
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
        latest_backup = get_latest_backup(shard)
        new_backup = run_backup(check_latest_backup_status(latest_backup), shard)
        wait_for_backup(new_backup)

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
    latest_backup = get_latest_backup()
    new_backup = run_backup(check_latest_backup_status(latest_backup))
    wait_for_backup(new_backup)


def run_backup_request(table: str, incremental: bool) -> dagster.RunRequest:
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    config = BackupConfig(
        database=settings.CLICKHOUSE_DATABASE,
        date=timestamp,
        table=table,
        incremental=incremental,
    )
    return dagster.RunRequest(
        run_key=f"{timestamp}-{table}",
        run_config={
            "ops": {
                "get_latest_backup": {"config": config.model_dump()},
                "run_backup": {"config": config.model_dump()},
            }
        },
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
def full_sharded_backup_schedule():
    """Launch a full backup for sharded tables"""
    for table in SHARDED_TABLES:
        yield run_backup_request(table, incremental=False)


@dagster.schedule(
    job=non_sharded_backup,
    cron_schedule=settings.CLICKHOUSE_FULL_BACKUP_SCHEDULE,
    default_status=dagster.DefaultScheduleStatus.RUNNING,
)
def full_non_sharded_backup_schedule():
    """Launch a full backup for non-sharded tables"""
    for table in NON_SHARDED_TABLES:
        yield run_backup_request(table, incremental=False)


@dagster.schedule(
    job=sharded_backup,
    cron_schedule=settings.CLICKHOUSE_INCREMENTAL_BACKUP_SCHEDULE,
    default_status=dagster.DefaultScheduleStatus.RUNNING,
)
def incremental_sharded_backup_schedule():
    """Launch an incremental backup for sharded tables"""
    for table in SHARDED_TABLES:
        yield run_backup_request(table, incremental=True)


@dagster.schedule(
    job=non_sharded_backup,
    cron_schedule=settings.CLICKHOUSE_INCREMENTAL_BACKUP_SCHEDULE,
    default_status=dagster.DefaultScheduleStatus.RUNNING,
)
def incremental_non_sharded_backup_schedule():
    """Launch an incremental backup for non-sharded tables"""
    for table in NON_SHARDED_TABLES:
        yield run_backup_request(table, incremental=True)
