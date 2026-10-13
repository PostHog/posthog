# ruff: noqa: T201 allow print statements

import datetime
from textwrap import indent

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from cachetools import cached
from infi.clickhouse_orm import Database
from infi.clickhouse_orm.migrations import MigrationHistory
from infi.clickhouse_orm.utils import import_submodules

from posthog.clickhouse.client.connection import ClickHouseCredentials, default_client
from posthog.clickhouse.managed_schema import ClickHouseDatabase
from posthog.run_mode import run_mode
from posthog.settings import CLICKHOUSE_DATABASE, CLICKHOUSE_PASSWORD, CLICKHOUSE_USER
from posthog.settings.data_stores import CLICKHOUSE_MIGRATIONS_CLUSTER, CLICKHOUSE_PASSWORD_FILE

MIGRATIONS_PACKAGE_NAME = "posthog.clickhouse.migrations"


class Command(BaseCommand):
    help = "Create or update the ClickHouse schema of a single-cluster install, and load its reference data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--check",
            action="store_true",
            help="Exits with a non-zero status if the database differs from the declared schema.",
        )
        parser.add_argument(
            "--plan",
            action="store_true",
            help="Shows the changes that would bring the database to the declared schema.",
        )

    def handle(self, *args, **options):
        if run_mode().is_deployed_cloud:
            # Cloud clusters get their schema from the infrastructure repository, which maps it onto the nodes.
            # Deploy hooks still call this command, so it succeeds without doing anything.
            self.stdout.write("Skipping: the ClickHouse schema of this deployment is not applied by the app")
            return

        database = ClickHouseDatabase()
        if not database.is_single_node():
            # A cloud pod whose CLOUD_DEPLOYMENT is missing resolves to HOBBY, so the run mode alone cannot protect
            # a production cluster. Every install this command manages runs ClickHouse on one node.
            self.stderr.write(
                "Skipping: ClickHouse has remote cluster hosts, and this command manages single-node installs only"
            )
            return
        if options["check"] or options["plan"]:
            has_changes, plan = database.plan_schema(kafka=True)
            self.stdout.write(plan)
            if has_changes and options["check"]:
                raise CommandError("The ClickHouse schema is not up to date")
            return

        database.create()
        database.apply_schema(kafka=True)
        database.seed()
        self.stdout.write(self.style.SUCCESS("ClickHouse schema is up to date"))

    def migrate(self, host, options):
        # Read-only --check and --plan finish in seconds, so they use the short-lived
        # token from CLICKHOUSE_PASSWORD_FILE, and fall back to the static password when
        # no token file is set. infi.clickhouse_orm never re-reads the password, and an
        # apply can outlast the token, so the apply keeps the static password. The setup
        # steps below share this password, so they never authenticate differently than
        # the migration itself.
        if options["check"] or options["plan"]:
            password = ClickHouseCredentials(
                user=CLICKHOUSE_USER, password=CLICKHOUSE_PASSWORD, password_file=CLICKHOUSE_PASSWORD_FILE
            ).read_password()
        else:
            password = CLICKHOUSE_PASSWORD

        # Infi only creates the DB in one node, but not the rest. Create it before running migrations.
        self._create_database_if_not_exists(CLICKHOUSE_DATABASE, CLICKHOUSE_MIGRATIONS_CLUSTER, password)
        self._create_migration_tracking_tables_if_not_exist(
            CLICKHOUSE_DATABASE, CLICKHOUSE_MIGRATIONS_CLUSTER, password
        )
        database = Database(
            CLICKHOUSE_DATABASE,
            db_url=host,
            username=CLICKHOUSE_USER,
            password=password,
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

    def _create_database_if_not_exists(self, database: str, cluster: str, password: str):
        # MULTINODE_CLICKHOUSE: infi.clickhouse_orm creates the Distributed
        # migration-tracking table across the migrations cluster before the
        # first migration runs, so the database has to exist on every node up
        # front — otherwise the CREATE TABLE fans out to satellites that have
        # no `posthog` database yet and fails with UNKNOWN_DATABASE.
        if settings.TEST or settings.E2E_TESTING or settings.MULTINODE_CLICKHOUSE:
            with default_client(password=password) as client:
                client.execute(
                    f"CREATE DATABASE IF NOT EXISTS {database} ON CLUSTER {cluster}",
                )

    def _create_migration_tracking_tables_if_not_exist(self, database: str, cluster: str, password: str):
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
        with default_client(password=password) as client:
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
