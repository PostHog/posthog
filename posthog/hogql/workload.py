from posthog.hogql import ast
from posthog.hogql.database.models import FunctionCallTable, Table
from posthog.hogql.database.s3_table import S3Table
from posthog.hogql.database.schema.duckdb_table_functions import (
    GenerateSeriesTable,
    OpaqueFunctionCallTable,
    RangeTable,
)
from posthog.hogql.database.schema.numbers import NumbersTable
from posthog.hogql.errors import QueryError
from posthog.hogql.visitor import TraversingVisitor

from posthog.clickhouse.workload import Workload

# Standalone table functions (numbers(), range(), generate_series(), opaque direct-SQL calls) are pure
# compute with no cluster affinity — they run identically on any cluster, so they don't disqualify a
# query from materialized-view routing. Mirrors the exclusion list in posthog/hogql/query.py.
_STANDALONE_FUNCTION_TABLES = (RangeTable, GenerateSeriesTable, OpaqueFunctionCallTable, NumbersTable)


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


class MaterializedViewOnlyCollector(TraversingVisitor):
    """Detects queries whose only data reads are materialized-view S3 tables.

    Such a query is isolated in exactly the way a materialized endpoint is — it reads a single
    S3-delta file and nothing else — so it can run on the dedicated endpoints cluster. Must be
    visited on the fully lazy-resolved AST: a lazy join to persons/events (which lives on another
    cluster) only materializes into a concrete table after lazy-table resolution, and it must
    disqualify the query.
    """

    def __init__(self):
        self.saw_materialized_view = False
        self.saw_other_table = False

    def visit_table_type(self, node: ast.TableType):
        self._check_table(node.table)

    def visit_lazy_table_type(self, node: ast.TableType):
        # An unresolved lazy table means the query still depends on a joined source (persons,
        # events, groups, sessions) that isn't an S3 read — never route these.
        self.saw_other_table = True

    def _check_table(self, table: Table) -> None:
        if isinstance(table, _STANDALONE_FUNCTION_TABLES):
            return
        if isinstance(table, S3Table) and table.is_materialized_view:
            self.saw_materialized_view = True
        else:
            self.saw_other_table = True

    @property
    def is_materialized_view_only(self) -> bool:
        return self.saw_materialized_view and not self.saw_other_table
