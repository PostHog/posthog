"""PostHog-specific migration policies.

These are team coding guidelines, not database safety issues.
Policies enforce architectural decisions and coding standards.
"""

from abc import ABC, abstractmethod

# Apps owned by PostHog where policies are enforced
POSTHOG_OWNED_APPS = ["posthog", "ee"]


def is_posthog_app(app_label: str) -> bool:
    """Check if app is owned by PostHog (vs third-party dependency)."""
    if app_label in POSTHOG_OWNED_APPS:
        return True
    if app_label.startswith("products."):
        return True
    return False


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
            if field_name != "id":
                continue

            field_type = field.__class__.__name__
            if field_type in ["AutoField", "BigAutoField"]:
                return [
                    f"Model '{op.name}' uses integer ID ({field_type}). "
                    "PostHog requires UUID primary keys. "
                    "Use `from posthog.models.utils import UUIDModel` and inherit from UUIDModel."
                ]

        return []

    def check_migration(self, migration) -> list[str]:
        """Only enforce on PostHog-owned apps."""
        if not is_posthog_app(migration.app_label):
            return []

        violations = []
        for op in migration.operations:
            violations.extend(self.check_operation(op))
        return violations


class SingleMigrationPolicy(MigrationPolicy):
    """
    PostHog policy: One migration per app per PR.

    Rationale:
    - Easier to debug issues
    - Simpler rollback strategy
    - Clearer code review

    Note: Multiple migrations from different apps is OK (e.g., posthog + third-party dependency).
    """

    def __init__(self, app_counts: dict[str, int]):
        self.app_counts = app_counts

    def check_operation(self, op) -> list[str]:
        """No operation-level checks for this policy."""
        return []

    def check_migration(self, migration) -> list[str]:
        """No single-migration checks for this policy."""
        return []

    def check_batch(self) -> list[str]:
        """Check for multiple migrations per app (PostHog apps only)."""
        violations = []
        for app_label, count in self.app_counts.items():
            if count > 1 and is_posthog_app(app_label):
                violations.append(
                    f"Found {count} migrations for app '{app_label}'. "
                    "PostHog requires one migration per app per PR to promote easy debugging and revertability."
                )
        return violations


# Registry of all PostHog policies
POSTHOG_POLICIES = [
    UUIDPrimaryKeyPolicy(),
]
