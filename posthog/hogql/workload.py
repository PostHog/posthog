from posthog.hogql import ast
from posthog.hogql.database.models import FunctionCallTable
from posthog.hogql.errors import QueryError
from posthog.hogql.visitor import TraversingVisitor

from posthog.clickhouse.workload import LogsClusterSignal, Workload


class WorkloadCollector(TraversingVisitor):
    """Collects workload requirements from tables in a resolved AST."""

    def __init__(self, *, default_workload: Workload = Workload.DEFAULT):
        self.workloads: set[Workload] = set()
        self.logs_cluster_signals: set[LogsClusterSignal | None] = set()
        self.default_workload = default_workload

    def visit_table_type(self, node: ast.TableType):
        if isinstance(node.table, FunctionCallTable):
            return

        self._add(node.table.workload or self.default_workload, node.table.logs_cluster_signal)

    def visit_lazy_table_type(self, node: ast.LazyTableType):
        if hasattr(node.table, "workload"):
            self._add(node.table.workload or self.default_workload, getattr(node.table, "logs_cluster_signal", None))

    def _add(self, workload: Workload, logs_cluster_signal: LogsClusterSignal | None) -> None:
        self.workloads.add(workload)
        if workload == Workload.LOGS:
            self.logs_cluster_signals.add(logs_cluster_signal)

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

    def get_logs_cluster_signal(self) -> LogsClusterSignal | None:
        """The one signal of every logs-cluster table the query reads, or None when they differ or one has none.

        Each signal user can read only the tables of its own signal, so a query that reads tables of
        two signals must use the shared logs cluster user.
        """
        if len(self.logs_cluster_signals) == 1:
            return next(iter(self.logs_cluster_signals))
        return None
