from posthog.hogql import ast
from posthog.hogql.database.models import FunctionCallTable
from posthog.hogql.errors import QueryError
from posthog.hogql.visitor import TraversingVisitor

from posthog.clickhouse.workload import Workload


class WorkloadCollector(TraversingVisitor):
    """Collects workload requirements from tables in a resolved AST."""

    def __init__(self, *, default_workload: Workload = Workload.DEFAULT):
        self.workloads: set[Workload] = set()
        self.default_workload = default_workload

    def visit_table_type(self, node: ast.TableType):
        if isinstance(node.table, FunctionCallTable):
            return

        self.workloads.add(node.table.workload or self.default_workload)

    def visit_lazy_table_type(self, node: ast.TableType):
        if isinstance(node.table, FunctionCallTable):
            return

        if hasattr(node.table, "workload"):
            self.workloads.add(node.table.workload or self.default_workload)

    def get_workload(self) -> Workload:
        """
        Returns the workload to use for query execution.

        If no workloads are found, returns the default.
        If exactly one workload is found, returns it.
        If multiple workloads are found, raises an error.
        """
        if not self.workloads:
            return self.default_workload

        if len(self.workloads) == 1:
            return next(iter(self.workloads))

        raise QueryError(
            f"Cannot query tables from different clusters in the same query. "
            f"Found tables requiring clusters: {', '.join(sorted(w.value.capitalize() for w in self.workloads))}"
        )
