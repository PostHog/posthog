# ruff: noqa: T201 allow print statements
import sys
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.migrations.executor import MigrationExecutor

from infi.clickhouse_orm import Database
from infi.clickhouse_orm.utils import import_submodules

from posthog.settings import CLICKHOUSE_DATABASE, CLICKHOUSE_HTTP_URL, CLICKHOUSE_PASSWORD, CLICKHOUSE_USER
from posthog.settings.data_stores import CLICKHOUSE_MIGRATIONS_CLUSTER

CLICKHOUSE_MIGRATIONS_PACKAGE = "posthog.clickhouse.migrations"


def _postgres_migrations_pending() -> bool:
    """Check for unapplied Django migrations. Same approach as posthog/health.py."""
    try:
        executor = MigrationExecutor(connections[DEFAULT_DB_ALIAS])
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        return len(plan) > 0
    except Exception as e:
        print(f"  PostgreSQL check failed: {e}")
        return True


def _clickhouse_migrations_pending() -> bool:
    """Check for unapplied ClickHouse migrations.

    Mirrors migrate_clickhouse.py logic but without the @cached decorator
    so results stay fresh across loop iterations.
    """
    try:
        database = Database(
            CLICKHOUSE_DATABASE,
            db_url=CLICKHOUSE_HTTP_URL,
            username=CLICKHOUSE_USER,
            password=CLICKHOUSE_PASSWORD,
            cluster=CLICKHOUSE_MIGRATIONS_CLUSTER,
            verify_ssl_cert=False,
            randomize_replica_paths=settings.TEST or settings.E2E_TESTING,
        )
        modules = import_submodules(CLICKHOUSE_MIGRATIONS_PACKAGE)
        applied = database._get_applied_migrations(CLICKHOUSE_MIGRATIONS_PACKAGE, replicated=True)
        unapplied = set(modules.keys()) - applied
        return len(unapplied) > 0
    except Exception as e:
        print(f"  ClickHouse check failed: {e}")
        return True


def _async_migrations_pending() -> bool:
    """Check for blocking async migrations.

    Mirrors run_async_migrations.py --check: only blocks when
    ASYNC_MIGRATIONS_BLOCK_UPGRADE is enabled.
    """
    try:
        from posthog.async_migrations.setup import setup_async_migrations
        from posthog.models.async_migration import MigrationStatus, get_async_migrations_by_status
        from posthog.models.instance_setting import get_instance_setting

        if not get_instance_setting("ASYNC_MIGRATIONS_BLOCK_UPGRADE"):
            return False

        setup_async_migrations(ignore_posthog_version=True)

        from posthog.management.commands.run_async_migrations import get_necessary_migrations

        if get_necessary_migrations():
            return True
        if get_async_migrations_by_status([MigrationStatus.Running, MigrationStatus.Starting]).exists():
            return True
        if get_async_migrations_by_status([MigrationStatus.Errored]).exists():
            return True
        return False
    except Exception as e:
        print(f"  Async migrations check failed: {e}")
        return True


class Command(BaseCommand):
    help = "Wait for all migrations to be applied, then exit. Designed for k8s init containers."

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval",
            type=int,
            default=30,
            help="Seconds between checks (default: 30)",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=0,
            help="Maximum seconds to wait, 0 = wait forever (default: 0)",
        )
        parser.add_argument(
            "--skip-postgres",
            action="store_true",
            help="Skip PostgreSQL migration check",
        )
        parser.add_argument(
            "--skip-clickhouse",
            action="store_true",
            help="Skip ClickHouse migration check",
        )
        parser.add_argument(
            "--skip-async",
            action="store_true",
            help="Skip async migration check",
        )

    def handle(self, *args, **options):
        interval = options["interval"]
        timeout = options["timeout"]
        skip_pg = options["skip_postgres"]
        skip_ch = options["skip_clickhouse"]
        skip_async = options["skip_async"]

        start = time.monotonic()

        while True:
            pending = []

            if not skip_pg and _postgres_migrations_pending():
                pending.append("PostgreSQL")

            if not skip_ch and _clickhouse_migrations_pending():
                pending.append("ClickHouse")

            if not skip_async and _async_migrations_pending():
                pending.append("async")

            if not pending:
                print("All migrations up to date!")
                return

            elapsed = time.monotonic() - start
            print(f"Waiting for migrations: {', '.join(pending)} ({elapsed:.0f}s elapsed)")

            if timeout and elapsed >= timeout:
                print(f"Timed out after {timeout}s waiting for migrations")
                sys.exit(1)

            time.sleep(interval)
