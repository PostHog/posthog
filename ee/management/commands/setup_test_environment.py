from django.core.management.base import BaseCommand

from posthog.ee import is_ee_enabled


class Command(BaseCommand):
    help = "Set up databases for non-Python tests that depend on the Django server"

    def handle(self, *args, **options):
        from django.test.runner import DiscoverRunner as TestRunner

        test_runner = TestRunner(interactive=False)
        test_runner.setup_databases()
        test_runner.setup_test_environment()

        if is_ee_enabled():
            from infi.clickhouse_orm import Database  # type: ignore

            from posthog.settings import (
                CLICKHOUSE_DATABASE,
                CLICKHOUSE_HTTP_URL,
                CLICKHOUSE_PASSWORD,
                CLICKHOUSE_USER,
                CLICKHOUSE_VERIFY,
            )

            database = Database(
                CLICKHOUSE_DATABASE,
                db_url=CLICKHOUSE_HTTP_URL,
                username=CLICKHOUSE_USER,
                password=CLICKHOUSE_PASSWORD,
                verify_ssl_cert=CLICKHOUSE_VERIFY,
            )

            try:
                database.create_database()
            except:
                pass
            database.migrate("ee.clickhouse.migrations")
