import re
from collections.abc import Callable, Collection

from posthog.hogql import ast
from posthog.hogql.database.database import Database, models_namespace_chain
from posthog.hogql.database.models import SavedQuery
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.escape_sql import escape_hogql_identifier
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import TraversingVisitor, clear_locations

from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

MODELS_ROOT = "models"

DOES_NOT_PARSE = "Its query does not parse."
PARSE_CHECK_FAILED = "The updated query could not be checked against the original."

Chain = tuple[str, ...]
# Maps the chain of a table reference to the chain that replaces it, or None to leave it.
TargetFor = Callable[[Chain], list[str] | None]

_SEGMENT = r"""(?:`(?:[^`\\]|\\.)*`|"(?:[^"\\]|\\.)*"|[^\s.`"]+)"""


class ModelReferenceRewriteError(Exception):
    """The query cannot be rewritten with proof that nothing else changed."""


def _qualifier_binding(field_chain: list[str], scope: dict[str, list[str] | None]) -> tuple[int, list[str]] | None:
    """The leading segments of a field that name a model read in scope, and that read's replacement.

    Mirrors `lookup_table_by_name` and `lookup_table_by_nested_name` in the resolver: a first segment that
    is a table key wins, else the longest nested name among all tables in scope. A qualifier is rewritten
    only when the table it binds to is the model.
    """
    if len(field_chain) < 2:
        return None
    if field_chain[0] in scope:
        target = scope[field_chain[0]]
        return (1, target) if target is not None else None
    match: tuple[int, list[str] | None] | None = None
    parts: list[str] = []
    for consumed, segment in enumerate(field_chain[:-1], start=1):
        parts.extend(segment.split("."))
        key = "__".join(parts)
        if len(parts) >= 2 and key in scope:
            match = consumed, scope[key]
    if match is None or match[1] is None:
        return None
    return match[0], match[1]


class _ModelReferenceFinder(TraversingVisitor):
    """Collects the fields that name a model: table references, and the qualifiers that follow them.

    It walks the parsed query, not the resolved one: the parse holds only the text the user wrote, so a
    view's expanded body is never visited, and the resolver overwrites view references anyway.

    The resolver looks up a qualifier only in the tables of the `SELECT` that holds the field. So a
    qualifier is a reference only when it binds to an unaliased read of the model in that `SELECT`.
    """

    def __init__(self, target_for: TargetFor) -> None:
        super().__init__()
        self.target_for = target_for
        self.cte_scopes: list[set[str]] = []
        # Per open SELECT: the resolver's scope key of each table it reads, and the replacement when that
        # table is an unaliased read of the model.
        self.table_scopes: list[dict[str, list[str] | None]] = []
        self.qualified_fields: list[list[ast.Field]] = []
        self.lambda_arguments: list[str] = []
        # Each reference is the field, the number of leading segments to replace, and the replacement.
        self.references: list[tuple[ast.Field, int, list[str]]] = []

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        # The resolver registers a CTE only after resolving its definition, so a definition reads the
        # model of the same name. A recursive CTE is registered first, so it can read itself.
        ctes = node.ctes
        names: set[str] = set()
        self.cte_scopes.append(names)
        self.table_scopes.append({})
        self.qualified_fields.append([])
        try:
            for cte in (ctes or {}).values():
                if cte.recursive:
                    names.add(cte.name)
                self.visit(cte)
                names.add(cte.name)
            node.ctes = None
            try:
                super().visit_select_query(node)
            finally:
                node.ctes = ctes
        finally:
            self.cte_scopes.pop()
            scope = self.table_scopes.pop()
            fields = self.qualified_fields.pop()
        for field in fields:
            binding = _qualifier_binding([str(part) for part in field.chain], scope)
            if binding is not None:
                self.references.append((field, *binding))

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        # The parser puts a leading WITH on the first branch, and the resolver lets the later branches read it.
        self.visit(node.initial_select_query)
        first = node.initial_select_query
        self.cte_scopes.append(set(first.ctes or {}) if isinstance(first, ast.SelectQuery) else set())
        try:
            for expr in node.subsequent_select_queries:
                self.visit(expr.select_query)
            self.visit(node.limit)
            self.visit(node.offset)
        finally:
            self.cte_scopes.pop()

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        table = node.table
        if isinstance(table, ast.Field):
            # The table name is not visited as a field: `revenue.archive` is a table, not a column of `revenue`.
            raw_chain = [str(part) for part in table.chain]
            target = self._table_reference(table) if node.table_args is None else None
            if self.table_scopes:
                key = node.alias or "__".join(raw_chain)
                self.table_scopes[-1][key] = target if node.alias is None else None
        else:
            self.visit(table)
            if node.alias is not None and self.table_scopes:
                self.table_scopes[-1][node.alias] = None
        for expr in node.table_args or []:
            self.visit(expr)
        self.visit(node.constraint)
        self.visit(node.next_join)

    def visit_pivot_expr(self, node: ast.PivotExpr) -> None:
        self._pivot_source(node.table)
        for expr in [*node.aggregates, *node.columns, *(node.group_by or [])]:
            self.visit(expr)

    def visit_unpivot_expr(self, node: ast.UnpivotExpr) -> None:
        self._pivot_source(node.table)
        for column in node.columns:
            self.visit(column)

    def _pivot_source(self, table: ast.Expr) -> None:
        # The resolver reads a bare PIVOT or UNPIVOT source as a table, in a scope of its own.
        if isinstance(table, ast.Field):
            self._table_reference(table)
        else:
            self.visit(table)

    def visit_lambda(self, node: ast.Lambda) -> None:
        depth = len(self.lambda_arguments)
        self.lambda_arguments.extend(node.args)
        try:
            super().visit_lambda(node)
        finally:
            del self.lambda_arguments[depth:]

    def visit_field(self, node: ast.Field) -> None:
        # Inside a lambda, its argument wins over a table of the same name.
        if self.qualified_fields and len(node.chain) > 1 and str(node.chain[0]) not in self.lambda_arguments:
            self.qualified_fields[-1].append(node)

    def _table_reference(self, table: ast.Field) -> list[str] | None:
        raw_chain = [str(part) for part in table.chain]
        if any(".".join(raw_chain) in scope for scope in self.cte_scopes):
            return None
        # A backquoted segment can hold a dotted name, as `Database.get_table_node` accepts.
        chain = [part for segment in raw_chain for part in segment.split(".")]
        target = self.target_for(tuple(chain))
        if target is not None:
            self.references.append((table, len(raw_chain), target))
        return target


