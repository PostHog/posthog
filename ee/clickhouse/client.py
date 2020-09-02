from clickhouse_driver import Client  # type: ignore

from posthog.settings import (
    CLICKHOUSE_CA,
    CLICKHOUSE_DATABASE,
    CLICKHOUSE_HOST,
    CLICKHOUSE_PASSWORD,
    CLICKHOUSE_SECURE,
    CLICKHOUSE_VERIFY,
)

# Reconnect scoped to the database provided for security
ch_client = Client(
    host=CLICKHOUSE_HOST,
    database=CLICKHOUSE_DATABASE,
    secure=CLICKHOUSE_SECURE,
    password=CLICKHOUSE_PASSWORD,
    ca_certs=CLICKHOUSE_CA,
    verify=CLICKHOUSE_VERIFY,
)
