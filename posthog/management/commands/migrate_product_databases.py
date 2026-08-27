from __future__ import annotations

import os
import time

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import OperationalError, connections
from django.db.migrations.executor import MigrationExecutor

import psycopg
import structlog
from psycopg import sql

from posthog.product_db_migrations import configured_product_databases, product_migration_alias
from posthog.product_db_router import get_product_db_routes
from posthog.settings.base_variables import DEBUG

logger = structlog.get_logger(__name__)

# Retry knobs share the names bin/migrate uses for the main-database loop, so a
# deploy tunes both the same way. A product migration runs after that shell loop,
# as a single un-retried call, so without an in-process retry a lock_timeout
# cancellation — or a deadlock, which lock_timeout cannot prevent — fails the
# deploy on the first try.
DEFAULT_MAX_RETRIES = 10
DEFAULT_RETRY_DELAY = 3.0
DEFAULT_BACKOFF = 2.0


class ProductMigrationError(Exception):
    """A product migration failed after all retries.

    Carries the database, app label, and migration name so the deploy error
    report names the migration that failed instead of a bare OperationalError.
    """

    def __init__(self, alias: str, app_label: str, migration_name: str | None, cause: BaseException) -> None:
        self.alias = alias
        self.app_label = app_label
        self.migration_name = migration_name
        target = f"{app_label}.{migration_name}" if migration_name else app_label
        super().__init__(f"Product migration {target} on database '{alias}' failed after retries: {cause}")


def _ensure_database_exists(db_alias: str) -> None:
    """Create the product database if it doesn't exist yet."""
    db_settings = settings.DATABASES[db_alias]
    target_db = db_settings["NAME"]

    with psycopg.connect(
        dbname="postgres",
        host=db_settings.get("HOST") or "localhost",
        port=int(db_settings.get("PORT") or 5432),
        user=db_settings.get("USER") or "posthog",
        password=db_settings.get("PASSWORD") or "posthog",
        autocommit=True,
    ) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_db,))
            if cur.fetchone():
                return

            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_db)))
            owner = db_settings.get("USER")
            if owner:
                cur.execute(
                    sql.SQL("GRANT ALL PRIVILEGES ON DATABASE {} TO {}").format(
                        sql.Identifier(target_db),
                        sql.Identifier(owner),
                    )
                )


def _next_unapplied_migration(alias: str, app_label: str) -> str | None:
    """Name of the first still-unapplied migration for the app.

    Django applies an app's migrations in order and stops at the one that fails,
    so after a failed run this names the migration that failed.
    """
    executor = MigrationExecutor(connections[alias])
    targets = [node for node in executor.loader.graph.leaf_nodes() if node[0] == app_label]
    for migration, _ in executor.migration_plan(targets):
        if migration.app_label == app_label:
            return migration.name
    return None


def _migrate_app(
    stdout,
    alias: str,
    app_label: str,
    *,
    max_retries: int,
    retry_delay: float,
    backoff: float,
) -> None:
    """Apply one app's migrations, retrying transient lock failures.

    Retries OperationalError, which wraps both a lock_timeout cancellation and a
    DeadlockDetected. On the last attempt it re-raises as ProductMigrationError,
    tagged with the migration that failed.
    """
    delay = retry_delay
    for attempt in range(1, max_retries + 1):
        try:
            call_command("migrate", app_label, database=alias, interactive=False, verbosity=1)
            return
        except OperationalError as exc:
            # A cancelled statement can leave the connection in an aborted
            # transaction; drop it so the name lookup and the retry both start clean.
            connection = connections[alias]
            if not connection.in_atomic_block:
                connection.close()

            migration_name = _next_unapplied_migration(alias, app_label)
            target = f"{app_label}.{migration_name}" if migration_name else app_label

            if attempt >= max_retries:
                raise ProductMigrationError(alias, app_label, migration_name, exc) from exc

            logger.warning(
                "product_migration_retry",
                database=alias,
                migration=target,
                attempt=attempt,
                max_retries=max_retries,
                error=str(exc),
            )
            stdout.write(
                f"Product migration {target} failed (attempt {attempt}/{max_retries}), retrying in {delay:.0f}s"
            )
            time.sleep(delay)
            delay *= backoff


class Command(BaseCommand):
    help = "Run Django migrations for product-routed databases"

    def handle(self, *args, **options):
        get_product_db_routes.cache_clear()
        db_to_apps = configured_product_databases()

        if not db_to_apps:
            self.stdout.write("No configured product databases found.")
            return

        max_retries = int(os.environ.get("MIGRATE_MAX_RETRIES", DEFAULT_MAX_RETRIES))
        retry_delay = float(os.environ.get("MIGRATE_RETRY_DELAY", DEFAULT_RETRY_DELAY))
        backoff = float(os.environ.get("MIGRATE_BACKOFF", DEFAULT_BACKOFF))

        for database, app_labels in sorted(db_to_apps.items()):
            # Use direct connection (bypasses PgBouncer) for migrations; shared with
            # check_product_migrations so check and apply cannot disagree on the alias.
            migrate_alias = product_migration_alias(database)

            if DEBUG:
                _ensure_database_exists(migrate_alias)
            self.stdout.write(f"Running product migrations on database '{migrate_alias}'")
            for app_label in sorted(app_labels):
                _migrate_app(
                    self.stdout,
                    migrate_alias,
                    app_label,
                    max_retries=max_retries,
                    retry_delay=retry_delay,
                    backoff=backoff,
                )
