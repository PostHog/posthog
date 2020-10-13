import asyncio

from aioch import Client  # type: ignore
from asgiref.sync import async_to_sync  # type: ignore
from clickhouse_driver import Client as SyncClient
from clickhouse_pool import ChPool  # type: ignore

from posthog.settings import (
    CLICKHOUSE,
    CLICKHOUSE_ASYNC,
    CLICKHOUSE_CA,
    CLICKHOUSE_DATABASE,
    CLICKHOUSE_HOST,
    CLICKHOUSE_PASSWORD,
    CLICKHOUSE_SECURE,
    CLICKHOUSE_VERIFY,
    PRIMARY_DB,
    TEST,
)

if PRIMARY_DB != CLICKHOUSE:
    ch_client = None  # type: Client
    ch_sync_pool = None  # type: ChPool

    def async_execute(query, args=None):
        return

    def sync_execute(query, args=None):
        return


else:
    if not TEST and CLICKHOUSE_ASYNC:
        ch_client = Client(
            host=CLICKHOUSE_HOST,
            database=CLICKHOUSE_DATABASE,
            secure=CLICKHOUSE_SECURE,
            password=CLICKHOUSE_PASSWORD,
            ca_certs=CLICKHOUSE_CA,
            verify=CLICKHOUSE_VERIFY,
        )

        @async_to_sync
        async def async_execute(query, args=None):
            loop = asyncio.get_event_loop()
            task = loop.create_task(ch_client.execute(query, args))
            return task

    else:
        # if this is a test use the sync client
        ch_client = SyncClient(
            host=CLICKHOUSE_HOST,
            database=CLICKHOUSE_DATABASE,
            secure=CLICKHOUSE_SECURE,
            password=CLICKHOUSE_PASSWORD,
            ca_certs=CLICKHOUSE_CA,
            verify=CLICKHOUSE_VERIFY,
        )

        def async_execute(query, args=None):
            return sync_execute(query, args)

    ch_sync_pool = ChPool(
        host=CLICKHOUSE_HOST,
        database=CLICKHOUSE_DATABASE,
        secure=CLICKHOUSE_SECURE,
        password=CLICKHOUSE_PASSWORD,
        ca_certs=CLICKHOUSE_CA,
        verify=CLICKHOUSE_VERIFY,
        connections_min=20,
        connections_max=100,
    )

    def sync_execute(query, args=None):
        with ch_sync_pool.get_client() as client:
            result = client.execute(query, args)
        return result
