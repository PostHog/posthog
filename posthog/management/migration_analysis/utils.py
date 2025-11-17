"""Utility classes and functions for migration analysis."""

import re
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from posthog.management.migration_analysis.models import OperationRisk


class VolatileFunctionDetector:
    """Detects volatile functions in field defaults that cause table rewrites."""

    VOLATILE_PATTERNS = [
        "uuid",
        "random",
        "now",  # datetime.now() is volatile (different from SQL NOW())
        "today",
        "time",
    ]

    @classmethod
    def is_volatile(cls, name: str) -> bool:
        """Check if a function name indicates a volatile function."""
        name_lower = name.lower()
        return any(pattern in name_lower for pattern in cls.VOLATILE_PATTERNS)

    @classmethod
    def is_stable(cls, name: str) -> bool:
        """Check if a function name indicates a stable function (SQL stable functions)."""
        # These are PostgreSQL stable functions that don't cause rewrites
        stable_functions = ["current_timestamp", "current_date", "current_time"]
        return name.lower() in stable_functions


class OperationCategorizer:
    """Categorizes migration operations for combination risk analysis."""

    # Operations that change database schema
    SCHEMA_OPERATIONS = {
        "AddField",
        "RemoveField",
        "AlterField",
        "RenameField",
        "AddIndex",
        "AddConstraint",
        "CreateModel",
        "DeleteModel",
    }

    # SQL keywords that indicate different operation types
    DML_KEYWORDS = ["UPDATE", "DELETE", "INSERT"]
    DDL_KEYWORDS = ["CREATE INDEX", "ALTER TABLE", "ADD COLUMN"]

    def __init__(self, operation_risks: list["OperationRisk"]):
        self.operation_risks = operation_risks
        self.dml_ops: list[tuple[int, OperationRisk]] = []
        self.ddl_ops: list[tuple[int, OperationRisk]] = []
        self.schema_ops: list[tuple[int, OperationRisk]] = []
        self.runsql_ops: list[tuple[int, OperationRisk]] = []
        self.runpython_ops: list[tuple[int, OperationRisk]] = []
        self.addindex_ops: list[tuple[int, OperationRisk]] = []
        self.high_risk_ops: list[tuple[int, OperationRisk]] = []
        self._categorize()

    def _categorize(self):
        """Categorize all operations by type."""
        for idx, op_risk in enumerate(self.operation_risks):
            if op_risk.type == "RunSQL":
                self._categorize_runsql(idx, op_risk)
            elif op_risk.type == "RunPython":
                self.runpython_ops.append((idx, op_risk))
            elif op_risk.type == "AddIndex":
                self.addindex_ops.append((idx, op_risk))
            elif op_risk.type in self.SCHEMA_OPERATIONS:
                self.schema_ops.append((idx, op_risk))

            # Track high-risk operations (score 4+)
            if op_risk.score >= 4:
                self.high_risk_ops.append((idx, op_risk))

    def _categorize_runsql(self, idx, op_risk):
        """Categorize a RunSQL operation as DML or DDL."""
        self.runsql_ops.append((idx, op_risk))

        sql_upper = str(op_risk.details.get("sql", "")).upper() if op_risk.details else ""

        # Skip categorization for safe non-blocking operations
        # These don't need DDL isolation warnings
        if "CONCURRENTLY" in sql_upper and ("INDEX" in sql_upper or "REINDEX" in sql_upper):
            return  # Don't categorize as DDL or DML

        # Skip for safe constraint operations
        if (
            ("ADD" in sql_upper and "CONSTRAINT" in sql_upper and "NOT VALID" in sql_upper)
            or ("VALIDATE" in sql_upper and "CONSTRAINT" in sql_upper)
            or ("DROP" in sql_upper and "CONSTRAINT" in sql_upper)
            or ("ADD" in sql_upper and "CONSTRAINT" in sql_upper and "USING INDEX" in sql_upper)
            or ("COMMENT ON" in sql_upper)
            or ("SET STATISTICS" in sql_upper)
            or ("SET (FILLFACTOR" in sql_upper)
        ):
            return  # Don't categorize as DDL - these are safe/metadata operations

        # Use word boundaries to avoid false positives like UPDATE_TIME matching UPDATE
        for kw in self.DML_KEYWORDS:
            if re.search(r"\b" + re.escape(kw) + r"\b", sql_upper):
                self.dml_ops.append((idx, op_risk))
                break

        for kw in self.DDL_KEYWORDS:
            # DDL keywords may have spaces, so escape and replace spaces with \s+
            pattern = r"\b" + re.escape(kw).replace(r"\ ", r"\s+") + r"\b"
            if re.search(pattern, sql_upper):
                self.ddl_ops.append((idx, op_risk))
                break

    @property
    def has_dml(self) -> bool:
        return len(self.dml_ops) > 0

    @property
    def has_ddl(self) -> bool:
        return len(self.ddl_ops) > 0

    @property
    def has_schema_changes(self) -> bool:
        return len(self.schema_ops) > 0

    @property
    def has_runpython(self) -> bool:
        return len(self.runpython_ops) > 0

    @property
    def has_multiple_indexes(self) -> bool:
        return len(self.addindex_ops) > 1

    @property
    def has_multiple_high_risk(self) -> bool:
        return len(self.high_risk_ops) > 1

    def format_operation_refs(self, ops: list[tuple[int, "OperationRisk"]]) -> str:
        """Format operation references like '#3 RunSQL, #5 AddField'."""
        return ", ".join(f"#{idx+1} {op.type}" for idx, op in ops)


