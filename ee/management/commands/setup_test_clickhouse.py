from django.core.management.base import BaseCommand

from ee.clickhouse.clickhouse_test_runner import ClickhouseTestRunner


class Command(BaseCommand):
    help = "Set up ClickHouse for non-Python tests"

    def handle(self, *args, **options):
        ClickhouseTestRunner(interactive=False).setup_databases()
