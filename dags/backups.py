from dataclasses import dataclass
from datetime import datetime, UTC
import re
import time
from typing import Optional
from clickhouse_driver import Client
import dagster
from django.conf import settings
import pydantic
from posthog.clickhouse.cluster import ClickhouseCluster

from dagster_aws.s3 import S3Resource


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
        shard_path = "noshard" if self.shard is None else self.shard
        if self.table:
            base_path = f"{base_path}/{self.table}"

        return f"{base_path}/{shard_path}/{self.date}"

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
            shard=match.group("shard"),
        )

    def create(self, client: Client):
        backup_settings = {
            "async": "1",
        }
        if self.base_backup:
            backup_settings["base_backup"] = "S3('https://{bucket}.s3.amazonaws.com/{path}')".format(
                bucket=settings.CLICKHOUSE_BACKUPS_BUCKET,
                path=self.base_backup.path,
            )

        query = """
        BACKUP {object} {name}
        TO S3('https://{bucket}.s3.amazonaws.com/{path}')
        SETTINGS {settings}
        """.format(
            bucket=settings.CLICKHOUSE_BACKUPS_BUCKET,
            path=self.path,
            object="TABLE" if self.table else "DATABASE",
            name=self.table if self.table else self.database,
            settings=", ".join([f"{k} = {v}" for k, v in backup_settings.items()]),
        )

        client.execute(query, query_id=f"{self.id}-{self.shard}")

    def throw_on_error(self, client: Client) -> None:
        rows = client.execute(
            f"""
            SELECT hostname(), argMax(status, event_time_microseconds), argMax(left(error, 200), event_time_microseconds)
            FROM system.backup_log
            WHERE (start_time >= (now() - toIntervalDay(7))) AND name LIKE '%{self.path}%'
            GROUP BY hostname()
            """
        )

        if len(rows) > 0:
            statuses = [status for _, status, _ in rows]
            if any(status != "BACKUP_CREATED" for status in statuses):
                raise ValueError(f"The backup {self.path} finished with unexpected statuses in different nodes: {rows}")

    def is_done(self, client: Client) -> bool:
        # We query the processes table to check if the backup is in progress,
        # because the backup_log table could not be updated (for example, if the server is restarted)
        rows = client.execute(
            f"""
            SELECT count()
            FROM system.processes
            WHERE query_kind = 'Backup' AND query like '%{self.path}%'
            """
        )

        if len(rows) > 0:
            [[count]] = rows
            return count == 0
        else:
            raise ValueError(f"could not find backup matching {self!r}")

    def wait(self, client: Client) -> None:
        # The query can take a little bit to appear in the system.processes table,
        # so we wait a bit before checking if the backup is done.
        time.sleep(5)

        while not self.is_done(client):
            time.sleep(120)

        self.throw_on_error(client)


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
    shard: int = pydantic.Field(
        default=None,
        description="The shard to backup. If not specified, the backup will be made once.",
    )


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
    base_prefix = f"{config.database}/"
    if config.table:
        base_prefix = f"{base_prefix}{config.table}/"
    if shard:
        base_prefix = f"{base_prefix}{shard}/"

    backups = s3.get_client().list_objects_v2(
        Bucket=settings.CLICKHOUSE_BACKUPS_BUCKET, Prefix=base_prefix, Delimiter="/"
    )

    if "CommonPrefixes" not in backups:
        return None

    latest_backup = sorted(backups["CommonPrefixes"], key=lambda x: x["Prefix"])[-1]["Prefix"]
    return Backup.from_s3_path(latest_backup)


@dagster.op
def run_backup(
    context: dagster.OpExecutionContext,
    config: BackupConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    latest_backup: Optional[Backup],
    shard: Optional[int] = None,
):
    """
    Run the incremental or full backup and wait for it to finish.
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

    if backup.shard:
        # Run the backup on any host in the shard, but launch the wait
        # on all hosts since we don't know which host will be used
        cluster.map_any_host_in_shards({backup.shard: backup.create}).result()
        cluster.map_all_hosts_in_shard(backup.shard, backup.wait).result()
    else:
        cluster.any_host(backup.create).result()
        cluster.map_all_hosts(backup.wait).result()


@dagster.job()
def sharded_backup():
    """
    Backup ClickHouse database / table to S3 using ClickHouse's native backup functionality.
    """

    def run_backup_for_shard(shard: int):
        latest_backup = get_latest_backup(shard)
        run_backup(latest_backup, shard)

    shards: dagster.DynamicOutput = get_shards()
    shards.map(run_backup_for_shard)


@dagster.schedule(
    job=sharded_backup,
    cron_schedule="0 22 * * 5",
)
def full_sharded_backup_schedule():
    """Launch a full backup for sharded tables"""
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    tables = [
        # "sharded_app_metrics",
        # "sharded_app_metrics2",
        # "sharded_events",
        # "sharded_heatmaps",
        # "sharded_ingestion_warnings",
        # "sharded_performance_events",
        # "sharded_raw_sessions",
        # "sharded_session_recording_events",
        # "sharded_session_replay_embeddings",
        # "sharded_session_replay_events",
        # "sharded_session_replay_events_v2_test",
        "sharded_sessions",
    ]

    for table in tables:
        config = BackupConfig(
            database=settings.CLICKHOUSE_DATABASE,
            date=timestamp,
            table=table,
            incremental=False,
        )
        yield dagster.RunRequest(
            run_key=timestamp,
            run_config={
                "ops": {
                    "get_latest_backup": {"config": config.model_dump()},
                    "run_backup": {"config": config.model_dump()},
                }
            },
        )
