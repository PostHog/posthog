from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection

from django.conf import settings
from django.db import connections
from django.db.migrations.executor import MigrationExecutor

from posthog.product_db_router import get_product_db_routes


def product_migration_alias(database: str) -> str:
    """Alias migrations run against: the PgBouncer-bypassing direct alias when
    configured, else the writer (mirrors migrate_product_databases)."""
    direct_alias = f"{database}_db_direct"
    return direct_alias if direct_alias in settings.DATABASES else f"{database}_db_writer"


def collect_unapplied_product_migrations(databases: Collection[str] | None = None) -> dict[str, list[str]]:
    """Read-only check of configured product databases.

    Returns a map of database alias -> unapplied migration names (``app.name``),
    computed the same way ``migrate <app_label> --check`` does, so it agrees with
    what migrate_product_databases would apply. Product databases without a
    configured connection (no PRODUCT_DB_* env in this process) are skipped, so
    each deployment only checks the databases it actually uses. Pass ``databases``
    to restrict the check to specific product databases (by route database name).
    """
    routes = get_product_db_routes()

    db_to_apps: dict[str, set[str]] = defaultdict(set)
    for route in routes:
        if databases is not None and route.database not in databases:
            continue
        if f"{route.database}_db_writer" in settings.DATABASES:
            db_to_apps[route.database].add(route.app_label)

    unapplied: dict[str, list[str]] = {}
    for database, app_labels in sorted(db_to_apps.items()):
        alias = product_migration_alias(database)
        executor = MigrationExecutor(connections[alias])
        targets = [node for node in executor.loader.graph.leaf_nodes() if node[0] in app_labels]
        plan = executor.migration_plan(targets)
        if plan:
            unapplied[alias] = [str(migration) for migration, _ in plan]
    return unapplied
