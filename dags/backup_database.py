from dataclasses import dataclass
from datetime import datetime, UTC
from functools import partial
from typing import Optional
from clickhouse_driver import Client
import dagster
from django.conf import settings
import pydantic
from posthog.clickhouse.cluster import ClickhouseCluster

from dagster_aws.s3 import S3Resource


@dataclass
class Backup:
    # _id: str
    database: str
    date: datetime
    base_backup: "Backup"

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
        BACKUP DATABASE {database}
        TO S3('https://{bucket}.s3.amazonaws.com/{path}/{shard}')
        """.format(
            database=self.database,
            bucket=settings.CLICKHOUSE_BACKUPS_BUCKET,
            path=self.path,
            shard=shard,
        )

        client.execute(query, settings=backup_settings)


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
        Bucket=settings.CLICKHOUSE_BACKUPS_BUCKET, Prefix="posthog/", Delimiter="/"
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
        database=settings.CLICKHOUSE_DATABASE,
        date=datetime.now(UTC),
        base_backup=latest_backup,
    )

    cluster.map_any_host_in_shards({shard: partial(backup.create, shard=shard) for shard in cluster.shards}).result()


@dagster.job
def backup_database():
    latest_backup = get_latest_backup()
    run_backup(latest_backup)
