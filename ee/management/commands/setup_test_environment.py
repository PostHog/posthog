from django.core.management.base import BaseCommand

from posthog.ee import is_ee_enabled


class Command(BaseCommand):
    help = "Set up databases for non-Python tests that depend on the Django server"

    def handle(self, *args, **options):
        if is_ee_enabled():
            from ee.clickhouse.clickhouse_test_runner import ClickhouseTestRunner as TestRunner
        else:
            from django.test.runner import DiscoverRunner as TestRunner
        test_runner = TestRunner(interactive=False)
        test_runner.setup_databases()
        test_runner.setup_test_environment()
