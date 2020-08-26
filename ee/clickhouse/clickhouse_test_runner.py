from django.test.runner import DiscoverRunner
from infi.clickhouse_orm import Database

TEST_DB = "ch_test"


class ClickhouseTestRunner(DiscoverRunner):
    def setup_databases(self, **kwargs):
        Database(TEST_DB).migrate("ee.clickhouse.migrations")

    def teardown_databases(self, old_config, **kwargs):
        Database(TEST_DB).drop_database()
