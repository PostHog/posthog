from django.core.management.base import BaseCommand

from ee.clickhouse.clickhouse_test_runner import ClickhouseTestRunner


class Command(BaseCommand):
    help = "Tear down ClickHouse after non-Python tests"

    def handle(self, *args, **options):
        ClickhouseTestRunner(interactive=False).teardown_databases(old_config=[])
