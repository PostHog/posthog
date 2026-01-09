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
    def check_migration(self, migration) -> tuple[list[str], list[str]]:
        """
        Check if entire migration violates this policy.

        Returns:
            Tuple of (info_messages, violations):
            - info_messages: Informational warnings (don't block)
            - violations: Blocking violations (boost to BLOCKED)
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

    def check_migration(self, migration) -> tuple[list[str], list[str]]:
        """Only enforce on PostHog-owned apps."""
        if not is_posthog_app(migration.app_label):
            return [], []

        violations = []
        for op in migration.operations:
            violations.extend(self.check_operation(op))
        return [], violations  # UUID violations are blocking


class AtomicFalsePolicy(MigrationPolicy):
    """
    Policy: atomic=False should only be used with CONCURRENTLY operations.

    Rationale:
    - atomic=False loses transaction rollback safety
    - Only CONCURRENTLY operations require it (can't run in transaction)
    - Using it for regular DDL creates partial-commit risk on failure
    - Our retry mechanism (bin/migrate) re-runs entire migration, breaking
      on non-idempotent operations that already committed
    """

    CONCURRENT_OP_TYPES = {
        "AddIndexConcurrently",
        "RemoveIndexConcurrently",
    }

    def check_operation(self, op) -> list[str]:
        return []  # Checked at migration level

    def check_migration(self, migration) -> tuple[list[str], list[str]]:
        if not is_posthog_app(migration.app_label):
            return [], []

        is_atomic = getattr(migration, "atomic", True)
        has_concurrent = self._has_concurrent_operations(migration)
        has_non_concurrent = self._has_non_concurrent_operations(migration)

        info = []
        violations = []

        # atomic=False without concurrent ops = info (not blocking)
        # Legitimate for idempotent backfills where partial progress is desired
        if not is_atomic and not has_concurrent:
            info.append(
                "ℹ️ atomic=False without CONCURRENTLY. "
                "OK if migration is idempotent (WHERE field IS NULL, IF NOT EXISTS). "
                "On failure, retry continues from where it left off. "
                "Consider async migrations for very large tables."
            )

        # concurrent ops without atomic=False = violation (will fail at runtime)
        if has_concurrent and is_atomic:
            violations.append(
                "❌ BLOCKED: CONCURRENTLY operations require atomic=False. "
                "PostgreSQL cannot run CREATE/DROP INDEX CONCURRENTLY inside a transaction. "
                "Add 'atomic = False' to the Migration class."
            )

        # Mixed: has both concurrent and non-concurrent ops = info (recommend split)
        if not is_atomic and has_concurrent and has_non_concurrent:
            info.append(
                "ℹ️ RECOMMEND SPLIT: Migration mixes CONCURRENTLY with regular DDL. "
                "Consider splitting for rollback safety on regular operations."
            )

        return info, violations

    def _has_non_concurrent_operations(self, migration) -> bool:
        """Check if migration has operations that are NOT concurrent index operations."""
        non_concurrent_types = {
            "AddField",
            "RemoveField",
            "AlterField",
            "RenameField",
            "CreateModel",
            "DeleteModel",
            "RenameModel",
            "AddConstraint",
            "RemoveConstraint",
            "AlterModelTable",
            "AlterUniqueTogether",
            "AlterIndexTogether",
            "RunPython",
        }

        for op in migration.operations:
            op_type = op.__class__.__name__

            # Check if it's a non-concurrent operation type
            if op_type in non_concurrent_types:
                return True

            # RunSQL that doesn't contain CONCURRENTLY
            if op_type == "RunSQL":
                sql = str(getattr(op, "sql", ""))
                if "CONCURRENTLY" not in sql.upper():
                    return True

            # AddIndex without concurrent=True
            if op_type == "AddIndex":
                if not (hasattr(op, "index") and getattr(op.index, "concurrent", False)):
                    return True

            # Check inside SeparateDatabaseAndState
            if op_type == "SeparateDatabaseAndState":
                for db_op in getattr(op, "database_operations", []) or []:
                    db_op_type = db_op.__class__.__name__
                    if db_op_type in non_concurrent_types:
                        return True
                    if db_op_type == "RunSQL":
                        sql = str(getattr(db_op, "sql", ""))
                        if "CONCURRENTLY" not in sql.upper():
                            return True
                    # AddIndex without concurrent=True inside SeparateDatabaseAndState
                    if db_op_type == "AddIndex":
                        if not (hasattr(db_op, "index") and getattr(db_op.index, "concurrent", False)):
                            return True

        return False

    def _has_concurrent_operations(self, migration) -> bool:
        for op in migration.operations:
            if self._is_concurrent_operation(op):
                return True

            # Also check inside SeparateDatabaseAndState
            if op.__class__.__name__ == "SeparateDatabaseAndState":
                for db_op in getattr(op, "database_operations", []) or []:
                    if self._is_concurrent_operation(db_op):
                        return True

        return False

    def _is_concurrent_operation(self, op) -> bool:
        """Check if a single operation is a CONCURRENTLY operation."""
        # Check Django concurrent operations
        if op.__class__.__name__ in self.CONCURRENT_OP_TYPES:
            return True

        # Check RunSQL for CONCURRENTLY keyword
        if op.__class__.__name__ == "RunSQL":
            sql = str(getattr(op, "sql", ""))
            if "CONCURRENTLY" in sql.upper():
                return True

        # Check AddIndex with concurrent=True
        if op.__class__.__name__ == "AddIndex":
            if hasattr(op, "index") and getattr(op.index, "concurrent", False):
                return True

        return False


# Registry of all PostHog policies
POSTHOG_POLICIES = [
    UUIDPrimaryKeyPolicy(),
    AtomicFalsePolicy(),
]
