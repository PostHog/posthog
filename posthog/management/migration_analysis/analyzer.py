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
    0-1: Safe - No locks, backwards compatible
    2-3: Needs Review - May have performance impact or needs careful deployment
    4-5: Blocked - Causes locks, breaks backwards compatibility, or can't rollback
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
        operation_risks = []

        for op in migration.operations:
            risk = self.analyze_operation(op)
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

        return MigrationRisk(
            path=path,
            app=migration.app_label,
            name=migration.name,
            operations=operation_risks,
            combination_risks=combination_risks,
            policy_violations=policy_violations,
        )

    def analyze_operation(self, op) -> OperationRisk:
        op_type = op.__class__.__name__

        # Look up specific analyzer for this operation type
        analyzer = self.ANALYZERS.get(op_type)

        if analyzer:
            return analyzer.analyze(op)

        # Fallback for unknown operation types
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
            f"⚠️  WARNING: {runpython_refs} + {schema_refs}    "
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
            f"⚠️  WARNING: {ddl_refs} mixed with other operations    "
            "RunSQL with DDL (CREATE INDEX/ALTER TABLE) should be isolated in their own migration "
            "to avoid lock conflicts."
        ]

    def _check_multiple_high_risk_ops(self, categorizer: OperationCategorizer) -> list[str]:
        """Check for multiple high-risk operations in one migration."""
        if not categorizer.has_multiple_high_risk:
            return []

        high_risk_refs = categorizer.format_operation_refs(categorizer.high_risk_ops)

        return [
            f"⚠️  WARNING: Multiple high-risk operations in one migration: {high_risk_refs}    "
            "Each high-risk operation (score 4+) should be isolated to make rollback easier and reduce deployment risk. "
            "Consider splitting into separate migrations."
        ]

    def _check_multiple_indexes(self, categorizer: OperationCategorizer) -> list[str]:
        """Check for multiple index creations in one migration."""
        if not categorizer.has_multiple_indexes:
            return []

        index_refs = categorizer.format_operation_refs(categorizer.addindex_ops)

        return [
            f"⚠️  WARNING: Multiple index creations in one migration: {index_refs}    "
            "Creating multiple indexes can cause I/O overload and extended lock times. "
            "Consider splitting into separate migrations to reduce system load."
        ]

    def _check_non_atomic_runsql(self, migration, categorizer: OperationCategorizer) -> list[str]:
        """Check for non-atomic migrations with RunSQL."""
        if not categorizer.runsql_ops or getattr(migration, "atomic", True):
            return []

        return ["⚠️  INFO: Migration is marked atomic=False. Ensure data migrations handle failures correctly."]

    def check_policies(self, migration) -> list[str]:
        """Check migration against PostHog coding policies."""
        violations = []

        for policy in POSTHOG_POLICIES:
            # Check migration-level policies (which internally check operations as needed)
            violations.extend(policy.check_migration(migration))

        return violations
