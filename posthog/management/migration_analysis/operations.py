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

        # Only null=True matters for database safety (blank=True is just form validation)
        if field.null:
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
            guidance="""Add NOT NULL fields in 3 steps:
1. Add column as nullable (`null=True`), deploy
2. Backfill data for all rows
3. Add NOT NULL constraint (or use `ALTER COLUMN SET NOT NULL` in RunSQL), deploy""",
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
                guidance="""Volatile defaults (like `uuid4()`, `now()`, `random()`) require a table rewrite. Deploy in 3 steps:
1. Add column as nullable without default, deploy
2. Use RunSQL to backfill: `UPDATE table SET column = gen_random_uuid() WHERE column IS NULL`
3. Add NOT NULL constraint, deploy""",
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
            guidance="""**Never drop columns directly.** Deploy in steps:
1. Remove all code references to the column, deploy
2. Wait at least one full deploy cycle to ensure no rollback needed
3. Optionally drop column in a later migration (consider leaving unused columns indefinitely)""",
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
            guidance="""**Never drop tables directly.** Deploy in steps:
1. Remove all code references to the model, deploy
2. Wait at least one full deploy cycle to ensure no rollback needed
3. Optionally drop table in a later migration (consider leaving unused tables indefinitely)""",
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
            guidance="""**Don't rename columns in production** - accept the bad name. If you must: 1) Add new column, deploy code that writes to both but reads from old. 2) Backfill data. 3) Deploy code that reads from new. 4) Never drop the old column - leave it forever.""",
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
            guidance="""**Don't rename tables in production** - accept the bad name. If you must: Use views (1. Rename table, create view with old name. 2. Deploy code. 3. Drop view). Or expand-contract (1. Create new table, write to both. 2. Backfill. 3. Read from new. 4. Never drop old table).""",
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
                    guidance="Use migrations.AddIndex with index=models.Index(..., name='...', fields=[...]) and set concurrent=True in the index. In PostgreSQL this requires a separate migration with atomic=False.",
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
            guidance="""Add constraints without locking in 2 steps:
1. Add constraint with `NOT VALID` using RunSQL: `ALTER TABLE ... ADD CONSTRAINT ... CHECK (...) NOT VALID`
2. In a separate migration, validate: `ALTER TABLE ... VALIDATE CONSTRAINT ...`

This allows writes to continue while validation happens in the background.""",
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
                guidance="""**Critical for large tables:** UPDATE/DELETE can lock tables for extended periods.
- Use batching: Update/delete in chunks of 1000-10000 rows with LIMIT and loop
- Add `WHERE` clauses to limit scope
- Consider using `SELECT ... FOR UPDATE SKIP LOCKED` for concurrent updates
- Monitor query duration in production before deploying to large tables
- For very large updates, consider using a background job instead of a migration""",
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
            guidance="""**Large-scale considerations for data migrations:**
- Use `.iterator()` for large querysets to avoid loading all rows into memory
- Process in batches: `for obj in Model.objects.all().iterator(chunk_size=1000)`
- Use `.bulk_update()` instead of saving individual objects
- Add progress logging every N rows for visibility
- Test on production-sized data before deploying
- Consider timeout limits - migrations blocking deployment for >10min are problematic""",
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
    default_score = 0

    def analyze(self, op, analyzer=None) -> OperationRisk:
        """
        Analyze SeparateDatabaseAndState operation.

        Note: The actual risk comes from database_operations inside this wrapper.
        The RiskAnalyzer will recursively analyze those operations separately.
        """
        if not hasattr(op, "database_operations") or not op.database_operations:
            return OperationRisk(
                type=self.operation_type,
                score=0,
                reason="Only state operations (no database changes)",
                details={},
            )

        db_op_types = [db_op.__class__.__name__ for db_op in op.database_operations]

        return OperationRisk(
            type=self.operation_type,
            score=0,
            reason=f"Wrapper operation - see nested operations for risk: {', '.join(db_op_types)}",
            details={"database_operations": ", ".join(db_op_types)},
        )
