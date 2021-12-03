import datetime
from textwrap import indent

from django.core.management.base import BaseCommand
from infi.clickhouse_orm import Database  # type: ignore
from infi.clickhouse_orm.migrations import MigrationHistory  # type: ignore
from infi.clickhouse_orm.utils import import_submodules

from posthog.models.special_migration import MigrationStatus, SpecialMigration  # type: ignore
from posthog.settings import (
    CLICKHOUSE_DATABASE,
    CLICKHOUSE_HTTP_URL,
    CLICKHOUSE_PASSWORD,
    CLICKHOUSE_REPLICATION,
    CLICKHOUSE_USER,
)
from posthog.special_migrations.runner import start_special_migration
from posthog.special_migrations.setup import ALL_SPECIAL_MIGRATIONS

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
        parser.add_argument(
            "--print-sql",
            action="store_true",
            help="Only use with --plan. Also prints SQL for each migration to be applied.",
        )
        parser.add_argument(
            "--skip-special-migrations",
            type=bool,
            default=False,
            help="Skip running special migrations on a fresh instance",
        )

    def handle(self, *args, **options):
        self.migrate(CLICKHOUSE_HTTP_URL, options)

    def migrate(self, host, options):
        database = Database(
            CLICKHOUSE_DATABASE,
            db_url=host,
            username=CLICKHOUSE_USER,
            password=CLICKHOUSE_PASSWORD,
            verify_ssl_cert=False,
        )
        if options["plan"]:
            print("List of clickhouse migrations to be applied:")
            migrations = list(self.get_migrations(database, options["upto"]))
            for migration_name, operations in migrations:
                print(f"Migration would get applied: {migration_name}")
                for op in operations:
                    sql = getattr(op, "_sql")
                    if options["print_sql"] and sql is not None:
                        print(indent("\n\n".join(sql), "    "))
            if len(migrations) == 0:
                print("Clickhouse migrations up to date!")
        elif options["fake"]:
            for migration_name, _ in self.get_migrations(database, options["upto"]):
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
            is_fresh_instance = len(self.get_applied_migrations(database)) == 0
            database.migrate(MIGRATIONS_PACKAGE_NAME, options["upto"], replicated=CLICKHOUSE_REPLICATION)
            if is_fresh_instance and not options["skip_special_migrations"]:
                for migration_name, definition in ALL_SPECIAL_MIGRATIONS.items():
                    sm = SpecialMigration.objects.get_or_create(
                        name=migration_name,
                        description=definition.description,
                        posthog_min_version=definition.posthog_min_version,
                        posthog_max_version=definition.posthog_max_version,
                    )[0]
                    if sm.status == MigrationStatus.NotStarted:
                        print("Applying special migration", migration_name)
                        started_successfully = start_special_migration(migration_name)
                        if not started_successfully or sm.status != MigrationStatus.CompletedSuccessfully:
                            print(f"Unable to complete special migration {migration_name} with error", sm.last_error)
                            return
            print("✅ Migration successful")

    def get_migrations(self, database, upto):
        modules = import_submodules(MIGRATIONS_PACKAGE_NAME)
        applied_migrations = self.get_applied_migrations(database)
        unapplied_migrations = set(modules.keys()) - applied_migrations

        for migration_name in sorted(unapplied_migrations):
            yield migration_name, modules[migration_name].operations

            if int(migration_name[:4]) >= upto:
                break

    def get_applied_migrations(self, database):
        return database._get_applied_migrations(MIGRATIONS_PACKAGE_NAME, replicated=CLICKHOUSE_REPLICATION)
