from collections import Counter

from posthog.hogql import ast
from posthog.hogql.transforms.trino.query_wrappers import _AggregateFunctionFinder
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor

_MIN_SIBLING_READS_TO_LAYER = 2


class TrinoSiblingAliasLayerer(CloningVisitor):
    def __init__(self) -> None:
        super().__init__(clear_types=False)

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        lowered = super().visit_select_query(node)
        return _layered(lowered) or lowered


def _layered(query: ast.SelectQuery) -> ast.SelectQuery | None:
    source = query.select_from
    if (
        source is None
        or source.next_join is not None
        or source.sample is not None
        or source.column_aliases
        or not _is_plain_projection(query)
    ):
        return None
    source_columns = _subquery_columns(source.type)
    source_alias = _source_alias(source)
    if source_columns is None or source_alias is None:
        return None
    aliases = {expr.alias: expr.expr for expr in query.select if isinstance(expr, ast.Alias) and not expr.hidden}
    if not aliases or aliases.keys() & source_columns:
        return None
    reads_by_projection = [_sibling_reads(_unwrap_projection(expr), aliases) for expr in query.select]
    if any(reads is None for reads in reads_by_projection):
        return None
    total_reads = sum((reads for reads in reads_by_projection if reads is not None), Counter())
    if max(total_reads.values(), default=0) < _MIN_SIBLING_READS_TO_LAYER:
        return None
    if query.where is not None and _sibling_reads(query.where, aliases) != Counter():
        return None
    depths = _alias_depths(aliases)
    qualifier = _SiblingAliasQualifier(set(aliases), source_alias)
    layer = source
    for depth in range(max(depths.values()) + 1):
        layer_select: list[ast.Expr] = [ast.Field(chain=[source_alias, "*"])]
        layer_select.extend(
            ast.Alias(alias=name, expr=qualifier.visit(expr)) for name, expr in aliases.items() if depths[name] == depth
        )
        layer_query = ast.SelectQuery(select=layer_select, select_from=layer, where=query.where if depth == 0 else None)
        layer = ast.JoinExpr(table=layer_query, alias=source_alias)
    query.select = [
        ast.Alias(alias=expr.alias, expr=ast.Field(chain=[source_alias, expr.alias]))
        if isinstance(expr, ast.Alias) and expr.alias in aliases and not expr.hidden
        else qualifier.visit(expr)
        for expr in query.select
    ]
    query.select_from = layer
    query.where = None
    return query


def _is_plain_projection(query: ast.SelectQuery) -> bool:
    if (
        query.group_by
        or query.group_by_mode
        or query.having
        or query.qualify
        or query.window_exprs
        or query.distinct
        or query.limit_by
        or query.prewhere
        or query.array_join_op
        or query.array_join_list
        or query.interpolate
    ):
        return False
    finder = _AggregateOrWindowFinder()
    for expr in query.select:
        finder.visit(expr)
    return not finder.found


def _subquery_columns(source_type: ast.Type | None) -> set[str] | None:
    if isinstance(source_type, ast.CTETableAliasType):
        source_type = source_type.cte_table_type
    if isinstance(source_type, (ast.CTETableType, ast.SelectQueryAliasType, ast.SelectViewType)):
        return set(source_type.select_query_type.columns)
    return None


def _source_alias(source: ast.JoinExpr) -> str | None:
    if source.alias is not None:
        return source.alias
    if isinstance(source.table, ast.Field) and isinstance(source.table.chain[-1], str):
        return source.table.chain[-1]
    return None


def _unwrap_projection(expr: ast.Expr) -> ast.Expr:
    return expr.expr if isinstance(expr, ast.Alias) else expr


def _sibling_reads(expr: ast.Expr, aliases: dict[str, ast.Expr]) -> Counter[str] | None:
    finder = _SiblingAliasReadFinder(set(aliases))
    finder.visit(expr)
    return None if finder.defines_inline_alias else finder.reads


def _alias_depths(aliases: dict[str, ast.Expr]) -> dict[str, int]:
    depths: dict[str, int] = {}

    def depth_of(name: str) -> int:
        if name not in depths:
            reads = _sibling_reads(aliases[name], aliases) or Counter()
            depths[name] = 1 + max((depth_of(read) for read in reads), default=-1)
        return depths[name]

    for name in aliases:
        depth_of(name)
    return depths


def _is_sibling_alias_read(node: ast.Field, names: set[str]) -> bool:
    return (
        len(node.chain) == 1
        and isinstance(node.chain[0], str)
        and node.chain[0] in names
        and isinstance(node.type, ast.FieldAliasType)
    )


class _AggregateOrWindowFinder(_AggregateFunctionFinder):
    def visit_window_function(self, node: ast.WindowFunction) -> None:
        self.found = True


class _SiblingAliasReadFinder(TraversingVisitor):
    def __init__(self, names: set[str]) -> None:
        super().__init__()
        self.names = names
        self.reads: Counter[str] = Counter()
        self.defines_inline_alias = False

    def visit(self, node: ast.AST | None) -> None:
        if isinstance(node, ast.Type):
            return
        super().visit(node)

    def visit_alias(self, node: ast.Alias) -> None:
        if not node.hidden:
            self.defines_inline_alias = True
        super().visit_alias(node)

    def visit_field(self, node: ast.Field) -> None:
        if _is_sibling_alias_read(node, self.names):
            self.reads[node.chain[0]] += 1

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        return None

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        return None


class _SiblingAliasQualifier(CloningVisitor):
    def __init__(self, names: set[str], source_alias: str) -> None:
        super().__init__(clear_types=False)
        self.names = names
        self.source_alias = source_alias

    def visit_field(self, node: ast.Field) -> ast.Field:
        if _is_sibling_alias_read(node, self.names):
            return ast.Field(chain=[self.source_alias, node.chain[0]], start=node.start, end=node.end)
        return super().visit_field(node)

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        return node

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> ast.SelectSetQuery:
        return node
