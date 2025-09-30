"""Operation-specific analyzers for Django migration operations."""

from django.db import models

from posthog.management.migration_analysis.models import OperationRisk
from posthog.management.migration_analysis.utils import VolatileFunctionDetector


class OperationAnalyzer:
    """Base class for operation-specific analyzers"""

    operation_type: str
    default_score: int = 2

    def analyze(self, op) -> OperationRisk:
        """Override in subclasses to provide specific analysis logic"""
        return OperationRisk(
            type=self.operation_type,
            score=self.default_score,
            reason=f"{self.operation_type} operation",
            details={},
        )


class AddFieldAnalyzer(OperationAnalyzer):
    operation_type = "AddField"

    def analyze(self, op) -> OperationRisk:
        field = op.field
        is_nullable = field.null or getattr(field, "blank", False)

        if is_nullable:
            return self._analyze_nullable_field(op)

        has_default = field.default != models.NOT_PROVIDED
        if not has_default:
            return self._risk_not_null_no_default(op)

        return self._analyze_not_null_with_default(op, field)

    def _analyze_nullable_field(self, op) -> OperationRisk:
        """Nullable fields are always safe."""
        return OperationRisk(
            type=self.operation_type,
            score=0,
            reason="Adding nullable field is safe",
            details={"model": op.model_name, "field": op.name},
        )

    def _risk_not_null_no_default(self, op) -> OperationRisk:
        """NOT NULL without default requires table rewrite with lock."""
        return OperationRisk(
            type=self.operation_type,
            score=5,
            reason="Adding NOT NULL field without default locks table",
            details={"model": op.model_name, "field": op.name},
        )

    def _analyze_not_null_with_default(self, op, field) -> OperationRisk:
        """Analyze NOT NULL field with default value."""
        if not callable(field.default):
            return self._risk_constant_default(op)

        return self._analyze_callable_default(op, field)

    def _risk_constant_default(self, op) -> OperationRisk:
        """Constant defaults are safe in PostgreSQL 11+."""
        return OperationRisk(
            type=self.operation_type,
            score=1,
            reason="Adding NOT NULL field with constant default (safe in PG11+)",
            details={"model": op.model_name, "field": op.name},
        )

    def _analyze_callable_default(self, op, field) -> OperationRisk:
        """Analyze callable defaults (functions)."""
        default_name = getattr(field.default, "__name__", str(field.default))

        if VolatileFunctionDetector.is_volatile(default_name):
            return OperationRisk(
                type=self.operation_type,
                score=5,
                reason=f"Adding NOT NULL field with volatile default ({default_name}) rewrites entire table",
                details={"model": op.model_name, "field": op.name, "default": default_name},
            )

        return OperationRisk(
            type=self.operation_type,
            score=2,
            reason=f"Adding NOT NULL field with callable default ({default_name}) - verify it's stable",
            details={"model": op.model_name, "field": op.name, "default": default_name},
        )


class RemoveFieldAnalyzer(OperationAnalyzer):
    operation_type = "RemoveField"
    default_score = 5

    def analyze(self, op) -> OperationRisk:
        return OperationRisk(
            type=self.operation_type,
            score=5,
            reason="Dropping column breaks backwards compatibility and can't rollback",
            details={"model": op.model_name, "field": op.name},
        )


class DeleteModelAnalyzer(OperationAnalyzer):
    operation_type = "DeleteModel"
    default_score = 5

    def analyze(self, op) -> OperationRisk:
        return OperationRisk(
            type=self.operation_type,
            score=5,
            reason="Dropping table breaks backwards compatibility and can't rollback",
            details={"model": op.name},
        )


class AlterFieldAnalyzer(OperationAnalyzer):
    operation_type = "AlterField"
    default_score = 3

    def analyze(self, op) -> OperationRisk:
        field = op.field
        field_type = field.__class__.__name__

        # Check for specific dangerous alterations
        # Note: We can't easily compare old vs new field without loading the old migration state,
        # so we look for markers that suggest dangerous changes

        # Setting NOT NULL on existing column is very dangerous
        if not field.null and hasattr(field, "_null_changed"):
            return OperationRisk(
                type=self.operation_type,
                score=5,
                reason="Setting NOT NULL on existing column requires full table scan and locks table",
                details={"model": op.model_name, "field": op.name},
            )

        # Changing to a more restrictive max_length could be dangerous
        # (would need validation), but we can't detect this without old state

        # Default case: needs review
        return OperationRisk(
            type=self.operation_type,
            score=3,
            reason="Field alteration may cause table locks or data loss (check if changing type or constraints)",
            details={"model": op.model_name, "field": op.name, "field_type": field_type},
        )


class RenameFieldAnalyzer(OperationAnalyzer):
    operation_type = "RenameField"
    default_score = 4

    def analyze(self, op) -> OperationRisk:
        return OperationRisk(
            type=self.operation_type,
            score=4,
            reason="Renaming column breaks old code during deployment",
            details={"model": op.model_name, "old": op.old_name, "new": op.new_name},
        )


