from clickhouse_driver import Client as SyncClient
from clickhouse_pool import ChPool

from posthog.settings import (
    CLICKHOUSE_CA,
    CLICKHOUSE_CONN_POOL_MAX,
    CLICKHOUSE_CONN_POOL_MIN,
    CLICKHOUSE_DATABASE,
    CLICKHOUSE_HOST,
    CLICKHOUSE_PASSWORD,
    CLICKHOUSE_SECURE,
    CLICKHOUSE_USER,
    CLICKHOUSE_VERIFY,
    TEST,
)


def default_client():
    """
    Return a bare bones client for use in places where we are only interested in general ClickHouse state
    DO NOT USE THIS FOR QUERYING DATA
    """
    return SyncClient(
        host=CLICKHOUSE_HOST,
        # We set "system" here as we don't necessarily have a "default" database,
        # which is what the clickhouse_driver would use by default. We are
        # assuming that this exists and we have permissions to access it. This
        # feels like a reasonably safe assumption as e.g. we already reference
        # `system.numbers` in multiple places within queries. We also assume
        # access to various other tables e.g. to handle async migrations.
        database="system",
        secure=CLICKHOUSE_SECURE,
        user=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
        ca_certs=CLICKHOUSE_CA,
        verify=CLICKHOUSE_VERIFY,
    )


def make_ch_pool(**overrides) -> ChPool:
    kwargs = {
        "host": CLICKHOUSE_HOST,
        "database": CLICKHOUSE_DATABASE,
        "secure": CLICKHOUSE_SECURE,
        "user": CLICKHOUSE_USER,
        "password": CLICKHOUSE_PASSWORD,
        "ca_certs": CLICKHOUSE_CA,
        "verify": CLICKHOUSE_VERIFY,
        "connections_min": CLICKHOUSE_CONN_POOL_MIN,
        "connections_max": CLICKHOUSE_CONN_POOL_MAX,
        "settings": {"mutations_sync": "1"} if TEST else {},
        # Without this, OPTIMIZE table and other queries will regularly run into timeouts
        "send_receive_timeout": 30 if TEST else 999_999_999,
        **overrides,
    }

    return ChPool(**kwargs)


ch_pool = make_ch_pool()
