from django.core.management.base import BaseCommand

from ee.clickhouse.clickhouse_test_runner import ClickhouseTestRunner


class Command(BaseCommand):
    help = "Set up ClickHouse for non-Python tests"

    def handle(self, *args, **options):
        test_runner = ClickhouseTestRunner(interactive=False)
        test_runner.setup_databases()
        test_runner.setup_test_environment()
