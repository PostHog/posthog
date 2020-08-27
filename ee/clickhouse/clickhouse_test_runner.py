from django.test.runner import DiscoverRunner
from infi.clickhouse_orm import Database  # type: ignore

TEST_DB = "ch_test"


class ClickhouseTestRunner(DiscoverRunner):
    def setup_databases(self, **kwargs):
        super().setup_databases(**kwargs)
        Database(TEST_DB).migrate("ee.clickhouse.migrations")

    def teardown_databases(self, old_config, **kwargs):
        super().teardown_databases(old_config, **kwargs)
        Database(TEST_DB).drop_database()
