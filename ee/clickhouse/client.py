from clickhouse_driver import Client  # type: ignore

from posthog.settings import (
    CLICKHOUSE_CA,
    CLICKHOUSE_DATABASE,
    CLICKHOUSE_HOST,
    CLICKHOUSE_PASSWORD,
    CLICKHOUSE_SECURE,
    CLICKHOUSE_VERIFY,
)

# Bootstrap ClickHouse with Database
ch_client = Client(
    host=CLICKHOUSE_HOST,
    secure=CLICKHOUSE_SECURE,
    password=CLICKHOUSE_PASSWORD,
    ca_certs=CLICKHOUSE_CA,
    verify=CLICKHOUSE_VERIFY,
)

# We have to do this because if the database doesn't exist no clickhouse commands will function correctly
ch_client.execute("CREATE DATABASE IF NOT EXISTS {database}".format(database=CLICKHOUSE_DATABASE))

# Reconnect scoped to the database provided for security
ch_client = Client(
    host=CLICKHOUSE_HOST,
    database=CLICKHOUSE_DATABASE,
    secure=CLICKHOUSE_SECURE,
    password=CLICKHOUSE_PASSWORD,
    ca_certs=CLICKHOUSE_CA,
    verify=CLICKHOUSE_VERIFY,
)
