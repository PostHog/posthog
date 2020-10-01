from django.test.runner import DiscoverRunner
from infi.clickhouse_orm import Database  # type: ignore

from posthog.settings import (
    CLICKHOUSE_DATABASE,
    CLICKHOUSE_HTTP_URL,
    CLICKHOUSE_PASSWORD,
    CLICKHOUSE_USERNAME,
    CLICKHOUSE_VERIFY,
)


class ClickhouseTestRunner(DiscoverRunner):
    def get_database(self) -> Database:
        return Database(
            CLICKHOUSE_DATABASE,
            db_url=CLICKHOUSE_HTTP_URL,
            username=CLICKHOUSE_USERNAME,
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
        return super().setup_databases(**kwargs)

    def teardown_databases(self, old_config, **kwargs):
        try:
            self.get_database().drop_database()
        except:
            pass
        super().teardown_databases(old_config, **kwargs)
