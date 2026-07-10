import os
import re
import importlib
import threading

import structlog

from posthog.schema_migrations.base import SchemaMigration

logger = structlog.get_logger(__name__)

LATEST_VERSIONS: dict[str, int] = {}
MIGRATIONS: dict[str, dict[int, SchemaMigration]] = {}
_migrations_discovered: bool = False
_discovery_lock = threading.Lock()


def _discover_migrations():
    global _migrations_discovered
    if _migrations_discovered:
        return

    # Serialize discovery: concurrent first calls would otherwise interleave the clear/rebuild
    # below, tripping the duplicate-target check on valid migrations or exposing partial state
    with _discovery_lock:
        if _migrations_discovered:
            return

        # Clear in place (both dicts are imported by reference elsewhere), so a retry
        # after a failed discovery doesn't see partial state as duplicate targets
        LATEST_VERSIONS.clear()
        MIGRATIONS.clear()

        migration_dir = os.path.dirname(__file__)
        migration_files = [f for f in os.listdir(migration_dir) if re.match(r"^\d{4}[a-zA-Z_]*\.py$", f)]

        for file in sorted(migration_files):
            module_name = file[:-3]  # Remove .py
            module = importlib.import_module(f"posthog.schema_migrations.{module_name}")
            migration = module.Migration()

            for kind, version in migration.targets.items():
                if kind not in MIGRATIONS:
                    MIGRATIONS[kind] = {}
                if version in MIGRATIONS[kind]:
                    # Overwriting would silently drop one of the two transforms at runtime
                    raise ValueError(
                        f"Duplicate schema migration target: {module_name} targets {kind} version {version}, "
                        f"which is already targeted by another migration. Bump one of them to the next version."
                    )
                MIGRATIONS[kind][version] = migration

                old_version = LATEST_VERSIONS.get(kind, 1)
                new_version = max(old_version, version + 1)
                LATEST_VERSIONS[kind] = new_version

        # Set only after the registry is fully built, so the unlocked fast path above
        # never observes a partially populated registry
        _migrations_discovered = True
        logger.debug("migrations_discovered", latest_versions={str(k): v for k, v in LATEST_VERSIONS.items()})
