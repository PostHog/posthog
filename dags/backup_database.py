from dataclasses import dataclass
from datetime import datetime, UTC
from functools import partial
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
    date: datetime
    table: Optional[str] = None
    id: Optional[str] = None
    base_backup: Optional["Backup"] = None

    @property
    def path(self):
        base_path = f"{self.database}/{self.date.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        if self.table:
            base_path = f"{base_path}/{self.table}"

        return base_path

    def create(self, client: Client, shard: int):
        backup_settings = {
            "async": "1",
        }
        if self.base_backup:
            backup_settings["base_backup"] = "S3('https://{bucket}.s3.amazonaws.com/{path}/{shard}')".format(
                bucket=settings.CLICKHOUSE_BACKUPS_BUCKET,
                path=self.base_backup.path,
                shard=shard,
            )

        query = """
        BACKUP {object} {name}
        TO S3('https://{bucket}.s3.amazonaws.com/{path}/{shard}')
        SETTINGS {settings}
        """.format(
            bucket=settings.CLICKHOUSE_BACKUPS_BUCKET,
            path=self.path,
            shard=shard,
            object="TABLE" if self.table else "DATABASE",
            name=self.table if self.table else self.database,
            settings=", ".join([f"{k} = {v}" for k, v in backup_settings.items()]),
        )

        client.execute(query, query_id=f"{self.id}-{shard}")

    def throw_on_error(self, client: Client) -> bool:
        rows = client.execute(
            f"""
            SELECT hostname(), argMax(status, event_time_microseconds), argMax(left(error, 100), event_time_microseconds)
            FROM clusterAllReplicas(posthog, system.backup_log)
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
            FROM clusterAllReplicas(posthog, system.processes)
            WHERE query_kind = 'Backup' AND query like '%{self.path}%'
            """
        )

        if len(rows) > 0:
            [[count]] = rows
            if count > 0:
                return False
            else:
                self.throw_on_error(client)
        else:
            raise ValueError(f"could not find backup matching {self!r}")

    def wait(self, client: Client) -> None:
        while not self.is_done(client):
            time.sleep(60.0 * 2)


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


@dagster.op
def get_latest_backup(
    s3: S3Resource,
) -> Optional[Backup]:
    backups = s3.get_client().list_objects_v2(
        Bucket=settings.CLICKHOUSE_BACKUPS_BUCKET, Prefix=f"{settings.CLICKHOUSE_DATABASE}/", Delimiter="/"
    )

    if "CommonPrefixes" not in backups:
        return None

    latest_backup = backups["CommonPrefixes"][-1]
    (database, date, _) = latest_backup["Prefix"].split("/")

    return Backup(
        database=database,
        date=datetime.strptime(date, "%Y-%m-%dT%H:%M:%SZ"),
        base_backup=None,
    )


@dagster.op
def run_backup(
    context: dagster.OpExecutionContext,
    config: BackupConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    latest_backup: Optional[Backup],
):
    """
    Backup ClickHouse database / table to S3 using ClickHouse's native backup functionality.
    """
    if config.incremental:
        if not latest_backup:
            raise ValueError("Latest backup not found and incremental backup requested")

    backup = Backup(
        id=context.run_id,
        database=config.database,
        table=config.table,
        date=datetime.now(UTC),
        base_backup=latest_backup if config.incremental else None,
    )

    cluster.map_any_host_in_shards({shard: partial(backup.create, shard=shard) for shard in cluster.shards}).result()

    cluster.any_host(backup.wait).result()


@dagster.job
def backup_database():
    latest_backup = get_latest_backup()
    run_backup(latest_backup)
