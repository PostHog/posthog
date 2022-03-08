import re
from typing import Dict, Set

import structlog
from django.core.management.base import BaseCommand

from ee.clickhouse.client import sync_execute
from ee.clickhouse.sql.schema import CREATE_TABLE_QUERIES, build_query, get_table_name
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE, CLICKHOUSE_REPLICATION, MULTI_TENANCY

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Synchronize schema across clickhouse cluster, creating missing tables on new nodes"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", help="Exits with a non-zero status if schema changes would be required."
        )

    def handle(self, *args, **options):
        if not CLICKHOUSE_REPLICATION or MULTI_TENANCY:
            logger.info("✅ Skipping non-replicated or cloud setup")
            return

        out_of_sync_hosts = self.get_out_of_sync_hosts()

        if len(out_of_sync_hosts) > 0:
            logger.info("Schema out of sync on some clickhouse nodes!", out_of_sync_hosts=out_of_sync_hosts)

            if options["dry_run"]:
                exit(1)

            logger.info("Creating missing tables")
            for query in CREATE_TABLE_QUERIES:
                sync_execute(build_query(query))

        logger.info("✅ All ClickHouse nodes schema in sync")

    def get_out_of_sync_hosts(self):
        table_names = list(map(get_table_name, CREATE_TABLE_QUERIES))
        rows = sync_execute(
            """
            SELECT hostName() as host, groupArray(name)
            FROM clusterAllReplicas(%(cluster)s, system, tables)
            WHERE database = %(database)s
              AND name IN %(table_names)s
            GROUP BY host
        """,
            {
                "cluster": CLICKHOUSE_CLUSTER,
                "database": CLICKHOUSE_DATABASE,
                "table_names": table_names,
                "target_count": len(table_names),
            },
        )

        out_of_sync: Dict[str, Set[str]] = {}
        for host, host_tables in rows:
            missing_tables = set(table_names) - set(host_tables)
            if len(missing_tables) > 0:
                out_of_sync[host] = missing_tables

        return out_of_sync
