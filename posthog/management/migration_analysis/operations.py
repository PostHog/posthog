"""Operation-specific analyzers for Django migration operations."""

from django.db import models

from posthog.management.migration_analysis.models import OperationRisk


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
        has_default = field.default != models.NOT_PROVIDED

        if not is_nullable and not has_default:
            return OperationRisk(
                type=self.operation_type,
                score=5,
                reason="Adding NOT NULL field without default locks table",
                details={"model": op.model_name, "field": op.name},
            )
        elif not is_nullable and has_default:
            return OperationRisk(
                type=self.operation_type,
                score=1,
                reason="Adding NOT NULL field with default (verify it's a constant)",
                details={"model": op.model_name, "field": op.name},
            )
        else:
            return OperationRisk(
                type=self.operation_type,
                score=0,
                reason="Adding nullable field is safe",
                details={"model": op.model_name, "field": op.name},
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
        return OperationRisk(
            type=self.operation_type,
            score=3,
            reason="Field alteration may cause table locks or data loss",
            details={"model": op.model_name, "field": op.name},
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
            details={},
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
