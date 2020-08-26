from ee.clickhouse.client import ch_client
from ee.clickhouse.sql.events import DROP_EVENTS_TABLE_SQL, EVENTS_TABLE_SQL


class ClickhouseTestMixin:
    def tearDown(self):
        ch_client.execute(DROP_EVENTS_TABLE_SQL)
        ch_client.execute(EVENTS_TABLE_SQL)
