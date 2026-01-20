# ruff: noqa: T201 allow print statements

import datetime
from dataclasses import dataclass
from textwrap import indent

from django.conf import settings
from django.core.management.base import BaseCommand

from cachetools import cached
from infi.clickhouse_orm import Database
from infi.clickhouse_orm.migrations import MigrationHistory
from infi.clickhouse_orm.utils import import_submodules

from posthog.clickhouse.client.connection import default_client
from posthog.clickhouse.client.migration_tools import MigrationCluster
from posthog.settings import CLICKHOUSE_DATABASE, CLICKHOUSE_HTTP_URL, CLICKHOUSE_PASSWORD, CLICKHOUSE_USER
from posthog.settings.data_stores import (
    CLICKHOUSE_LOGS_CLUSTER_DATABASE,
    CLICKHOUSE_LOGS_CLUSTER_PASSWORD,
    CLICKHOUSE_LOGS_CLUSTER_USER,
    CLICKHOUSE_LOGS_HTTP_URL,
    CLICKHOUSE_LOGS_MIGRATIONS_CLUSTER,
    CLICKHOUSE_MIGRATIONS_CLUSTER,
)


@dataclass
class ClusterConfig:
    package_name: str
    database: str
    http_url: str
    username: str
    password: str
    migrations_cluster: str
    display_name: str


CLUSTER_CONFIGS: dict[str, ClusterConfig] = {
    MigrationCluster.MAIN: ClusterConfig(
        package_name="posthog.clickhouse.migrations",
        database=CLICKHOUSE_DATABASE,
        http_url=CLICKHOUSE_HTTP_URL,
        username=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
        migrations_cluster=CLICKHOUSE_MIGRATIONS_CLUSTER,
        display_name="main",
    ),
    MigrationCluster.LOGS: ClusterConfig(
        package_name="posthog.clickhouse.migrations_logs",
        database=CLICKHOUSE_LOGS_CLUSTER_DATABASE,
        http_url=CLICKHOUSE_LOGS_HTTP_URL,
        username=CLICKHOUSE_LOGS_CLUSTER_USER,
        password=CLICKHOUSE_LOGS_CLUSTER_PASSWORD,
        migrations_cluster=CLICKHOUSE_LOGS_MIGRATIONS_CLUSTER,
        display_name="logs",
    ),
}


class Command(BaseCommand):
    help = "Migrate clickhouse"

    def add_arguments(self, parser):
        parser.add_argument(
            "--cluster",
            default=MigrationCluster.MAIN,
            choices=[c.value for c in MigrationCluster],
            help="Which ClickHouse cluster to migrate. Default: main",
        )
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

    def handle(self, *args, **options):
        cluster_name = options["cluster"]
        config = CLUSTER_CONFIGS[cluster_name]
        self.migrate(config, options)

    def migrate(self, config: ClusterConfig, options):
        # Infi only creates the DB in one node, but not the rest. Create it before running migrations.
        self._create_database_if_not_exists(config.database, config.migrations_cluster)
        database = Database(
            config.database,
            db_url=config.http_url,
            username=config.username,
            password=config.password,
            cluster=config.migrations_cluster,
            verify_ssl_cert=False,
            randomize_replica_paths=settings.TEST or settings.E2E_TESTING,
        )

        if options["plan"] or options["check"]:
            print(f"List of clickhouse migrations to be applied ({config.display_name} cluster):")
            migrations = list(self.get_migrations(database, config.package_name, options["upto"]))
            for migration_name, operations in migrations:
                print(f"Migration would get applied: {migration_name}")
                for op in operations:
                    sql = getattr(op, "_sql", None)
                    if options["print_sql"] and sql is not None:
                        if isinstance(sql, str):
                            print(indent(sql, "    "))
                        else:
                            print(indent("\n\n".join(sql), "    "))
            applied = self.get_applied_migrations(database, config.package_name)
            if len(applied) > 0:
                last = max(applied)
                print(f"\nClickhouse ({config.display_name}) most recent applied migration: {last}")
            if len(migrations) == 0:
                print(f"Clickhouse ({config.display_name}) migrations up to date!")
            elif options["check"]:
                exit(1)
        elif options["fake"]:
            for migration_name, _ in self.get_migrations(database, config.package_name, options["upto"]):
                print(f"Faked migration: {migration_name}")
                database.insert(
                    [
                        MigrationHistory(
                            package_name=config.package_name,
                            module_name=migration_name,
                            applied=datetime.date.today(),
                        )
                    ]
                )
            print("Migrations done")
        else:
            database.migrate(config.package_name, options["upto"], replicated=True)
            print(f"✅ Migration successful ({config.display_name} cluster)")

    def get_migrations(self, database, package_name: str, upto: int):
        modules = import_submodules(package_name)
        applied_migrations = self.get_applied_migrations(database, package_name)
        unapplied_migrations = set(modules.keys()) - applied_migrations

        for migration_name in sorted(unapplied_migrations):
            yield migration_name, modules[migration_name].operations

            if int(migration_name[:4]) >= upto:
                break

    @cached(cache={})
    def get_applied_migrations(self, database, package_name: str) -> set[str]:
        return database._get_applied_migrations(package_name, replicated=True)

    def _create_database_if_not_exists(self, database: str, cluster: str):
        if settings.TEST or settings.E2E_TESTING:
            with default_client() as client:
                client.execute(
                    f"CREATE DATABASE IF NOT EXISTS {database} ON CLUSTER {cluster}",
                )
