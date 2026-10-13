from django.core.management.base import BaseCommand
from django.test.runner import DiscoverRunner as TestRunner

from posthog.clickhouse.managed_schema import ClickHouseDatabase
from posthog.settings import TEST


class Command(BaseCommand):
    help = "Set up databases for non-Python tests that depend on the Django server"

    # has optional arg to only run postgres setup
    def add_arguments(self, parser):
        parser.add_argument(
            "--only-postgres", action="store_true", help="Only set up the Postgres database", default=False
        )
        parser.add_argument(
            "--only-clickhouse", action="store_true", help="Only set up the ClickHouse database", default=False
        )

    def handle(self, *args, **options):
        if not TEST:
            raise ValueError("TEST environment variable needs to be set for this command to function")

        if not options["only_clickhouse"]:
            disable_migrations()

            test_runner = TestRunner(interactive=False)
            test_runner.setup_databases()
            test_runner.setup_test_environment()

        if options["only_postgres"]:
            print("Only setting up Postgres database")  # noqa: T201
            return

        print("\nCreating test ClickHouse database...")  # noqa: T201
        database = ClickHouseDatabase()
        database.drop()
        database.create()
        database.apply_schema(kafka=True)
        database.seed()


def disable_migrations() -> None:
    """
    Disables django migrations when creating test database. Model definitions are used instead.

    Speeds up setup significantly.
    """
    from django.conf import settings
    from django.core.management.commands import migrate as django_migrate

    from posthog.management.commands import migrate as posthog_migrate

    class DisableMigrations:
        def __contains__(self, item: str) -> bool:
            return True

        def __getitem__(self, item: str) -> None:
            return None

    class MigrateSilentCommand(posthog_migrate.Command):
        def handle(self, *args, **kwargs):
            from django.db import connection

            # :TRICKY: Create extension and function depended on by models.
            with connection.cursor() as cursor:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
                cursor.execute("CREATE EXTENSION IF NOT EXISTS ltree")

            return super().handle(*args, **kwargs)

    settings.MIGRATION_MODULES = DisableMigrations()
    django_migrate.Command = MigrateSilentCommand  # type: ignore
    posthog_migrate.Command = MigrateSilentCommand  # type: ignore
