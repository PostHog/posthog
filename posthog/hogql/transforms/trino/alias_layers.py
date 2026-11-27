from collections import Counter

from posthog.hogql import ast
from posthog.hogql.transforms.trino.query_wrappers import _AggregateFunctionFinder
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor

_MIN_SIBLING_READS_TO_LAYER = 2
_MAX_LAYERS = 20
_MAX_LAYERED_COLUMNS = 2_000


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
    if not aliases or _names_collide(aliases, source_columns) or any(map(_reads_a_property, aliases.values())):
        return None
    names = set(aliases)
    total_reads: Counter[str] = Counter()
    for expr in query.select:
        reads = _sibling_reads(_unwrap_projection(expr), names)
        if reads is None:
            return None
        total_reads.update(reads)
    if max(total_reads.values(), default=0) < _MIN_SIBLING_READS_TO_LAYER:
        return None
    if query.where is not None and _sibling_reads(query.where, names) != Counter():
        return None
    depths = _alias_depths(aliases, names)
    if depths is None:
        return None
    layer_count = max(depths.values()) + 1
    if layer_count * (len(source_columns) + len(aliases)) > _MAX_LAYERED_COLUMNS:
        return None
    qualifier = _SiblingAliasQualifier(names, source_alias)
    layer = source
    for depth in range(layer_count):
        carried = [*source_columns, *(name for name in aliases if depths[name] < depth)]
        layer_select: list[ast.Expr] = [ast.Field(chain=[source_alias, column]) for column in carried]
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


def _subquery_columns(source_type: ast.Type | None) -> list[str] | None:
    if isinstance(source_type, ast.CTETableAliasType):
        source_type = source_type.cte_table_type
    if isinstance(source_type, (ast.CTETableType, ast.SelectQueryAliasType, ast.SelectViewType)):
        return list(source_type.select_query_type.columns)
    return None


def _names_collide(aliases: dict[str, ast.Expr], source_columns: list[str]) -> bool:
    folded_aliases = {name.casefold() for name in aliases}
    folded_columns = {column.casefold() for column in source_columns}
    return (
        len(folded_aliases) < len(aliases)
        or len(folded_columns) < len(source_columns)
        or not folded_aliases.isdisjoint(folded_columns)
    )


def _reads_a_property(expr: ast.Expr) -> bool:
    expr = _unwrap_projection(expr)
    if isinstance(expr, ast.PropertyAccess):
        return True
    field_type = expr.type if isinstance(expr, ast.Field) else None
    while isinstance(field_type, ast.FieldAliasType):
        field_type = field_type.type
    return isinstance(field_type, ast.PropertyType)


def _source_alias(source: ast.JoinExpr) -> str | None:
    if source.alias is not None:
        return source.alias
    if isinstance(source.table, ast.Field) and isinstance(source.table.chain[-1], str):
        return source.table.chain[-1]
    return None


def _unwrap_projection(expr: ast.Expr) -> ast.Expr:
    return expr.expr if isinstance(expr, ast.Alias) else expr


def _sibling_reads(expr: ast.Expr, names: set[str]) -> Counter[str] | None:
    finder = _SiblingAliasReadFinder(names)
    finder.visit(expr)
    return None if finder.defines_inline_alias or finder.has_lambda else finder.reads


def _alias_depths(aliases: dict[str, ast.Expr], names: set[str]) -> dict[str, int] | None:
    pending = {name: set(_sibling_reads(expr, names) or ()) for name, expr in aliases.items()}
    depths: dict[str, int] = {}
    for depth in range(_MAX_LAYERS):
        ready = [name for name, reads in pending.items() if reads.issubset(depths)]
        for name in ready:
            depths[name] = depth
            del pending[name]
        if not pending:
            return depths
    return None


def _sibling_alias_read(node: ast.Field, names: set[str]) -> str | None:
    if len(node.chain) != 1 or not isinstance(node.type, ast.FieldAliasType):
        return None
    name = node.chain[0]
    return name if isinstance(name, str) and name in names else None


class _AggregateOrWindowFinder(_AggregateFunctionFinder):
    def visit_window_function(self, node: ast.WindowFunction) -> None:
        self.found = True


class _SiblingAliasReadFinder(TraversingVisitor):
    def __init__(self, names: set[str]) -> None:
        super().__init__()
        self.names = names
        self.reads: Counter[str] = Counter()
        self.defines_inline_alias = False
        self.has_lambda = False

    def visit(self, node: ast.AST | None) -> None:
        if isinstance(node, ast.Type):
            return
        super().visit(node)

    def visit_alias(self, node: ast.Alias) -> None:
        if not node.hidden:
            self.defines_inline_alias = True
        super().visit_alias(node)

    def visit_lambda(self, node: ast.Lambda) -> None:
        self.has_lambda = True

    def visit_field(self, node: ast.Field) -> None:
        name = _sibling_alias_read(node, self.names)
        if name is not None:
            self.reads[name] += 1

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
        name = _sibling_alias_read(node, self.names)
        if name is not None:
            return ast.Field(chain=[self.source_alias, name], start=node.start, end=node.end)
        return super().visit_field(node)

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        return node

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> ast.SelectSetQuery:
        return node
