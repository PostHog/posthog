from django.core.management.base import BaseCommand
from django.test.runner import DiscoverRunner as TestRunner
from infi.clickhouse_orm import Database

from posthog.clickhouse.schema import (
    CREATE_DISTRIBUTED_TABLE_QUERIES,
    CREATE_KAFKA_TABLE_QUERIES,
    CREATE_MERGETREE_TABLE_QUERIES,
    CREATE_MV_TABLE_QUERIES,
    build_query,
)
from posthog.settings import (
    CLICKHOUSE_CLUSTER,
    CLICKHOUSE_DATABASE,
    CLICKHOUSE_HTTP_URL,
    CLICKHOUSE_PASSWORD,
    CLICKHOUSE_USER,
    CLICKHOUSE_VERIFY,
    TEST,
)


class Command(BaseCommand):
    help = "Set up databases for non-Python tests that depend on the Django server"

    def handle(self, *args, **options):
        if not TEST:
            raise ValueError("TEST environment variable needs to be set for this command to function")

        test_runner = TestRunner(interactive=False)
        disable_migrations()
        test_runner.setup_databases()
        test_runner.setup_test_environment()

        print("\nCreating test ClickHouse database...")  # noqa: T001
        database = Database(
            CLICKHOUSE_DATABASE,
            db_url=CLICKHOUSE_HTTP_URL,
            username=CLICKHOUSE_USER,
            password=CLICKHOUSE_PASSWORD,
            cluster=CLICKHOUSE_CLUSTER,
            verify_ssl_cert=CLICKHOUSE_VERIFY,
            autocreate=False,
        )
        if database.db_exists:
            print(  # noqa: T001
                f'Got an error creating the test ClickHouse database: database "{CLICKHOUSE_DATABASE}" already exists\n'
            )
            print("Destroying old test ClickHouse database...")  # noqa: T001
            database.drop_database()
        database.create_database()
        create_clickhouse_schema_in_parallel(CREATE_MERGETREE_TABLE_QUERIES + CREATE_KAFKA_TABLE_QUERIES)
        create_clickhouse_schema_in_parallel(CREATE_DISTRIBUTED_TABLE_QUERIES)
        create_clickhouse_schema_in_parallel(CREATE_MV_TABLE_QUERIES)


def create_clickhouse_schema_in_parallel(queries):
    from posthog.test.base import run_clickhouse_statement_in_parallel

    queries = list(map(build_query, queries))
    run_clickhouse_statement_in_parallel(queries)


def disable_migrations() -> None:
    """
    Disables django migrations when creating test database. Model definitions are used instead.

    Speeds up setup significantly.
    """
    from django.conf import settings
    from django.core.management.commands import migrate

    class DisableMigrations:
        def __contains__(self, item: str) -> bool:
            return True

        def __getitem__(self, item: str) -> None:
            return None

    class MigrateSilentCommand(migrate.Command):
        def handle(self, *args, **kwargs):
            from django.db import connection

            # :TRICKY: Create extension depended on by models.
            with connection.cursor() as cursor:
                cursor.execute("CREATE EXTENSION pg_trgm")

            return super().handle(*args, **kwargs)

    settings.MIGRATION_MODULES = DisableMigrations()
    migrate.Command = MigrateSilentCommand  # type: ignore