def check_drop_properly_staged(
    target_type: str, table_name: str, migration: Any, loader: Any, field_name: Optional[str] = None
) -> bool:
    """
    Check if a DROP operation (table or column) was preceded by proper state removal.

    Args:
        target_type: Either "table" or "column"
        table_name: Name of table (e.g., "posthog_namedquery" or "llm_analytics_evaluation")
        migration: The migration object containing the DROP operation
        loader: Django MigrationLoader with migration history
        field_name: Column name (required for target_type="column", e.g., "prompt")

    Returns:
        True if drop was properly staged (state removed in prior migration),
        False otherwise

    Patterns checked:
    - For "table": SeparateDatabaseAndState with DeleteModel for the model
    - For "column": SeparateDatabaseAndState with RemoveField for the model+field
    """
    if not loader or not hasattr(loader, "disk_migrations"):
        return False

    # Extract model name from table name
    # posthog_namedquery -> NamedQuery
    # llm_analytics_evaluation (app=llm_analytics) -> Evaluation
    app_label = getattr(migration, "app_label", None)
    model_name = _extract_model_name_from_table(table_name, app_label)
    if not model_name:
        return False

    # For column drops, field_name is required
    if target_type == "column" and not field_name:
        return False

    # Walk back through migration history via dependencies
    visited = set()
    to_check = list(getattr(migration, "dependencies", []))

    while to_check:
        dependency_key = to_check.pop(0)

        # Avoid cycles
        if dependency_key in visited:
            continue
        visited.add(dependency_key)

        # Get the migration
        parent_migration = loader.disk_migrations.get(dependency_key)
        if not parent_migration:
            continue

        # Check if this migration removed the target from state
        if _migration_removed_from_state(parent_migration, target_type, model_name, field_name):
            return True

        # Continue walking back through dependencies
        if hasattr(parent_migration, "dependencies"):
            to_check.extend(parent_migration.dependencies)

    return False


def _extract_model_name_from_table(table_name: str, app_label: Optional[str] = None) -> Optional[str]:
    """
    Extract Django model name from table name.

    Examples:
        posthog_namedquery -> NamedQuery
        posthog_old_model -> OldModel
        llm_analytics_evaluation (app=llm_analytics) -> Evaluation
        my_app_some_table -> SomeTable

    Args:
        table_name: Database table name (e.g., "posthog_namedquery", "llm_analytics_evaluation")
        app_label: Optional app label to strip (e.g., "llm_analytics"). If not provided, assumes single-word app.
    """
    parts = table_name.split("_")
    if len(parts) < 2:
        return None

    # If app_label provided, strip it from the table name
    if app_label:
        # app_label might be multi-word (e.g., "llm_analytics")
        app_parts = app_label.split("_") if "_" in app_label else [app_label]
        # Check if table starts with app parts
        if parts[: len(app_parts)] == app_parts:
            model_parts = parts[len(app_parts) :]
        else:
            # Fallback: assume single-word app
            model_parts = parts[1:]
    else:
        # Skip first part (assumed to be app label like 'posthog')
        model_parts = parts[1:]

    if not model_parts:
        return None

    # Join remaining parts and convert to PascalCase
    model_name = "".join(word.capitalize() for word in model_parts)

    return model_name


def _migration_removed_from_state(
    migration: Any, target_type: str, model_name: str, field_name: Optional[str] = None
) -> bool:
    """
    Check if a migration removed a model or field from Django state.

    Looks for SeparateDatabaseAndState operations with:
    - DeleteModel (for target_type="table")
    - RemoveField (for target_type="column")
    """
    if not hasattr(migration, "operations"):
        return False

    for op in migration.operations:
        # Only check SeparateDatabaseAndState operations
        if op.__class__.__name__ != "SeparateDatabaseAndState":
            continue

        if not hasattr(op, "state_operations"):
            continue

        for state_op in op.state_operations:
            if target_type == "table":
                # Check for DeleteModel
                if state_op.__class__.__name__ != "DeleteModel":
                    continue

                # Check if the model name matches (case-insensitive)
                deleted_model_name = getattr(state_op, "name", "")
                if deleted_model_name.lower() == model_name.lower():
                    return True

            elif target_type == "column":
                # Check for RemoveField
                if state_op.__class__.__name__ != "RemoveField":
                    continue

                # Check if both model and field match (case-insensitive)
                removed_model_name = getattr(state_op, "model_name", "")
                removed_field_name = getattr(state_op, "name", "")

                if (
                    removed_model_name.lower() == model_name.lower()
                    and field_name
                    and removed_field_name.lower() == field_name.lower()
                ):
                    return True

    return False
