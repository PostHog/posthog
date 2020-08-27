from django.test.runner import DiscoverRunner
from infi.clickhouse_orm import Database  # type: ignore

TEST_DB = "test_clickhhouse"


class ClickhouseTestRunner(DiscoverRunner):
    def setup_databases(self, **kwargs):
        Database(TEST_DB).migrate("ee.clickhouse.migrations")
        return super().setup_databases(**kwargs)

    def teardown_databases(self, old_config, **kwargs):
        Database(TEST_DB).drop_database()
        super().teardown_databases(old_config, **kwargs)
