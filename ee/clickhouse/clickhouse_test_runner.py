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
    def setup_databases(self, **kwargs):
        Database(
            CLICKHOUSE_DATABASE,
            db_url=CLICKHOUSE_HTTP_URL,
            username=CLICKHOUSE_USERNAME,
            password=CLICKHOUSE_PASSWORD,
            verify_ssl_cert=CLICKHOUSE_VERIFY,
        ).migrate("ee.clickhouse.migrations")
        return super().setup_databases(**kwargs)

    def teardown_databases(self, old_config, **kwargs):
        Database(
            CLICKHOUSE_DATABASE,
            db_url=CLICKHOUSE_HTTP_URL,
            username=CLICKHOUSE_USERNAME,
            password=CLICKHOUSE_PASSWORD,
            verify_ssl_cert=CLICKHOUSE_VERIFY,
        ).drop_database()
        super().teardown_databases(old_config, **kwargs)
