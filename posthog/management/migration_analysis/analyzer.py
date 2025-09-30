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
    RenameFieldAnalyzer,
    RenameModelAnalyzer,
    RunPythonAnalyzer,
    RunSQLAnalyzer,
)


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
    }

    def analyze_migration(self, migration, path: str) -> MigrationRisk:
        operation_risks = []

        for op in migration.operations:
            risk = self.analyze_operation(op)
            operation_risks.append(risk)

        # Check for dangerous operation combinations
        combination_risks = self.check_operation_combinations(migration, operation_risks)

        return MigrationRisk(
            path=path,
            app=migration.app_label,
            name=migration.name,
            operations=operation_risks,
            combination_risks=combination_risks,
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
        warnings = []

        # Categorize operations with indices for reference
        has_runsql_dml = False
        has_runsql_ddl = False
        has_schema_changes = False
        runsql_ops = []
        schema_change_ops = []
        dml_ops = []
        ddl_ops = []

        for idx, op_risk in enumerate(operation_risks):
            if op_risk.type == "RunSQL":
                runsql_ops.append((idx, op_risk))
                # Check SQL content
                sql_upper = str(op_risk.details.get("sql", "")).upper() if op_risk.details else ""
                if any(kw in sql_upper for kw in ["UPDATE", "DELETE", "INSERT"]):
                    has_runsql_dml = True
                    dml_ops.append((idx, op_risk))
                if any(kw in sql_upper for kw in ["CREATE INDEX", "ALTER TABLE", "ADD COLUMN"]):
                    has_runsql_ddl = True
                    ddl_ops.append((idx, op_risk))

            # Schema-changing operations
            if op_risk.type in [
                "AddField",
                "RemoveField",
                "AlterField",
                "RenameField",
                "AddIndex",
                "AddConstraint",
                "CreateModel",
                "DeleteModel",
            ]:
                has_schema_changes = True
                schema_change_ops.append((idx, op_risk))

        # Check for dangerous combinations
        if has_runsql_dml and has_schema_changes:
            # Build reference to involved operations
            dml_refs = ", ".join(f"#{idx+1} {op.type}" for idx, op in dml_ops)
            schema_refs = ", ".join(f"#{idx+1} {op.type}" for idx, op in schema_change_ops)
            warnings.append(
                f"❌ CRITICAL: {dml_refs} + {schema_refs}\n"
                "   RunSQL with DML (UPDATE/DELETE/INSERT) combined with schema changes. "
                "This creates a long-running transaction that holds locks for the entire duration. "
                "Split into separate migrations: 1) schema changes, 2) data migration."
            )

        if has_runsql_ddl and len(operation_risks) > 1:
            ddl_refs = ", ".join(f"#{idx+1} {op.type}" for idx, op in ddl_ops)
            warnings.append(
                f"⚠️  WARNING: {ddl_refs} mixed with other operations\n"
                "   RunSQL with DDL (CREATE INDEX/ALTER TABLE) should be isolated in their own migration "
                "to avoid lock conflicts."
            )

        if len(runsql_ops) > 0 and not getattr(migration, "atomic", True):
            warnings.append(
                "⚠️  INFO: Migration is marked atomic=False. Ensure data migrations handle failures correctly."
            )

        return warnings
