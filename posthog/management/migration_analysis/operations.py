"""Operation-specific analyzers for Django migration operations."""

import re
from typing import Any, Optional

from django.db import models

from posthog.management.migration_analysis.models import OperationRisk
from posthog.management.migration_analysis.utils import VolatileFunctionDetector, check_drop_properly_staged

# Base URL for migration safety documentation
SAFE_MIGRATIONS_DOCS_URL = "https://github.com/PostHog/posthog/blob/master/docs/safe-django-migrations.md"


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
            guidance=f"""Add NOT NULL fields in 3 phases:
1. Add column as nullable, deploy
2. Backfill data for all rows
3. Add NOT NULL constraint, deploy

[See the migration safety guide]({SAFE_MIGRATIONS_DOCS_URL}#adding-not-null-columns)""",
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
                guidance=f"""Volatile defaults (like `uuid4()`, `now()`, `random()`) require a table rewrite. Deploy in 3 phases:
1. Add column as nullable, deploy
2. Backfill data for all rows
3. Add NOT NULL constraint, deploy

[See the migration safety guide]({SAFE_MIGRATIONS_DOCS_URL}#adding-not-null-columns)""",
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
            guidance=f"""Multi-phase column drop:
1. Remove field from Django model (keeps column in DB)
2. Wait at least one full deployment cycle
3. Optionally drop column with RemoveField

[See the migration safety guide]({SAFE_MIGRATIONS_DOCS_URL}#dropping-columns)""",
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
            guidance=f"""Use SeparateDatabaseAndState for multi-phase drops:
1. Remove model from Django state (state_operations only)
2. Wait at least one full deployment cycle
3. Optionally drop table with RunSQL

[See the migration safety guide]({SAFE_MIGRATIONS_DOCS_URL}#dropping-tables)""",
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
            guidance=f"""Don't rename columns in production. Use `db_column` to map a better Python name to the existing database column instead.

[See the migration safety guide]({SAFE_MIGRATIONS_DOCS_URL}#renaming-columns)""",
        )


class RenameModelAnalyzer(OperationAnalyzer):
    operation_type = "RenameModel"
    default_score = 4

    def analyze(self, op, migration=None) -> OperationRisk:
        # Check if model has explicit db_table set (makes rename safe)
        has_db_table, db_table_name = self._check_db_table_set(op, migration)

        if has_db_table:
            return OperationRisk(
                type=self.operation_type,
                score=0,
                reason="Model rename is safe (db_table explicitly set, no table rename)",
                details={"old": op.old_name, "new": op.new_name, "db_table": db_table_name},
                guidance=f"""✅ Safe rename: Model has explicit `db_table` in Meta, so the database table name doesn't change. Only Python code references change.""",
            )

        return OperationRisk(
            type=self.operation_type,
            score=4,
            reason="Renaming table breaks old code during deployment",
            details={"old": op.old_name, "new": op.new_name},
            guidance=f"""Don't rename tables in production - accept the original name. Renaming creates significant complexity and risk for minimal benefit.

[See the migration safety guide]({SAFE_MIGRATIONS_DOCS_URL}#renaming-tables)""",
        )

    def _check_db_table_set(self, op, migration) -> tuple[bool, str | None]:
        """
        Check if the model rename is safe (table name doesn't change).

        Django's RenameModel compares old_model._meta.db_table vs new_model._meta.db_table.
        If they're the same, alter_db_table is a no-op.

        This checks:
        1. Try to get both old and new model from registry
        2. Compare their db_table values
        3. Only return SAFE if both have same db_table

        We try both old and new model names since either might exist in the app registry:
        - Old name exists: before migration is applied
        - New name exists: after migration is applied or in test environment

        Returns:
            tuple: (is_safe_rename, db_table_name)
        """
        if not migration:
            return (False, None)

        try:
            from django.apps import apps

            app_label = migration.app_label

            # Try to get db_table from both old and new models
            old_db_table = None
            new_db_table = None

            # Try old model name
            try:
                old_model = apps.get_model(app_label, op.old_name)
                # Use model._meta.model_name which has proper formatting (e.g., "task_progress" not "taskprogress")
                auto_generated_for_old = f"{app_label}_{old_model._meta.model_name}"
                # Only consider it if db_table is explicitly set (differs from auto-generated)
                if old_model._meta.db_table != auto_generated_for_old:
                    old_db_table = old_model._meta.db_table
            except LookupError:
                pass

            # Try new model name
            try:
                new_model = apps.get_model(app_label, op.new_name)
                # Use model._meta.model_name which has proper formatting
                auto_generated_for_new = f"{app_label}_{new_model._meta.model_name}"
                # Only consider it if db_table is explicitly set (differs from auto-generated)
                if new_model._meta.db_table != auto_generated_for_new:
                    new_db_table = new_model._meta.db_table
            except LookupError:
                pass

            # If we found both and they match, it's safe
            if old_db_table and new_db_table and old_db_table == new_db_table:
                return (True, old_db_table)

            # If we only found one model with explicit db_table, assume it's the same
            # (common case: before/after migration, only one model exists)
            if old_db_table or new_db_table:
                return (True, old_db_table or new_db_table)

            # Neither model found or no explicit db_table
            return (False, None)
        except Exception:
            # If anything goes wrong, assume not safe
            return (False, None)


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
        model_name = getattr(op, "model_name", None)
        if hasattr(op, "index"):
            concurrent = getattr(op.index, "concurrent", False)
            if not concurrent:
                return OperationRisk(
                    type=self.operation_type,
                    score=4,
                    reason="Non-concurrent index creation locks table",
                    details={"model": model_name},
                    guidance=f"""Use AddIndexConcurrently for existing large tables (requires atomic=False).

[See the migration safety guide]({SAFE_MIGRATIONS_DOCS_URL}#adding-indexes)""",
                )
        return OperationRisk(
            type=self.operation_type,
            score=0,
            reason="Concurrent index is safe",
            details={"model": model_name},
        )