class RenameModelAnalyzer(OperationAnalyzer):
    operation_type = "RenameModel"
    default_score = 4

    def analyze(self, op) -> OperationRisk:
        return OperationRisk(
            type=self.operation_type,
            score=4,
            reason="Renaming table breaks old code during deployment",
            details={"old": op.old_name, "new": op.new_name},
        )


class AlterModelTableAnalyzer(OperationAnalyzer):
    operation_type = "AlterModelTable"
    default_score = 4

    def analyze(self, op) -> OperationRisk:
        return OperationRisk(
            type=self.operation_type,
            score=4,
            reason="Changing table name breaks old code during deployment",
            details={},
        )


class AddIndexAnalyzer(OperationAnalyzer):
    operation_type = "AddIndex"
    default_score = 0

    def analyze(self, op) -> OperationRisk:
        if hasattr(op, "index"):
            concurrent = getattr(op.index, "concurrent", False)
            if not concurrent:
                return OperationRisk(
                    type=self.operation_type,
                    score=4,
                    reason="Non-concurrent index creation locks table",
                    details={},
                )
        return OperationRisk(
            type=self.operation_type,
            score=0,
            reason="Concurrent index is safe",
            details={},
        )


class AddConstraintAnalyzer(OperationAnalyzer):
    operation_type = "AddConstraint"
    default_score = 3

    def analyze(self, op) -> OperationRisk:
        return OperationRisk(
            type=self.operation_type,
            score=3,
            reason="Adding constraint may lock table (use NOT VALID pattern)",
            details={},
        )


class RunSQLAnalyzer(OperationAnalyzer):
    operation_type = "RunSQL"
    default_score = 2

    def analyze(self, op) -> OperationRisk:
        sql = str(op.sql).upper()
        if "DROP" in sql:
            return OperationRisk(
                type=self.operation_type,
                score=5,
                reason="RunSQL with DROP is dangerous",
                details={"sql": sql},
            )
        elif "UPDATE" in sql or "DELETE" in sql:
            return OperationRisk(
                type=self.operation_type,
                score=4,
                reason="RunSQL with UPDATE/DELETE needs careful review for locking",
                details={"sql": sql},
            )
        elif "ALTER" in sql:
            return OperationRisk(
                type=self.operation_type,
                score=3,
                reason="RunSQL with ALTER may cause locks",
                details={"sql": sql},
            )
        else:
            return OperationRisk(
                type=self.operation_type,
                score=2,
                reason="RunSQL operation needs review",
                details={"sql": sql},
            )


class RunPythonAnalyzer(OperationAnalyzer):
    operation_type = "RunPython"
    default_score = 2

    def analyze(self, op) -> OperationRisk:
        return OperationRisk(
            type=self.operation_type,
            score=2,
            reason="RunPython data migration needs review for performance",
            details={},
        )


class CreateModelAnalyzer(OperationAnalyzer):
    operation_type = "CreateModel"
    default_score = 0

    def analyze(self, op) -> OperationRisk:
        return OperationRisk(
            type=self.operation_type,
            score=0,
            reason="Creating new table is safe",
            details={"model": op.name},
        )


class AlterUniqueTogetherAnalyzer(OperationAnalyzer):
    operation_type = "AlterUniqueTogether"
    default_score = 3

    def analyze(self, op) -> OperationRisk:
        return OperationRisk(
            type=self.operation_type,
            score=3,
            reason="Altering unique constraints may lock table",
            details={},
        )


class AlterIndexTogetherAnalyzer(OperationAnalyzer):
    operation_type = "AlterIndexTogether"
    default_score = 3

    def analyze(self, op) -> OperationRisk:
        return OperationRisk(
            type=self.operation_type,
            score=3,
            reason="Altering indexes may lock table",
            details={},
        )


class RemoveIndexAnalyzer(OperationAnalyzer):
    operation_type = "RemoveIndex"
    default_score = 0

    def analyze(self, op) -> OperationRisk:
        return OperationRisk(
            type=self.operation_type,
            score=0,
            reason="Removing index is safe (doesn't block reads/writes)",
            details={"model": op.model_name if hasattr(op, "model_name") else "unknown"},
        )


class SeparateDatabaseAndStateAnalyzer(OperationAnalyzer):
    operation_type = "SeparateDatabaseAndState"
    default_score = 2

    def analyze(self, op) -> OperationRisk:
        # This operation separates database operations from state operations
        # We should analyze the database_operations for actual risk
        # The state_operations are just Django model state changes

        if hasattr(op, "database_operations") and op.database_operations:
            # Get count of database operations to note in details
            db_op_count = len(op.database_operations)
            db_op_types = [db_op.__class__.__name__ for db_op in op.database_operations]

            return OperationRisk(
                type=self.operation_type,
                score=2,
                reason=f"Contains {db_op_count} database operation(s) - review database_operations for actual risk",
                details={"database_operations": ", ".join(db_op_types)},
            )

        return OperationRisk(
            type=self.operation_type,
            score=0,
            reason="Only state operations (no database changes)",
            details={},
        )