def _splice(text: str, field: ast.Field, length: int, target: list[str]) -> str:
    if field.start is None or field.end is None:
        raise ModelReferenceRewriteError(PARSE_CHECK_FAILED)
    source = text[field.start : field.end]
    leading = re.match(rf"{_SEGMENT}(?:\s*\.\s*{_SEGMENT}){{{length - 1}}}", source)
    if leading is None:
        raise ModelReferenceRewriteError(PARSE_CHECK_FAILED)
    replacement = ".".join(escape_hogql_identifier(part) for part in target)
    return f"{text[: field.start]}{replacement}{source[leading.end() :]}{text[field.end :]}"


def _rewrite(query: str, target_for: TargetFor) -> str:
    try:
        select = parse_select(query)
    except BaseHogQLError as error:
        raise ModelReferenceRewriteError(DOES_NOT_PARSE) from error

    finder = _ModelReferenceFinder(target_for)
    finder.visit(select)
    if not finder.references:
        return query

    result = query
    for field, length, target in sorted(finder.references, key=lambda ref: ref[0].start or 0, reverse=True):
        result = _splice(result, field, length, target)
        field.chain = [*target, *field.chain[length:]]

    # The splice edits text. The parse of the result must equal the original parse with only the
    # found chains replaced, or the splice changed something else.
    try:
        proven = clear_locations(parse_select(result)) == clear_locations(select)
    except BaseHogQLError:
        proven = False
    if not proven:
        raise ModelReferenceRewriteError(PARSE_CHECK_FAILED)
    return result


def model_spellings(saved_query: DataWarehouseSavedQuery, database: Database) -> set[Chain]:
    """The table names that bind to this model for the whole team.

    A synced table can hold the bare name, and then only `models.<name>` is the model.
    """
    spellings: set[Chain] = set()
    for chain in (saved_query.name_chain, models_namespace_chain(saved_query)):
        if chain is None:
            continue
        try:
            table = database.get_table_node(chain).table
        except BaseHogQLError:
            continue
        bound_id = table.id if isinstance(table, SavedQuery) else getattr(table, "saved_query_id", None)
        if bound_id == str(saved_query.id):
            spellings.add(tuple(chain))
    return spellings


def rename_model_references(query: str, spellings: Collection[Chain], new_chain: list[str]) -> str:
    """Rewrites each reference to the model that answers to `spellings` to the model's new name `new_chain`.

    A reference keeps its own form: `old` becomes `new`, and `models.old` becomes `models.new`.
    It splices the source text, so comments and formatting survive. It parses and never resolves.
    Raises ModelReferenceRewriteError when the query does not parse or the result cannot be proven.
    """
    qualified = new_chain if new_chain[0] == MODELS_ROOT else [MODELS_ROOT, *new_chain]

    def target_for(chain: Chain) -> list[str] | None:
        if chain not in spellings:
            return None
        return qualified if chain[0] == MODELS_ROOT else new_chain

    return _rewrite(query, target_for)
