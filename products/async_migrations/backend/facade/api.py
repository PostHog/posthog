"""Public facade for the async_migrations product.

Core (`posthog/`, `ee/`) drives the ClickHouse async-migration engine only through the
capabilities exposed here — the API viewset, instance status/settings, the app-ready
hook, the management command, and the celery tasks. The functions operate on the core
`AsyncMigration` model and primitives; the product owns no data model of its own, so
there are no contracts to map (see `contracts.py`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from products.async_migrations.backend import (
    runner as _runner,
    setup as _setup,
    status as _status,
    utils as _utils,
)
from products.async_migrations.backend.definition import AsyncMigrationDefinition
from products.async_migrations.backend.runner import (
    MAX_CONCURRENT_ASYNC_MIGRATIONS,
    complete_migration,
    is_migration_dependency_fulfilled,
    run_async_migration_next_op,
    run_async_migration_operations,
    run_migration_healthcheck,
    start_async_migration,
    update_migration_progress,
)
from products.async_migrations.backend.setup import ALL_ASYNC_MIGRATIONS, setup_model
from products.async_migrations.backend.utils import process_error

if TYPE_CHECKING:
    from posthog.models.async_migration import AsyncMigration


def setup_async_migrations(ignore_posthog_version: bool = False) -> None:
    _setup.setup_async_migrations(ignore_posthog_version=ignore_posthog_version)


def get_async_migration_definition(migration_name: str) -> AsyncMigrationDefinition:
    return _setup.get_async_migration_definition(migration_name)


def async_migrations_ok() -> bool:
    return _status.async_migrations_ok()


def is_posthog_version_compatible(posthog_min_version: str, posthog_max_version: str) -> bool:
    return bool(_runner.is_posthog_version_compatible(posthog_min_version, posthog_max_version))


def trigger_migration(migration_instance: AsyncMigration, fresh_start: bool = True) -> None:
    _utils.trigger_migration(migration_instance, fresh_start=fresh_start)


def force_stop_migration(
    migration_instance: AsyncMigration,
    error: str = "Force stopped by user",
    rollback: bool = True,
) -> None:
    _utils.force_stop_migration(migration_instance, error=error, rollback=rollback)


def rollback_migration(migration_instance: AsyncMigration) -> None:
    _utils.rollback_migration(migration_instance)


__all__ = [
    "ALL_ASYNC_MIGRATIONS",
    "MAX_CONCURRENT_ASYNC_MIGRATIONS",
    "AsyncMigrationDefinition",
    "async_migrations_ok",
    "complete_migration",
    "force_stop_migration",
    "get_async_migration_definition",
    "is_migration_dependency_fulfilled",
    "is_posthog_version_compatible",
    "process_error",
    "rollback_migration",
    "run_async_migration_next_op",
    "run_async_migration_operations",
    "run_migration_healthcheck",
    "setup_async_migrations",
    "setup_model",
    "start_async_migration",
    "trigger_migration",
    "update_migration_progress",
]
