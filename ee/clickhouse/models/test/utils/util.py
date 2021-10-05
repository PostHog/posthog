from time import sleep

from ee.clickhouse.client import sync_execute


# this normally is unnecessary as CH is fast to consume from Kafka when testing
# but it helps prevent potential flakiness
def delay_until_clickhouse_consumes_from_kafka(table_name: str, target_row_count: int) -> None:
    # max = 10 seconds
    for i in range(20):
        result = sync_execute(f"SELECT COUNT(1) FROM {table_name}")
        if result[0][0] == target_row_count:
            return
        sleep(0.5)
