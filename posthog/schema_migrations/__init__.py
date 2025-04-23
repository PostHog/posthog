import os
import importlib
import re
from posthog.schema import NodeKind
import structlog

logger = structlog.get_logger(__name__)

LATEST_VERSIONS: dict[NodeKind, int] = {}


def _discover_migrations():
    migration_dir = os.path.dirname(__file__)
    migration_files = [f for f in os.listdir(migration_dir) if re.match(r"^\d{4}.*\.py$", f)]

    for file in sorted(migration_files):
        module_name = file[:-3]  # Remove .py
        module = importlib.import_module(f"posthog.schema_migrations.{module_name}")
        migration = module.Migration()

        # Update versions based on migration targets
        for kind, version in migration.targets.items():
            old_version = LATEST_VERSIONS.get(kind, 1)
            new_version = max(old_version, version + 1)
            LATEST_VERSIONS[kind] = new_version


_discover_migrations()
logger.info("migrations_discovered", latest_versions={str(k): v for k, v in LATEST_VERSIONS.items()})
