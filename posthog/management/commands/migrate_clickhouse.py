# ruff: noqa: T201 allow print statements

import re
import datetime
from collections import defaultdict
from textwrap import indent

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from infi.clickhouse_orm import Database
from infi.clickhouse_orm.migrations import MigrationHistory
from infi.clickhouse_orm.utils import import_submodules

from posthog.clickhouse.client.connection import default_client
from posthog.settings import CLICKHOUSE_DATABASE, CLICKHOUSE_HTTP_URL, CLICKHOUSE_PASSWORD, CLICKHOUSE_USER
from posthog.settings.data_stores import CLICKHOUSE_MIGRATIONS_CLUSTER

MIGRATIONS_PACKAGE_NAME = "posthog.clickhouse.migrations"


class Command(BaseCommand):
    help = "Migrate clickhouse"

    def add_arguments(self, parser):
        parser.add_argument(
            "--upto",
            default=99_999,
            type=int,
            help="Database state will be brought to the state after that migration.",
        )
        parser.add_argument(
            "--fake",
            action="store_true",
            help="Mark migrations as run without actually running them.",
        )
        parser.add_argument(
            "--check",
            action="store_true",
            help="Exits with a non-zero status if unapplied migrations exist.",
        )
        parser.add_argument(
            "--plan",
            action="store_true",
            help="Shows a list of the migration actions that will be performed.",
        )
        parser.add_argument(
            "--print-sql",
            action="store_true",
            help="Only use with --plan. Also prints SQL for each migration to be applied.",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Enable strict validation. Checks for duplicate migration prefixes before running.",
        )

    def handle(self, *args, **options):
        self.migrate(CLICKHOUSE_HTTP_URL, options)

    def migrate(self, host, options):
        # Infi only creates the DB in one node, but not the rest. Create it before running migrations.
        self._create_database_if_not_exists(CLICKHOUSE_DATABASE, CLICKHOUSE_MIGRATIONS_CLUSTER)
        database = Database(
            CLICKHOUSE_DATABASE,
            db_url=host,
            username=CLICKHOUSE_USER,
            password=CLICKHOUSE_PASSWORD,
            cluster=CLICKHOUSE_MIGRATIONS_CLUSTER,
            verify_ssl_cert=False,
            randomize_replica_paths=settings.TEST or settings.E2E_TESTING,
        )

        # Check for duplicate migration prefixes if strict mode is enabled
        if options.get("strict"):
            self._check_duplicate_prefixes(database)
        if options["plan"] or options["check"]:
            print("List of clickhouse migrations to be applied:")
            migrations = list(self.get_migrations(database, options["upto"]))
            for migration_name, operations in migrations:
                print(f"Migration would get applied: {migration_name}")
                for op in operations:
                    sql = getattr(op, "_sql", None)
                    if options["print_sql"] and sql is not None:
                        print(indent("\n\n".join(sql), "    "))
            if len(migrations) == 0:
                print("Clickhouse migrations up to date!")
            elif options["check"]:
                exit(1)
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
            database.migrate(MIGRATIONS_PACKAGE_NAME, options["upto"], replicated=True)
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
        return database._get_applied_migrations(MIGRATIONS_PACKAGE_NAME, replicated=True)

    def _check_duplicate_prefixes(self, database):
        """Check for duplicate migration prefixes among unapplied migrations and against applied migrations."""
        modules = import_submodules(MIGRATIONS_PACKAGE_NAME)
        applied_migrations = self.get_applied_migrations(database)
        unapplied_migrations = set(modules.keys()) - applied_migrations

        # Group all migrations by prefix
        prefixes = defaultdict(list)
        duplicates: list[tuple[str, str]] = []

        migration_id_re = re.compile(r"^(\d+)_")
        for migration_name in applied_migrations:
            if match := migration_id_re.match(migration_name):
                prefixes[match.group(1)].append(migration_name)

        for migration_name in unapplied_migrations:
            if match := migration_id_re.match(migration_name):
                prefix = match.group(1)
                if prefix in prefixes:
                    duplicates.append((prefix, migration_name))
                prefixes[prefix].append(migration_name)

        # Check for conflicts
        errors = []
        for prefix, migration_name in duplicates:
            errors.append(f"  Duplicate prefix {migration_name}:")
            for conflict in sorted(prefixes[prefix]):
                errors.append(f"    - {conflict}")

        if errors:
            message = "❌ Found migration prefix conflicts:\n\n" + "\n".join(errors)
            message += "\n\nPlease rename the conflicting unapplied migrations."
            raise CommandError(message)

    def _create_database_if_not_exists(self, database: str, cluster: str):
        if settings.TEST or settings.E2E_TESTING:
            with default_client() as client:
                client.execute(
                    f"CREATE DATABASE IF NOT EXISTS {database} ON CLUSTER {cluster}",
                )
