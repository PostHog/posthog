from datetime import datetime, timedelta
from typing import Any

from posthog.hogql import ast
from posthog.hogql.visitor import CloningVisitor


class EvalTimeFreezeVisitor(CloningVisitor):
    """Replaces now()/today()/yesterday()/current_timestamp() with constants
    derived from a snapshot date. Active only in eval mode to ensure ClickHouse
    evaluates time-relative expressions against the snapshot date."""

    DATE_GENERATORS = frozenset({"now", "today", "yesterday", "current_timestamp"})

    def __init__(self, snapshot_date: datetime):
        super().__init__(clear_types=True)
        self.snapshot_date = snapshot_date

    def visit_call(self, node: ast.Call) -> Any:
        name_lower = node.name.lower()
        if name_lower in self.DATE_GENERATORS:
            if name_lower in ("now", "current_timestamp"):
                return ast.Constant(value=self.snapshot_date)
            elif name_lower == "today":
                return ast.Constant(value=self.snapshot_date.date())
            elif name_lower == "yesterday":
                return ast.Constant(value=self.snapshot_date.date() - timedelta(days=1))
        return super().visit_call(node)
