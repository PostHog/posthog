import os
import importlib
import re
from posthog.schema import NodeKind
from posthog.schema_migrations.base import SchemaMigration
import structlog

logger = structlog.get_logger(__name__)

LATEST_VERSIONS: dict[NodeKind, int] = {}
MIGRATIONS: dict[NodeKind, dict[int, SchemaMigration]] = {}


def _discover_migrations():
    migration_dir = os.path.dirname(__file__)
    migration_files = [f for f in os.listdir(migration_dir) if re.match(r"^\d{4}[a-zA-Z_]*\.py$", f)]

    for file in sorted(migration_files):
        module_name = file[:-3]  # Remove .py
        module = importlib.import_module(f"posthog.schema_migrations.{module_name}")
        migration = module.Migration()

        for kind, version in migration.targets.items():
            if kind not in MIGRATIONS:
                MIGRATIONS[kind] = {}
            MIGRATIONS[kind][version] = migration

            old_version = LATEST_VERSIONS.get(kind, 1)
            new_version = max(old_version, version + 1)
            LATEST_VERSIONS[kind] = new_version


_discover_migrations()
logger.info("migrations_discovered", latest_versions={str(k): v for k, v in LATEST_VERSIONS.items()})
