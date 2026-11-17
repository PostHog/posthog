from posthog.hogql import ast
from posthog.hogql.database.database import Database
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.escape_sql import escape_hogql_identifier
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import TraversingVisitor

MODELS_ROOT = "models"


class _ModelReferenceFinder(TraversingVisitor):
    """Collects the source offsets of table references that bind to an authored model.

    It walks the parsed query, not the resolved one: the parse holds only the text the user wrote, so a
    view's expanded body is never visited, and the resolver overwrites view references anyway.
    """

    def __init__(self, database: Database) -> None:
        super().__init__()
        self.database = database
        self.cte_scopes: list[set[str]] = []
        self.references: list[tuple[int, int, list[str], bool]] = []

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.cte_scopes.append(set(node.ctes or {}))
        try:
            super().visit_select_query(node)
        finally:
            self.cte_scopes.pop()

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        self.cte_scopes.append(set(node.ctes or {}))
        try:
            super().visit_select_set_query(node)
        finally:
            self.cte_scopes.pop()

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        table = node.table
        if isinstance(table, ast.Field) and table.start is not None and table.end is not None:
            chain = [str(part) for part in table.chain]
            if self._is_model_reference(chain):
                self.references.append((table.start, table.end, chain, node.alias is None))
        super().visit_join_expr(node)

    def _is_model_reference(self, chain: list[str]) -> bool:
        if chain[0] == MODELS_ROOT or any(".".join(chain) in scope for scope in self.cte_scopes):
            return False
        try:
            # Same node under both names means the bare name binds to the model, not to a table holding it.
            return self.database.get_table_node(chain) is self.database.get_table_node([MODELS_ROOT, *chain])
        except BaseHogQLError:
            return False


def qualify_model_references(query: str, database: Database) -> str:
    """Rewrites each table reference that binds to an authored model to `models.<name>`.

    It splices the source text, so comments and formatting survive. A query that does not parse comes
    back unchanged.
    """
    try:
        select = parse_select(query)
    except BaseHogQLError:
        return query

    finder = _ModelReferenceFinder(database)
    finder.visit(select)

    result = query
    for start, end, chain, needs_alias in sorted(finder.references, key=lambda ref: ref[0], reverse=True):
        # Offsets that do not cover exactly the name mean the parse and the text disagree; splicing would corrupt the query.
        if result[start:end].replace("`", "") != ".".join(chain):
            return query
        # Without an alias the old name was the implicit alias, and columns qualified by it must keep resolving.
        alias = f" AS {escape_hogql_identifier('__'.join(chain))}" if needs_alias else ""
        result = f"{result[:start]}{MODELS_ROOT}.{result[start:end]}{alias}{result[end:]}"
    return result
