from ee.clickhouse.client import ch_client
from ee.clickhouse.sql.clickhouse import GENERATE_UUID_SQL


def generate_clickhouse_uuid() -> str:
    response = ch_client.execute(GENERATE_UUID_SQL)
    return response[0][0]
