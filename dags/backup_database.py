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
    id: Optional[str] = None
    base_backup: Optional["Backup"] = None

    @property
    def path(self):
        return f"{self.database}/{self.date.strftime('%Y-%m-%dT%H:%M:%SZ')}"

    def create(self, client: Client, shard: int):
        backup_settings = {
            "async": True,
        }
        if self.base_backup:
            backup_settings["base_backup"] = self.base_backup.path

        query = """
        BACKUP TABLE groups
        TO S3('https://{bucket}.s3.amazonaws.com/{path}/{shard}')
        """.format(
            bucket=settings.CLICKHOUSE_BACKUPS_BUCKET,
            path=self.path,
            shard=shard,
        )

        client.execute(query, settings=backup_settings, query_id=f"{self.id}-{shard}")

    def is_done(self, client: Client) -> bool:
        rows = client.execute(
            f"""
            SELECT hostname(), argMax(status, event_time_microseconds)
            FROM clusterAllReplicas(posthog, system.backup_log)
            WHERE (start_time >= (now() - toIntervalDay(7))) AND query_id LIKE '{self.id}%'
            GROUP BY hostname()
            """
        )

        if len(rows) > 0:
            statuses = [status for _, status in rows]
            if any(status == "CREATING_BACKUP" for status in statuses):
                return False
            elif all(status == "BACKUP_CREATED" for status in statuses):
                return True
            else:
                raise ValueError(f"The backup {self.id} finished with unexpected statuses in different nodes: {rows}")
        else:
            raise ValueError(f"could not find backup matching {self!r}")

    def wait(self, client: Client) -> None:
        while not self.is_done(client):
            time.sleep(60.0 * 5)


class BackupDatabaseConfig(dagster.Config):
    incremental: bool = pydantic.Field(
        default=False,
        description="If true, the backup will be incremental. If false, the backup will be full.",
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
    config: BackupDatabaseConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    latest_backup: Optional[Backup],
):
    """
    Backup ClickHouse database to S3 using ClickHouse's native backup functionality.
    """
    if config.incremental:
        if not latest_backup:
            raise ValueError("Latest backup not found and incremental backup requested")
        context.log.info("Running an incremental backup using base backup %s", latest_backup.path)
    else:
        context.log.info("Running a full backup")
        latest_backup = None

    backup = Backup(
        id=context.run_id,
        database=settings.CLICKHOUSE_DATABASE,
        date=datetime.now(UTC),
        base_backup=latest_backup,
    )

    cluster.map_any_host_in_shards({shard: partial(backup.create, shard=shard) for shard in cluster.shards}).result()

    cluster.any_host(backup.wait).result()


@dagster.job
def backup_database():
    latest_backup = get_latest_backup()
    run_backup(latest_backup)
