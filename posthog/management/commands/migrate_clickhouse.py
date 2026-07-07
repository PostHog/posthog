# ruff: noqa: T201 allow print statements

import datetime
from textwrap import indent

from django.conf import settings
from django.core.management.base import BaseCommand

from cachetools import cached
from infi.clickhouse_orm import Database
from infi.clickhouse_orm.migrations import MigrationHistory
from infi.clickhouse_orm.utils import import_submodules

from posthog.clickhouse.client.connection import default_client
from posthog.settings import CLICKHOUSE_DATABASE, CLICKHOUSE_HTTP_URL, CLICKHOUSE_PASSWORD, CLICKHOUSE_USER
from posthog.settings.data_stores import CLICKHOUSE_MIGRATIONS_CLUSTER, CLICKHOUSE_SATELLITE_CLUSTERS

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

    def handle(self, *args, **options):
        self.migrate(CLICKHOUSE_HTTP_URL, options)

    def migrate(self, host, options):
        # Infi only creates the DB in one node, but not the rest. Create it before running migrations.
        self._create_database_if_not_exists(CLICKHOUSE_DATABASE)
        self._create_migration_tracking_tables_if_not_exist(CLICKHOUSE_DATABASE, CLICKHOUSE_MIGRATIONS_CLUSTER)
        database = Database(
            CLICKHOUSE_DATABASE,
            db_url=host,
            username=CLICKHOUSE_USER,
            password=CLICKHOUSE_PASSWORD,
            cluster=CLICKHOUSE_MIGRATIONS_CLUSTER,
            verify_ssl_cert=False,
            randomize_replica_paths=settings.TEST or settings.E2E_TESTING,
            # don't use the egress proxy, clickhouse is internal
            trust_env=False,
        )

        if options["plan"] or options["check"]:
            print("List of clickhouse migrations to be applied:")
            migrations = list(self.get_migrations(database, options["upto"]))
            for migration_name, operations in migrations:
                print(f"Migration would get applied: {migration_name}")
                for op in operations:
                    sql = getattr(op, "_sql", None)
                    if options["print_sql"] and sql is not None:
                        if isinstance(sql, str):
                            print(indent(sql, "    "))
                        else:
                            print(indent("\n\n".join(sql), "    "))
            applied = self.get_applied_migrations(database)
            if len(applied) > 0:
                last = max(applied)
                print(f"\nClickhouse most recent applied migration: {last}")
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

    @cached(cache={})
    def get_applied_migrations(self, database) -> set[str]:
        return database._get_applied_migrations(MIGRATIONS_PACKAGE_NAME, replicated=True)

    def _create_database_if_not_exists(self, database: str):
        # MULTINODE_CLICKHOUSE: infi.clickhouse_orm creates the Distributed
        # migration-tracking table across the migrations cluster before the
        # first migration runs, so the database has to exist on every node up
        # front — otherwise the CREATE TABLE fans out to satellites that have
        # no `posthog` database yet and fails with UNKNOWN_DATABASE.
        #
        # Individual migration operations then fan out per node role via
        # cluster.map_hosts_by_roles / any_host_by_roles, which reach the
        # satellite clusters (ai_events, aux, ops, sessions, ...) through the
        # cluster's extra hosts — not through the migrations cluster. Those
        # satellite nodes are their own clusters and are NOT necessarily part
        # of CLICKHOUSE_MIGRATIONS_CLUSTER, so creating the database only on
        # the migrations cluster leaves them without `posthog` and every
        # fanned-out query against them fails with UNKNOWN_DATABASE. Create it
        # on each satellite cluster too, before any migration query lands.
        if not self._should_bootstrap_databases():
            return
        # dict.fromkeys dedupes while preserving order in case the migrations
        # cluster is also listed as a satellite.
        clusters = dict.fromkeys([CLICKHOUSE_MIGRATIONS_CLUSTER, *CLICKHOUSE_SATELLITE_CLUSTERS])
        with default_client() as client:
            for cluster in clusters:
                client.execute(
                    f"CREATE DATABASE IF NOT EXISTS {database} ON CLUSTER {cluster}",
                )

    def _should_bootstrap_databases(self) -> bool:
        # Migrations fan out to satellite clusters by node role only when routing
        # is NOT collapsed to NodeRole.ALL. Mirror the collapse condition in
        # run_sql_with_exceptions so database bootstrap and query routing agree on
        # which nodes are in play: role-based routing is active in the multinode
        # smoke stack and in real cloud deployments, but not in local/hobby dev.
        collapsed_to_all = (
            settings.E2E_TESTING or settings.DEBUG or not settings.CLOUD_DEPLOYMENT
        ) and not settings.MULTINODE_CLICKHOUSE
        return settings.TEST or settings.E2E_TESTING or settings.MULTINODE_CLICKHOUSE or not collapsed_to_all

    def _create_migration_tracking_tables_if_not_exist(self, database: str, cluster: str):
        # MULTINODE_CLICKHOUSE only: infi.clickhouse_orm's auto-create path
        # issues `CREATE TABLE` without `ON CLUSTER`, so the underlying
        # ReplicatedMergeTree only lands on the migrations host. With a real
        # multi-node `posthog_migrations` cluster, the Distributed tracking
        # table fans out to every shard and trips UNKNOWN_TABLE on satellites
        # that never received the local replica. Pre-create both tables on
        # the cluster so the very first SELECT in infi's migrate() succeeds
        # and the auto-create branch never runs.
        #
        # Schema (`package_name String, module_name String, applied Date`) and
        # the ZK path mirror `infi.clickhouse_orm.migrations.MigrationHistory`
        # / `MigrationHistoryReplicated`. If `infi` ever changes those, this
        # pre-create will silently diverge — keep the two in sync.
        if not settings.MULTINODE_CLICKHOUSE:
            return
        with default_client() as client:
            client.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {database}.infi_clickhouse_orm_migrations
                ON CLUSTER {cluster} (
                    package_name String,
                    module_name String,
                    applied Date
                )
                ENGINE = ReplicatedMergeTree(
                    '/clickhouse/prod/tables/noshard/{{database}}/{{table}}',
                    '{{replica}}-{{shard}}'
                )
                PARTITION BY toYYYYMM(applied)
                ORDER BY (package_name, module_name)
                SETTINGS index_granularity = 8192
                """
            )
            client.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {database}.infi_clickhouse_orm_migrations_distributed
                ON CLUSTER {cluster} (
                    package_name String,
                    module_name String,
                    applied Date
                )
                ENGINE = Distributed({cluster}, {database}, infi_clickhouse_orm_migrations, rand())
                """
            )