class AddConstraintAnalyzer(OperationAnalyzer):
    operation_type = "AddConstraint"
    default_score = 3

    def analyze(self, op) -> OperationRisk:
        model_name = getattr(op, "model_name", None)
        return OperationRisk(
            type=self.operation_type,
            score=3,
            reason="Adding constraint may lock table (use NOT VALID pattern)",
            details={"model": model_name},
            guidance=f"""Add constraints in 2 phases without locking:
1. Add constraint with NOT VALID (instant, validates new rows only)
2. Validate constraint in separate migration (scans table with non-blocking lock)

[See the migration safety guide]({SAFE_MIGRATIONS_DOCS_URL}#adding-constraints)""",
        )


class RunSQLAnalyzer(OperationAnalyzer):
    operation_type = "RunSQL"
    default_score = 2

    def analyze(self, op, migration: Optional[Any] = None, loader: Optional[Any] = None) -> OperationRisk:
        sql = str(op.sql).upper()

        # Check for CONCURRENTLY operations first (these are safe)
        # This must come before DROP check to avoid flagging DROP INDEX CONCURRENTLY as dangerous
        if "CONCURRENTLY" in sql:
            if "CREATE" in sql and "INDEX" in sql:
                if "IF NOT EXISTS" in sql:
                    return OperationRisk(
                        type=self.operation_type,
                        score=1,
                        reason="CREATE INDEX CONCURRENTLY is safe (non-blocking)",
                        details={"sql": sql},
                    )
                return OperationRisk(
                    type=self.operation_type,
                    score=2,
                    reason="CREATE INDEX CONCURRENTLY is safe (non-blocking)",
                    details={"sql": sql},
                    guidance="Add IF NOT EXISTS for idempotency: CREATE INDEX CONCURRENTLY IF NOT EXISTS",
                )
            elif "DROP" in sql and "INDEX" in sql:
                if "IF EXISTS" in sql:
                    return OperationRisk(
                        type=self.operation_type,
                        score=1,
                        reason="DROP INDEX CONCURRENTLY is safe (non-blocking)",
                        details={"sql": sql},
                    )
                return OperationRisk(
                    type=self.operation_type,
                    score=2,
                    reason="DROP INDEX CONCURRENTLY is safe (non-blocking)",
                    details={"sql": sql},
                    guidance="Add IF EXISTS for idempotency: DROP INDEX CONCURRENTLY IF EXISTS",
                )
            elif "REINDEX" in sql:
                return OperationRisk(
                    type=self.operation_type,
                    score=1,
                    reason="REINDEX CONCURRENTLY is safe (non-blocking)",
                    details={"sql": sql},
                )

        # Check for constraint operations (before general ALTER/DROP checks)
        if "ADD" in sql and "CONSTRAINT" in sql and "USING INDEX" in sql:
            return OperationRisk(
                type=self.operation_type,
                score=0,
                reason="ADD CONSTRAINT ... USING INDEX is instant (just renames existing index to constraint)",
                details={"sql": sql},
                guidance="This operation only updates metadata - the index already exists and enforces uniqueness.",
            )

        if "ADD" in sql and "CONSTRAINT" in sql and "NOT VALID" in sql:
            return OperationRisk(
                type=self.operation_type,
                score=1,
                reason="ADD CONSTRAINT ... NOT VALID is safe (validates new rows only, no table scan)",
                details={"sql": sql},
                guidance="Follow up with VALIDATE CONSTRAINT in a later migration to check existing rows.",
            )

        if "VALIDATE" in sql and "CONSTRAINT" in sql:
            return OperationRisk(
                type=self.operation_type,
                score=2,
                reason="VALIDATE CONSTRAINT can be slow but non-blocking (allows reads/writes)",
                details={"sql": sql},
                guidance="Long-running on large tables but uses SHARE UPDATE EXCLUSIVE lock (allows normal operations).",
            )

        if "DROP" in sql and "CONSTRAINT" in sql:
            # Check for CASCADE which can be expensive
            if "CASCADE" in sql:
                return OperationRisk(
                    type=self.operation_type,
                    score=3,
                    reason="DROP CONSTRAINT CASCADE may be slow (drops dependent objects)",
                    details={"sql": sql},
                )
            return OperationRisk(
                type=self.operation_type,
                score=1,
                reason="DROP CONSTRAINT is fast (just removes metadata)",
                details={"sql": sql},
            )

        # Check for metadata-only operations (safe and instant)
        if "COMMENT ON" in sql:
            return OperationRisk(
                type=self.operation_type,
                score=0,
                reason="COMMENT ON is metadata-only (instant, no locks)",
                details={"sql": sql},
            )

        if "SET STATISTICS" in sql or "SET (FILLFACTOR" in sql:
            return OperationRisk(
                type=self.operation_type,
                score=0,
                reason="Metadata-only operation (instant, no locks)",
                details={"sql": sql},
            )

        if "DROP" in sql:
            # Check for DROP COLUMN first (before DROP TABLE check)
            # ALTER TABLE ... DROP COLUMN can contain both "TABLE" and "DROP" keywords
            # Use regex to verify it's actually ALTER TABLE ... DROP COLUMN (not just "COLUMN" in table name)
            column_match = re.search(
                r"ALTER\s+TABLE\s+([a-zA-Z0-9_]+)\s+DROP\s+COLUMN\s+(?:IF\s+EXISTS\s+)?([a-zA-Z0-9_]+)", sql
            )

            if column_match:
                if migration and loader:
                    table_name = column_match.group(1).lower()
                    column_name = column_match.group(2).lower()

                    # Check if properly staged (field removed from state in prior migration)
                    if check_drop_properly_staged("column", table_name, migration, loader, field_name=column_name):
                        return OperationRisk(
                            type=self.operation_type,
                            score=2,
                            reason="DROP COLUMN IF EXISTS - properly staged (prior state removal found)",
                            details={"sql": sql, "table": table_name, "column": column_name},
                            guidance=f"""✅ **Validated staged drop:** Found prior SeparateDatabaseAndState that removed field from state.

Remaining checklist:
- Ensure all code references removed (models, serializers, API)
- Waited at least one full deployment cycle since state removal
- Verify column is not used in queries or indexes

[See the migration safety guide]({SAFE_MIGRATIONS_DOCS_URL}#dropping-columns)""",
                        )

                # Not properly staged or can't validate
                return OperationRisk(
                    type=self.operation_type,
                    score=5,
                    reason="DROP COLUMN - no prior state removal found",
                    details={"sql": sql},
                    guidance=f"""❌ **Missing state removal:** Could not find prior SeparateDatabaseAndState that removed this field.

Safe pattern requires:
1. Prior migration with SeparateDatabaseAndState removes field from Django state
2. All code references removed (models, serializers, API)
3. Wait at least one full deployment cycle
4. Then DROP COLUMN in later migration with RunSQL

[See the migration safety guide]({SAFE_MIGRATIONS_DOCS_URL}#dropping-columns)""",
                )

            # Special case: DROP TABLE IF EXISTS may be safe if following proper staging pattern
            if "TABLE" in sql and "IF EXISTS" in sql:
                # Extract table name from the DROP statement
                table_name_match = re.search(r"DROP\s+TABLE\s+IF\s+EXISTS\s+([a-zA-Z0-9_]+)", sql)
                if table_name_match and migration and loader:
                    table_name = table_name_match.group(1).lower()

                    # Check if properly staged (model removed from state in prior migration)
                    if check_drop_properly_staged("table", table_name, migration, loader):
                        return OperationRisk(
                            type=self.operation_type,
                            score=2,
                            reason="DROP TABLE IF EXISTS - properly staged (prior state removal found)",
                            details={"sql": sql, "table": table_name},
                            guidance=f"""✅ **Validated staged drop:** Found prior SeparateDatabaseAndState that removed model from state.

Remaining checklist:
- Ensure all code references removed (API, models, imports)
- Waited at least one full deployment cycle since state removal
- No other models reference this table via foreign keys

[See the migration safety guide]({SAFE_MIGRATIONS_DOCS_URL}#dropping-tables)""",
                        )

                # Not properly staged or can't validate
                return OperationRisk(
                    type=self.operation_type,
                    score=5,
                    reason="DROP TABLE IF EXISTS - no prior state removal found",
                    details={"sql": sql},
                    guidance=f"""❌ **Missing state removal:** Could not find prior SeparateDatabaseAndState that removed this model.

Safe pattern requires:
1. Prior migration with SeparateDatabaseAndState removes model from Django state
2. All code references removed (API, models, imports)
3. Wait at least one full deployment cycle
4. Then DROP TABLE in later migration

[See the migration safety guide]({SAFE_MIGRATIONS_DOCS_URL}#dropping-tables)""",
                )

            # Check if using IF EXISTS for other DROP operations (safer but still dangerous)
            if "IF EXISTS" in sql:
                return OperationRisk(
                    type=self.operation_type,
                    score=5,
                    reason="RunSQL with DROP is dangerous",
                    details={"sql": sql},
                    guidance="Good: using IF EXISTS makes this idempotent. Consider using DROP ... CONCURRENTLY for indexes to avoid locks.",
                )
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
                guidance=f"""Break large updates into batches to avoid long locks:
- Batch size: 1,000-10,000 rows per batch
- Add pauses between batches
- Use WHERE clauses to limit scope
- Consider background jobs for very large updates (millions of rows)

[See the migration safety guide]({SAFE_MIGRATIONS_DOCS_URL}#running-data-migrations)""",
            )
        elif "ALTER" in sql:
            return OperationRisk(
                type=self.operation_type,
                score=3,
                reason="RunSQL with ALTER may cause locks",
                details={"sql": sql},
            )
        elif "CREATE" in sql and "INDEX" in sql:
            # Non-concurrent index creation (would have been caught earlier if CONCURRENTLY)
            if "IF NOT EXISTS" in sql:
                return OperationRisk(
                    type=self.operation_type,
                    score=2,
                    reason="CREATE INDEX without CONCURRENTLY locks table",
                    details={"sql": sql},
                    guidance="Use CONCURRENTLY to avoid table locks: CREATE INDEX CONCURRENTLY IF NOT EXISTS",
                )
            # Missing IF NOT EXISTS - slightly higher score within NEEDS_REVIEW range
            return OperationRisk(
                type=self.operation_type,
                score=3,
                reason="CREATE INDEX without CONCURRENTLY locks table",
                details={"sql": sql},
                guidance="Use CREATE INDEX CONCURRENTLY to avoid table locks. Add IF NOT EXISTS for idempotency and safer retries.",
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
            guidance=f"""Use batching for large data migrations:
- Use `.iterator()` to avoid loading all rows into memory
- Use `.bulk_update()` instead of saving individual objects
- Batch size: 1,000-10,000 rows per batch
- Add pauses between batches
- Consider background jobs for very large updates (millions of rows)

[See the migration safety guide]({SAFE_MIGRATIONS_DOCS_URL}#running-data-migrations)""",
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
