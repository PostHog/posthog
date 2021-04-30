import datetime

from django.core.management.base import BaseCommand
from infi.clickhouse_orm import Database  # type: ignore
from infi.clickhouse_orm.migrations import MigrationHistory  # type: ignore
from infi.clickhouse_orm.utils import import_submodules  # type: ignore

from posthog.settings import CLICKHOUSE_DATABASE, CLICKHOUSE_HTTP_URL, CLICKHOUSE_PASSWORD, CLICKHOUSE_USER

MIGRATIONS_PACKAGE_NAME = "ee.clickhouse.migrations"


class Command(BaseCommand):
    help = "Migrate clickhouse"

    def add_arguments(self, parser):
        parser.add_argument(
            "--upto", default=99_999, type=int, help="Database state will be brought to the state after that migration."
        )
        parser.add_argument("--fake", action="store_true", help="Mark migrations as run without actually running them.")
        parser.add_argument(
            "--plan", action="store_true", help="Shows a list of the migration actions that will be performed."
        )

    def handle(self, *args, **options):
        database = Database(
            CLICKHOUSE_DATABASE,
            db_url=CLICKHOUSE_HTTP_URL,
            username=CLICKHOUSE_USER,
            password=CLICKHOUSE_PASSWORD,
            verify_ssl_cert=False,
        )

        if options["plan"]:
            print("List of clickhouse migrations to be applied:")
            for migration_name in self.get_migrations(database, options["upto"]):
                print(f"Migration would get applied: {migration_name}")
            else:
                print("Clickhouse migrations up to date!")
        elif options["fake"]:
            for migration_name in self.get_migrations(database, options["upto"]):
                print(f"Faked migration: {migration_name}")
                database.insert(
                    [
                        MigrationHistory(
                            package_name=MIGRATIONS_PACKAGE_NAME,
                            module_name=migration_name,
                            applied=datetime.date.today(),
                        )
                    ]
                )
            print("Migrations done")
        else:
            database.migrate(MIGRATIONS_PACKAGE_NAME, options["upto"])
            print("Migration successful")

    def get_migrations(self, database, upto):
        applied_migrations = database._get_applied_migrations(MIGRATIONS_PACKAGE_NAME)
        modules = import_submodules(MIGRATIONS_PACKAGE_NAME)
        unapplied_migrations = set(modules.keys()) - applied_migrations

        for migration_name in sorted(unapplied_migrations):
            yield migration_name

            if int(migration_name[:4]) >= upto:
                break
