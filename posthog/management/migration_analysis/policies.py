"""PostHog-specific migration policies.

These are team coding guidelines, not database safety issues.
Policies enforce architectural decisions and coding standards.
"""

from abc import ABC, abstractmethod


class MigrationPolicy(ABC):
    """Base class for PostHog migration policies."""

    @abstractmethod
    def check_operation(self, op) -> list[str]:
        """
        Check if operation violates this policy.

        Returns:
            List of violation messages (empty if compliant)
        """
        pass

    @abstractmethod
    def check_migration(self, migration) -> list[str]:
        """
        Check if entire migration violates this policy.

        Returns:
            List of violation messages (empty if compliant)
        """
        pass


class UUIDPrimaryKeyPolicy(MigrationPolicy):
    """
    PostHog policy: All new models must use UUID primary keys.

    Rationale:
    - Better for distributed systems (no coordination needed)
    - Security: No sequential/predictable IDs
    - Easier data merging and future sharding
    """

    def check_operation(self, op) -> list[str]:
        if op.__class__.__name__ != "CreateModel":
            return []

        # Check for integer primary key
        for field_name, field in op.fields:
            if field_name == "id":
                field_type = field.__class__.__name__
                if field_type in ["AutoField", "BigAutoField"]:
                    return [
                        f"Model '{op.name}' uses integer ID ({field_type}). "
                        "PostHog requires UUID primary keys. "
                        "Use `from posthog.models.utils import UUIDModel` and inherit from UUIDModel."
                    ]

        return []

    def check_migration(self, migration) -> list[str]:
        """No migration-level checks for this policy."""
        return []


class SingleMigrationPolicy(MigrationPolicy):
    """
    PostHog policy: One migration per PR.

    Rationale:
    - Easier to debug issues
    - Simpler rollback strategy
    - Clearer code review
    """

    def __init__(self, migration_count: int):
        self.migration_count = migration_count

    def check_operation(self, op) -> list[str]:
        """No operation-level checks for this policy."""
        return []

    def check_migration(self, migration) -> list[str]:
        """No single-migration checks for this policy."""
        return []

    def check_batch(self) -> list[str]:
        """Check multiple migrations."""
        if self.migration_count > 1:
            return [
                f"Found {self.migration_count} migrations. "
                "PostHog requires one migration per PR to promote easy debugging and revertability."
            ]
        return []


# Registry of all PostHog policies
POSTHOG_POLICIES = [
    UUIDPrimaryKeyPolicy(),
]
