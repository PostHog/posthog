import logging
import re
from collections import defaultdict
from typing import Dict, Set

import structlog
from django.conf import settings
from django.core.management.base import BaseCommand

from posthog.clickhouse.schema import CREATE_TABLE_QUERIES, get_table_name
from posthog.client import sync_execute
from posthog.cloud_utils import is_cloud

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)

TableName = str
Query = str
HostName = str

# These tables are deprecated and should no longer be synchronised.
# They are kept here since the migration operations fail as we create and then drop them.
# TODO: Remove these tables from the CREATE_TABLE_QUERIES list
# That will require the original migrations being converted to no-ops so that these tables are not added
# when migrating from scratch
synchronization_ignore_list = (
    [
        "kafka_session_recording_events_partition_statistics",
        "session_recording_events",
        "kafka_session_recording_events",
        "session_recording_events_mv",
        "session_recording_events_partition_statistics_mv",
        "sharded_session_recording_events",
        "writable_session_recording_events",
    ]
    if is_cloud() or settings.DEBUG or settings.TEST or settings.E2E_TESTING
    else []
)


class Command(BaseCommand):
    help = "Synchronize schema across clickhouse cluster, creating missing tables on new nodes"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", help="Exits with a non-zero status if schema changes would be required."
        )

    def handle(self, *args, **options):
        if is_cloud():
            logger.info("✅ Skipping sync_replicated_schema because is_cloud=true")
            return

        _, create_table_queries, out_of_sync_hosts = self.analyze_cluster_tables()

        if len(out_of_sync_hosts) > 0:
            logger.info("Schema out of sync on some clickhouse nodes!", out_of_sync_hosts=out_of_sync_hosts)

            if options.get("dry_run"):
                exit(1)
            else:
                self.create_missing_tables(out_of_sync_hosts, create_table_queries)

        logger.info("✅ All ClickHouse nodes schema in sync")

    def analyze_cluster_tables(self):
        table_names = [
            x for x in list(map(get_table_name, CREATE_TABLE_QUERIES)) if x not in synchronization_ignore_list
        ]

        rows = sync_execute(
            """
            SELECT hostName() as host, name, create_table_query
            FROM clusterAllReplicas(%(cluster)s, system, tables)
            WHERE database = %(database)s
              AND name IN %(table_names)s
        """,
            {
                "cluster": settings.CLICKHOUSE_CLUSTER,
                "database": settings.CLICKHOUSE_DATABASE,
                "table_names": table_names,
            },
        )

        host_tables: Dict[HostName, Set[TableName]] = defaultdict(set)
        create_table_queries: Dict[TableName, Query] = {}

        for host, table_name, create_table_query in rows:
            host_tables[host].add(table_name)
            create_table_queries[table_name] = create_table_query

        return host_tables, create_table_queries, self.get_out_of_sync_hosts(host_tables)

    def get_out_of_sync_hosts(self, host_tables: Dict[HostName, Set[TableName]]) -> Dict[HostName, Set[TableName]]:
        table_names = [
            x for x in list(map(get_table_name, CREATE_TABLE_QUERIES)) if x not in synchronization_ignore_list
        ]

        out_of_sync = {}

        for host, tables in host_tables.items():
            missing_tables = set(table_names) - tables
            if len(missing_tables) > 0:
                out_of_sync[host] = missing_tables

        return out_of_sync

    def create_missing_tables(
        self, out_of_sync_hosts: Dict[HostName, Set[TableName]], create_table_queries: Dict[TableName, Query]
    ):
        missing_tables = set(table for tables in out_of_sync_hosts.values() for table in tables)

        logger.info("Creating missing tables", missing_tables=missing_tables)
        for table in missing_tables:
            query = create_table_queries[table]
            sync_execute(self.run_on_cluster(query))

    def run_on_cluster(self, create_table_query: Query) -> Query:
        return re.sub(
            r"^CREATE TABLE (\S+)",
            f"CREATE TABLE IF NOT EXISTS \\1 ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'",
            create_table_query,
            1,
        )
