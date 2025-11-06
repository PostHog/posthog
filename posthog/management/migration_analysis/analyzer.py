"""Main risk analyzer for Django migrations."""

from posthog.management.migration_analysis.models import MigrationRisk, OperationRisk
from posthog.management.migration_analysis.operations import (
    AddConstraintAnalyzer,
    AddFieldAnalyzer,
    AddIndexAnalyzer,
    AlterFieldAnalyzer,
    AlterIndexTogetherAnalyzer,
    AlterModelTableAnalyzer,
    AlterUniqueTogetherAnalyzer,
    CreateModelAnalyzer,
    DeleteModelAnalyzer,
    RemoveFieldAnalyzer,
    RemoveIndexAnalyzer,
    RenameFieldAnalyzer,
    RenameModelAnalyzer,
    RunPythonAnalyzer,
    RunSQLAnalyzer,
    SeparateDatabaseAndStateAnalyzer,
)
from posthog.management.migration_analysis.policies import POSTHOG_POLICIES
from posthog.management.migration_analysis.utils import OperationCategorizer


class RiskAnalyzer:
    """
    Analyzes Django migration operations and assigns risk scores.

    Risk scoring rules:
    0: Safe - No contention risk (new tables, concurrent operations)
    1: Needs Review - Brief lock required, review for high-traffic tables
    2-3: Needs Review - Extended operations or performance impact
    4-5: Blocked - Table rewrites, breaks backwards compatibility, or can't rollback
    """

    # Registry of operation analyzers
    ANALYZERS = {
        "AddField": AddFieldAnalyzer(),
        "RemoveField": RemoveFieldAnalyzer(),
        "DeleteModel": DeleteModelAnalyzer(),
        "AlterField": AlterFieldAnalyzer(),
        "RenameField": RenameFieldAnalyzer(),
        "RenameModel": RenameModelAnalyzer(),
        "AlterModelTable": AlterModelTableAnalyzer(),
        "AddIndex": AddIndexAnalyzer(),
        "AddConstraint": AddConstraintAnalyzer(),
        "RunSQL": RunSQLAnalyzer(),
        "RunPython": RunPythonAnalyzer(),
        "CreateModel": CreateModelAnalyzer(),
        "AlterUniqueTogether": AlterUniqueTogetherAnalyzer(),
        "AlterIndexTogether": AlterIndexTogetherAnalyzer(),
        "RemoveIndex": RemoveIndexAnalyzer(),
        "SeparateDatabaseAndState": SeparateDatabaseAndStateAnalyzer(),
    }

    def analyze_migration(self, migration, path: str) -> MigrationRisk:
        """Analyze migration without migration loader context (for backwards compatibility)."""
        return self.analyze_migration_with_context(migration, path, loader=None)

    def analyze_migration_with_context(self, migration, path: str, loader=None) -> MigrationRisk:
        """
        Analyze migration with optional migration loader for enhanced validation.

        Args:
            migration: Django migration object
            path: Path to migration file (for reporting)
            loader: Optional Django MigrationLoader for checking migration history
        """
        # Collect newly created models for this migration (normalized to lowercase for case-insensitive matching)
        self.newly_created_models = {
            op.name.lower()
            for op in migration.operations
            if op.__class__.__name__ == "CreateModel" and hasattr(op, "name")
        }

        # Store loader for operations that need it
        self.loader = loader
        self.migration = migration

        operation_risks = []

        for op in migration.operations:
            risk = self.analyze_operation(op)

            # Skip AddIndex/AddConstraint on newly created tables - they're safe
            if self._is_safe_on_new_table(op, risk):
                continue

            operation_risks.append(risk)

            # Recursively analyze database_operations in SeparateDatabaseAndState
            if (
                op.__class__.__name__ == "SeparateDatabaseAndState"
                and hasattr(op, "database_operations")
                and op.database_operations
            ):
                parent_idx = len(operation_risks) - 1  # Index of the parent operation
                for db_op in op.database_operations:
                    db_risk = self.analyze_operation(db_op)
                    db_risk.parent_index = parent_idx
                    operation_risks.append(db_risk)

        # Check for dangerous operation combinations
        combination_risks = self.check_operation_combinations(migration, operation_risks)

        # Check PostHog policies
        policy_violations = self.check_policies(migration)

        # Build info messages
        info_messages = []
        if self.newly_created_models:
            info_messages.append(
                "ℹ️  Skipped operations on newly created tables (empty tables don't cause lock contention)."
            )

        return MigrationRisk(
            path=path,
            app=migration.app_label,
            name=migration.name,
            operations=operation_risks,
            combination_risks=combination_risks,
            policy_violations=policy_violations,
            info_messages=info_messages,
        )

    def _is_safe_on_new_table(self, op, risk: OperationRisk) -> bool:
        """Check if operation is safe because it's on a newly created table."""
        if risk.type not in ["AddIndex", "AddConstraint"]:
            return False
        model_name = risk.details.get("model") or getattr(op, "model_name", None)
        if model_name:
            model_name = model_name.lower()
        return model_name in self.newly_created_models

    def analyze_operation(self, op) -> OperationRisk:
        op_type = op.__class__.__name__

        # Look up specific analyzer for this operation type
        analyzer = self.ANALYZERS.get(op_type)

        if analyzer:
            # Pass migration context to RunSQLAnalyzer for DROP TABLE validation
            if op_type == "RunSQL" and hasattr(self, "migration") and hasattr(self, "loader"):
                return analyzer.analyze(op, migration=self.migration, loader=self.loader)  # type: ignore[call-arg]
            # Pass migration context to RenameModelAnalyzer for db_table check
            if op_type == "RenameModel" and hasattr(self, "migration"):
                return analyzer.analyze(op, migration=self.migration)  # type: ignore[call-arg]
            return analyzer.analyze(op)

        # Fallback for unscored operation types
        # Check if it's a known Django operation
        is_django_operation = op.__class__.__module__.startswith("django.db.migrations.operations")

        if is_django_operation:
            return OperationRisk(
                type=op_type,
                score=2,
                reason=f"Unscored Django operation: {op_type} (needs manual review)",
                details={},
            )

        return OperationRisk(
            type=op_type,
            score=2,
            reason=f"Unknown operation type: {op_type}",
            details={},
        )

    def check_operation_combinations(self, migration, operation_risks: list[OperationRisk]) -> list[str]:
        """
        Check for dangerous combinations of operations in a single migration.

        Dangerous patterns:
        1. RunSQL with DML (UPDATE/DELETE) + schema changes = long transaction with locks
        2. RunSQL + DDL should be isolated
        3. Multiple schema changes in non-atomic migration
        """
        categorizer = OperationCategorizer(operation_risks)

        warnings = []
        warnings.extend(self._check_dml_with_schema_changes(categorizer))
        warnings.extend(self._check_runpython_with_schema_changes(categorizer))
        warnings.extend(self._check_ddl_isolation(categorizer, operation_risks))
        warnings.extend(self._check_multiple_high_risk_ops(categorizer))
        warnings.extend(self._check_multiple_indexes(categorizer))
        warnings.extend(self._check_non_atomic_runsql(migration, categorizer))

        return warnings

    def _check_dml_with_schema_changes(self, categorizer: OperationCategorizer) -> list[str]:
        """Check for DML operations mixed with schema changes."""
        if not (categorizer.has_dml and categorizer.has_schema_changes):
            return []

        dml_refs = categorizer.format_operation_refs(categorizer.dml_ops)
        schema_refs = categorizer.format_operation_refs(categorizer.schema_ops)

        return [
            f"❌ CRITICAL: {dml_refs} + {schema_refs}    "
            "RunSQL with DML (UPDATE/DELETE/INSERT) combined with schema changes. "
            "This creates a long-running transaction that holds locks for the entire duration. "
            "Split into separate migrations: 1) schema changes, 2) data migration."
        ]

    def _check_runpython_with_schema_changes(self, categorizer: OperationCategorizer) -> list[str]:
        """Check for RunPython operations mixed with schema changes."""
        if not (categorizer.has_runpython and categorizer.has_schema_changes):
            return []

        runpython_refs = categorizer.format_operation_refs(categorizer.runpython_ops)
        schema_refs = categorizer.format_operation_refs(categorizer.schema_ops)

        return [
            f"❌ BLOCKED: {runpython_refs} + {schema_refs}    "
            "RunPython data migration combined with schema changes. "
            "Data migrations can hold locks during execution, especially on large tables. "
            "Split into separate migrations: 1) schema changes, 2) data migration."
        ]

    def _check_ddl_isolation(self, categorizer: OperationCategorizer, operation_risks: list) -> list[str]:
        """Check if DDL operations should be isolated."""
        if not categorizer.has_ddl or len(operation_risks) <= 1:
            return []

        ddl_refs = categorizer.format_operation_refs(categorizer.ddl_ops)

        return [
            f"❌ BLOCKED: {ddl_refs} mixed with other operations    "
            "RunSQL with DDL (CREATE INDEX/ALTER TABLE) should be isolated in their own migration "
            "to avoid lock conflicts."
        ]

    def _check_multiple_high_risk_ops(self, categorizer: OperationCategorizer) -> list[str]:
        """Check for multiple high-risk operations in one migration."""
        if not categorizer.has_multiple_high_risk:
            return []

        high_risk_refs = categorizer.format_operation_refs(categorizer.high_risk_ops)

        return [
            f"❌ BLOCKED: Multiple high-risk operations in one migration: {high_risk_refs}    "
            "Each high-risk operation (score 4+) should be isolated to make rollback easier and reduce deployment risk. "
            "Consider splitting into separate migrations."
        ]

    def _check_multiple_indexes(self, categorizer: OperationCategorizer) -> list[str]:
        """Check for multiple index creations in one migration."""
        if not categorizer.has_multiple_indexes:
            return []

        index_refs = categorizer.format_operation_refs(categorizer.addindex_ops)

        return [
            f"❌ BLOCKED: Multiple index creations in one migration: {index_refs}    "
            "Creating multiple indexes can cause I/O overload and extended lock times. "
            "Consider splitting into separate migrations to reduce system load."
        ]

    def _check_non_atomic_runsql(self, migration, categorizer: OperationCategorizer) -> list[str]:
        """Check for non-atomic migrations with RunSQL."""
        if not categorizer.runsql_ops or getattr(migration, "atomic", True):
            return []

        # Skip INFO warning if all RunSQL operations are safe CONCURRENTLY operations
        all_safe_concurrent = all(
            op_risk.score == 1 and "CONCURRENTLY" in str(op_risk.details.get("sql", "")).upper()
            for _, op_risk in categorizer.runsql_ops
        )
        if all_safe_concurrent:
            return []  # No need to warn about atomic=False for safe concurrent operations

        return ["⚠️  INFO: Migration is marked atomic=False. Ensure data migrations handle failures correctly."]

    def check_policies(self, migration) -> list[str]:
        """Check migration against PostHog coding policies."""
        violations = []

        for policy in POSTHOG_POLICIES:
            # Check migration-level policies (which internally check operations as needed)
            violations.extend(policy.check_migration(migration))

        return violations
