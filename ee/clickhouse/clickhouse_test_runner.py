from django.test.runner import DiscoverRunner
from infi.clickhouse_orm import Database


class ClickhouseTestRunner(DiscoverRunner):
    def setup_databases(self, **kwargs):
        Database("ch_test").migrate("ee.clickhouse.migrations")

    def teardown_databases(self, old_config, **kwargs):
        Database("ch_test").drop_database()
