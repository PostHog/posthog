from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Literal, Optional
from clickhouse_driver import Client
import dagster
from django.conf import settings
import pydantic
from posthog.clickhouse.cluster import ClickhouseCluster

from dagster_aws.s3 import S3Resource


@dataclass
class BackupDetails:
    path: str
    incremental: bool
    base_backup: str


class BackupRunner:
    def __init__(self, cluster: ClickhouseCluster, database: str, kind: Literal["full", "incremental"]):
        self.cluster = cluster
        self.database = database
        self.kind = kind

    def query(self, client: Client, shard: int):
        # base_backup = "aa"
        # if self.kind == "full":
        #     base_backup = ""
        # else:
        #     base_backup = "TBD"

        return """
        BACKUP DATABASE %(database)s
        TO S3('https://%(bucket)s.s3.amazonaws.com/%(path)s/%(shard)s')
        FROM %(base_backup)s
        """.format()

    def execute(self, client: Client, shard: int):
        client.execute(self.query(client, shard), settings={"async": True})

    @property
    def path(self):
        return f"{self.database}/{datetime.now().isoformat()}-{self.kind}"

    def run_backup(self):
        self.cluster.map_any_host_in_shards(
            {shard: partial(self.execute, shard=shard) for shard in self.cluster.shards}
        ).result()


class FullBackupRunner(BackupRunner):
    def query(self, client: Client, shard: int):
        return """
        BACKUP DATABASE %(database)s
        TO S3('https://%(bucket)s.s3.amazonaws.com/%(path)s/%(shard)s')
        """.format()


class IncrementalBackupRunner(BackupRunner):
    base_backup: BackupDetails


class BackupDatabaseConfig(dagster.Config):
    incremental: bool = pydantic.Field(
        default=False,
        description="If true, the backup will be incremental. If false, the backup will be full.",
    )


@dagster.op
def get_latest_backup(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    s3: S3Resource,
) -> Optional[BackupDetails]:
    backups = s3.get_client().list_objects_v2(
        Bucket=settings.CLICKHOUSE_BACKUPS_BUCKET, Prefix="posthog/", Delimiter="/"
    )
    latest_backup = backups["CommonPrefixes"][-1] if "CommonPrefixes" in backups else None

    return (
        BackupDetails(
            path=latest_backup["Prefix"],
            incremental=False,
            base_backup=None,
        )
        if latest_backup
        else None
    )


@dagster.op
def run_backup(
    context: dagster.OpExecutionContext,
    config: BackupDatabaseConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    s3: S3Resource,
    latest_backup: Optional[BackupDetails],
):
    """
    Backup ClickHouse database to S3 using ClickHouse's native backup functionality.
    """
    backup_runner = (
        IncrementalBackupRunner(cluster, settings.CLICKHOUSE_DATABASE)
        if config.incremental
        else FullBackupRunner(cluster, settings.CLICKHOUSE_DATABASE)
    )
    backup_runner.run_backup()


# def run_incremental_backup(
#     context: dagster.OpExecutionContext,
#     s3_client: S3Client = s3.get_client()

#     def get_latest_run_backup():
#         objects = s3_client.list_objects_v2(
#             Bucket=settings.CLICKHOUSE_BACKUPS_BUCKET,
#             Prefix="posthog",
#         )

#         return objects

#     latest_backup = get_latest_run_backup()

#     # results = cluster.map_all_hosts(generate_export_query).result()

#     # Log the results
#     # for host, result in results.items():
#     #     context.log.info(f"Export completed on host {host}: {result}")

#     context.log.info(f"Query logs export completed successfully on all hosts")


@dagster.job
def backup_database():
    get_latest_backup()
    # run_backup(latest_backup)
