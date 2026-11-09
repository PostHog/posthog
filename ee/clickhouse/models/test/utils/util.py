import time

from posthog.clickhouse.client import sync_execute


# this normally is unnecessary as CH is fast to consume from Kafka when testing
# but it helps prevent potential flakiness
def delay_until_clickhouse_consumes_from_kafka(table_name: str, target_row_count: int, timeout_seconds=10) -> None:
    ts_start = time.time()
    while time.time() < ts_start + timeout_seconds:
        result = sync_execute(f"SELECT COUNT(1) FROM {table_name}")
        if result[0][0] == target_row_count:
            return
        time.sleep(0.5)  # noqa: TID251  # Kafka consumption is observed through ClickHouse queries.
