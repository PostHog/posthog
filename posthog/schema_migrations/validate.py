import structlog
from posthog.schema_migrations import MIGRATIONS

logger = structlog.get_logger(__name__)


def validate_migrations():
    """Validate that all migrations are linear."""
    for kind, migrations in MIGRATIONS.items():
        versions = sorted(migrations.keys())
        expected = list(range(min(versions), max(versions) + 1))
        if versions != expected:
            raise ValueError(f"Non-linear migration versions for {kind}: {versions} (expected {expected})")
