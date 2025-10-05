"""Utility classes and functions for migration analysis."""

import re


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

    def __init__(self, operation_risks: list):
        self.operation_risks = operation_risks
        self.dml_ops: list[tuple[int, object]] = []
        self.ddl_ops: list[tuple[int, object]] = []
        self.schema_ops: list[tuple[int, object]] = []
        self.runsql_ops: list[tuple[int, object]] = []
        self.runpython_ops: list[tuple[int, object]] = []
        self.addindex_ops: list[tuple[int, object]] = []
        self.high_risk_ops: list[tuple[int, object]] = []
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

    def format_operation_refs(self, ops: list[tuple[int, object]]) -> str:
        """Format operation references like '#3 RunSQL, #5 AddField'."""
        return ", ".join(f"#{idx+1} {getattr(op, 'type', 'Unknown')}" for idx, op in ops)
