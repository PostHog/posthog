from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from clickhouse_driver import Client

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import ClickhouseCluster, get_cluster
from posthog.models.event.sql import (
    EVENTS_JSON_TABLE_MV_SQL,
    KAFKA_EVENTS_NATIVE_JSON_TABLE,
    KAFKA_EVENTS_NATIVE_JSON_TABLE_SQL,
)

EVENTS_JSON_TABLE_MV = "events_json_table_mv"


def _ingestion_node_roles() -> list[NodeRole]:
    # Mirrors run_sql_with_exceptions: hobby/dev topologies have no dedicated ingestion layer,
    # so target every node there; on cloud the events pipeline runs on the ingestion layer.
    if (settings.E2E_TESTING or settings.DEBUG or not settings.CLOUD_DEPLOYMENT) and not settings.MULTINODE_CLICKHOUSE:
        return [NodeRole.ALL]
    return [NodeRole.INGESTION_EVENTS]


class Command(BaseCommand):
    help = (
        "Start or stop the dual-write of the events topic into the native-JSON events table "
        "(sharded_events_json) by creating or dropping its Kafka consumer table and materialized "
        "view. Idempotent. Use --start after enabling CLICKHOUSE_EVENTS_JSON_DUAL_WRITE on an "
        "instance whose ClickHouse migrations ran while it was disabled."
    )

    def add_arguments(self, parser: Any) -> None:
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--start", action="store_true", help="Create the Kafka table and dual-write MV")
        group.add_argument("--stop", action="store_true", help="Drop the dual-write MV and Kafka table")
        group.add_argument("--status", action="store_true", help="Report whether the dual-write objects exist")

    def handle(self, *args: Any, **options: Any) -> None:
        cluster: ClickhouseCluster = get_cluster()
        node_roles = _ingestion_node_roles()

        def run_on_ingestion_nodes(fn: Any) -> dict[Any, Any]:
            return cluster.map_hosts_by_roles(fn, node_roles).result()

        if options["status"]:

            def check(client: Client) -> tuple[bool, bool]:
                def exists(name: str) -> bool:
                    [[count]] = client.execute(
                        "SELECT count() FROM system.tables WHERE database = %(database)s AND name = %(name)s",
                        {"database": settings.CLICKHOUSE_DATABASE, "name": name},
                    )
                    return bool(count)

                return exists(KAFKA_EVENTS_NATIVE_JSON_TABLE), exists(EVENTS_JSON_TABLE_MV)

            for host, (kafka_exists, mv_exists) in run_on_ingestion_nodes(check).items():
                self.stdout.write(f"{host}: kafka_table={kafka_exists} mv={mv_exists}")
            return

        if options["start"]:
            kafka_sql = KAFKA_EVENTS_NATIVE_JSON_TABLE_SQL(on_cluster=False)
            mv_sql = EVENTS_JSON_TABLE_MV_SQL(on_cluster=False)

            def start(client: Client) -> None:
                client.execute(kafka_sql)
                client.execute(mv_sql)

            run_on_ingestion_nodes(start)
            self.stdout.write(self.style.SUCCESS("events_json dual-write started"))
            if not settings.CLICKHOUSE_EVENTS_JSON_DUAL_WRITE:
                self.stdout.write(
                    self.style.WARNING(
                        "CLICKHOUSE_EVENTS_JSON_DUAL_WRITE is not set; set it so future migrations "
                        "and tooling agree that dual-write is enabled."
                    )
                )
            return

        if options["stop"]:

            def stop(client: Client) -> None:
                # Drop the MV first so it stops consuming before the Kafka table disappears.
                client.execute(f"DROP TABLE IF EXISTS {EVENTS_JSON_TABLE_MV}")
                client.execute(f"DROP TABLE IF EXISTS {KAFKA_EVENTS_NATIVE_JSON_TABLE}")

            run_on_ingestion_nodes(stop)
            self.stdout.write(self.style.SUCCESS("events_json dual-write stopped"))
            return

        raise CommandError("one of --start / --stop / --status is required")
