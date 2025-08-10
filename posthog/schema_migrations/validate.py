import structlog
from posthog.schema_migrations import MIGRATIONS

logger = structlog.get_logger(__name__)


def validate_migrations():
    """Validate that all migrations are linear and in strictly increasing order."""
    for kind, migrations in MIGRATIONS.items():
        versions = list(migrations.keys())
        sorted_versions = sorted(versions)
        expected = list(range(min(sorted_versions), max(sorted_versions) + 1))
        if versions != sorted_versions:
            raise ValueError(f"Migration versions for {kind} are not in strictly increasing order: {versions}")
        if sorted_versions != expected:
            raise ValueError(f"Non-linear migration versions for {kind}: {sorted_versions} (expected {expected})")
