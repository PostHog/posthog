import asyncio

from aioch import Client  # type: ignore
from asgiref.sync import async_to_sync
from clickhouse_driver import Client as SyncClient

from posthog.settings import (
    CLICKHOUSE,
    CLICKHOUSE_CA,
    CLICKHOUSE_DATABASE,
    CLICKHOUSE_HOST,
    CLICKHOUSE_PASSWORD,
    CLICKHOUSE_SECURE,
    CLICKHOUSE_VERIFY,
    PRIMARY_DB,
    TEST,
)

if not TEST:
    if PRIMARY_DB != CLICKHOUSE:
        ch_client = Client(host="localhost")
    else:
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
        task = asyncio.create_task(ch_client.execute(query, args))
        # we return this in case we want to cancel it
        return task


else:
    # if this is a test use the sync client
    if PRIMARY_DB != CLICKHOUSE:
        ch_client = SyncClient(host="localhost")
    else:
        ch_client = SyncClient(
            host=CLICKHOUSE_HOST,
            database=CLICKHOUSE_DATABASE,
            secure=CLICKHOUSE_SECURE,
            password=CLICKHOUSE_PASSWORD,
            ca_certs=CLICKHOUSE_CA,
            verify=CLICKHOUSE_VERIFY,
        )

    def async_execute(query, args=None):
        task = ch_client.execute(query, args)
        return task


if PRIMARY_DB != CLICKHOUSE:
    ch_sync_client = SyncClient(host="localhost")
else:
    ch_sync_client = SyncClient(
        host=CLICKHOUSE_HOST,
        database=CLICKHOUSE_DATABASE,
        secure=CLICKHOUSE_SECURE,
        password=CLICKHOUSE_PASSWORD,
        ca_certs=CLICKHOUSE_CA,
        verify=CLICKHOUSE_VERIFY,
    )


def sync_execute(query, args=None):
    return ch_sync_client.execute(query, args)
