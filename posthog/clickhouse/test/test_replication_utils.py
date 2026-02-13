from django.conf import settings

from clickhouse_driver import Client as SyncClient

REPLICA_SECONDARY_HOST = "localhost"
REPLICA_SECONDARY_NATIVE_PORT = 9001


def make_client(host: str, port: int, database: str = "system") -> SyncClient:
    return SyncClient(
        host=host,
        port=port,
        database=database,
        secure=settings.CLICKHOUSE_SECURE,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        ca_certs=settings.CLICKHOUSE_CA,
        verify=settings.CLICKHOUSE_VERIFY,
        settings={"mutations_sync": "1"} if settings.TEST else {},
    )


def stop_replication(client: SyncClient, table: str) -> None:
    client.execute(f"SYSTEM STOP FETCHES {table}")


def start_replication(client: SyncClient, table: str) -> None:
    client.execute(f"SYSTEM START FETCHES {table}")
