from django.test.runner import DiscoverRunner
from infi.clickhouse_orm import Database

from ee.clickhouse.client import sync_execute
from posthog.settings import (
    CLICKHOUSE_DATABASE,
    CLICKHOUSE_HTTP_URL,
    CLICKHOUSE_PASSWORD,
    CLICKHOUSE_USER,
    CLICKHOUSE_VERIFY,
)


class ClickhouseTestRunner(DiscoverRunner):
    def get_database(self) -> Database:
        return Database(
            CLICKHOUSE_DATABASE,
            db_url=CLICKHOUSE_HTTP_URL,
            username=CLICKHOUSE_USER,
            password=CLICKHOUSE_PASSWORD,
            verify_ssl_cert=CLICKHOUSE_VERIFY,
        )

    def setup_databases(self, **kwargs):
        database = self.get_database()
        try:
            database.drop_database()
        except:
            pass
        database.create_database()
        database.migrate("ee.clickhouse.migrations")
        # Make DELETE / UPDATE synchronous to avoid flaky tests
        sync_execute("SET mutations_sync = 1")
        return super().setup_databases(**kwargs)

    def teardown_databases(self, old_config, **kwargs):
        try:
            self.get_database().drop_database()
        except:
            pass
        super().teardown_databases(old_config, **kwargs)
