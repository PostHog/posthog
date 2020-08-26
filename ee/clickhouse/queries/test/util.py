from ee.clickhouse.client import ch_client
from ee.clickhouse.sql.events import EVENT_SQL


class ClickhouseTestMixin:
    def tearDown(self):
        ch_client.execute("DROP TABLE events")
        ch_client.execute(EVENT_SQL)
