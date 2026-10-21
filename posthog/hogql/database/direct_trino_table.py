import re
from typing import ClassVar

from posthog.hogql import ast
from posthog.hogql.database.direct_sql_table import DirectSQLTable
from posthog.hogql.database.models import FieldOrTable
from posthog.hogql.errors import QueryError
from posthog.hogql.visitor import TraversingVisitor

# Catalogs a tenant creates on the managed Trino warehouse. PostHog reads them but never writes.
MANAGED_TRINO_EXTERNAL_CATALOG_PATTERN = re.compile(r"^ext_.+__.+$")


def is_managed_trino_external_catalog(catalog: str) -> bool:
    return MANAGED_TRINO_EXTERNAL_CATALOG_PATTERN.match(catalog) is not None


class _ExternalTableReferenceFinder(TraversingVisitor):
    def __init__(self) -> None:
        self.found: str | None = None

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        if self.found is None and isinstance(node.table, ast.Field):
            chain = [str(part) for part in node.table.chain]
            if len(chain) == 3 and is_managed_trino_external_catalog(chain[0]):
                self.found = ".".join(chain)
        super().visit_join_expr(node)


def find_managed_trino_external_table_reference(node: ast.AST) -> str | None:
    """Return the first `ext_*` catalog table the unresolved query reads, if any.

    Works on the parsed AST because a ClickHouse database does not contain these tables,
    so resolution would only report an unknown table.
    """
    finder = _ExternalTableReferenceFinder()
    finder.visit(node)
    return finder.found


class DirectTrinoTable(DirectSQLTable):
    trino_catalog: str
    trino_schema: str
    trino_table_name: str

    case_insensitive_identifiers: ClassVar[bool] = True

    # Trino resolves unquoted identifiers case-insensitively, but the printer quotes canonical
    # names. Resolve the user's field spelling to the discovered column name before printing it.
    def _canonical_field_key(self, name: str | int) -> str | None:
        target = str(name).lower()
        return next((key for key in self.fields if key.lower() == target), None)

    def has_field(self, name: str | int) -> bool:
        return super().has_field(name) or self._canonical_field_key(name) is not None

    def get_field(self, name: str | int) -> FieldOrTable:
        if super().has_field(name):
            return super().get_field(name)
        key = self._canonical_field_key(name)
        if key is not None:
            return self.fields[key]
        return super().get_field(name)

    def to_printed_duckdb(self, context) -> str:
        raise QueryError("Direct Trino tables cannot be printed into DuckDB SQL")

    def to_printed_postgres(self, context) -> str:
        raise QueryError("Direct Trino tables cannot be printed into Postgres SQL")

    def to_printed_clickhouse(self, context) -> str:
        raise QueryError("Direct Trino tables cannot be printed into ClickHouse SQL")
