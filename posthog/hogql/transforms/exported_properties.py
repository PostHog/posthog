"""Exported properties narrowing.

A select that exports the events `properties` blob to readers that only read keys of it exports a map of those keys
instead, under the same name:

    SELECT properties.email FROM (SELECT properties FROM events)
    ->
    SELECT replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(properties['email']), ''), 'null'), '^"|"$', '')
    FROM (SELECT map('email', JSONExtractRaw(events.properties, 'email')) AS properties FROM events)

On the native JSON events table the exported blob is a document rebuilt per row from every stored property, and the
reader parses that text again; the map reads one subcolumn per key instead. The column keeps its name, so a select that
passes it through to its own reader needs no change, and a reader looks a key up in the map where it extracted it from
the blob before.

The map holds each key's JSON text as `JSONExtractRaw(blob, key)` returned it. On the native table the property
resolution pass supplies that text from the key's own stored column (`stored_key_json_text`), or declines when no single
column holds what the rebuilt document shows, and a declined key keeps the blob. Neither is a property read: a property
read gets the property-definition type and, on the legacy table, a materialized column, which reads an empty string as
NULL and decodes escapes. The reader's own extract stays around the lookup, so a missing key still reads as `''` and
then NULL.

A blob stays a blob when any reader reads it whole (`SELECT properties`, `JSONHas(properties, k)`, a DISTINCT, GROUP BY
or ORDER BY on the column, a bare alias reference), when the resolution pass declines a key a native reader asks for, or
when any column that carries the same value cannot be narrowed: the columns a blob passes through and the branches of a
UNION ALL form one group, decided together. The decision runs on the reads `ProjectionPushdownOptimizer` collected,
after it pruned.
"""

from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.compilation import compilation_budget
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import StringJSONDatabaseField
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.util.null_sentinels import null_if_sentinels
from posthog.hogql.visitor import clone_expr

if TYPE_CHECKING:
    from posthog.hogql.transforms.projection_pushdown import ProjectionPushdownOptimizer, SubqueryNode

_MAP_TYPE_NAME = "Map(String, Nullable(String))"


def narrow_exported_properties(optimizer: "ProjectionPushdownOptimizer", context: HogQLContext) -> None:
    """Mutates the optimized query in place."""
    _ExportedPropertiesNarrower(optimizer, context).run()


def document_key_extract(document: ast.Expr, chain: list[str | int]) -> ast.Expr:
    """The key's raw JSON text with the quotes trimmed, as the printer renders a property read of a text document."""
    extract = ast.Call(
        name="JSONExtractRaw",
        args=[document, *(ast.Constant(value=key) for key in chain)],
        type=ast.StringType(nullable=False),
    )
    return ast.Call(
        name="replaceRegexpAll",
        args=[null_if_sentinels(extract), ast.Constant(value='^"|"$'), ast.Constant(value="")],
        type=ast.StringType(nullable=True),
    )


def _map_type() -> ast.MapType:
    return ast.MapType(key_type=ast.StringType(nullable=False), value_type=ast.StringType(nullable=True))


def _key_json_text(source: ast.Field, key: str, context: HogQLContext) -> ast.Expr | None:
    """The key's JSON text as `JSONExtractRaw(blob, key)` returns it, read from the events table (module docstring), or
    None when the native table has no single stored column for it."""
    if context.uses_new_events_schema():
        # Deferred: the resolution pass imports the printer, which imports the pruner and so this module.
        from posthog.hogql.transforms.clickhouse_property_resolution import stored_key_json_text  # noqa: PLC0415

        field_type = source.type
        assert isinstance(field_type, ast.FieldType)
        return stored_key_json_text(field_type, key, context)
    return ast.Call(
        name="JSONExtractRaw",
        args=[clone_expr(source, clear_types=False), ast.Constant(value=key)],
        type=ast.StringType(nullable=False),
    )


def _column_name(expr: ast.Expr) -> str | None:
    if isinstance(expr, ast.Alias):
        return expr.alias
    if isinstance(expr, ast.Field) and expr.chain:
        return str(expr.chain[-1])
    return None


def _unwrap_aliases(expr: ast.Expr) -> ast.Expr:
    while isinstance(expr, ast.Alias):
        expr = expr.expr
    return expr


class _ExportedPropertiesNarrower:
    def __init__(self, optimizer: "ProjectionPushdownOptimizer", context: HogQLContext):
        self.optimizer = optimizer
        self.context = context
        self._registered = {id(node) for node in optimizer.subquery_map.values()}
        self._exprs_by_name: dict[int, dict[str, ast.Expr]] = {}

    def run(self) -> None:
        for group in self._column_groups():
            if not all(self._allows_map(node, name) for node, name in group):
                continue
            for node, name in group:
                self._rewrite_reads(node, name)
                if isinstance(node, ast.SelectQuery) and self._events_source(node, name) is not None:
                    self._rewrite_export(node, name)

    def _column_groups(self) -> list[list[tuple["SubqueryNode", str]]]:
        """The columns that carry one value between them, so one decision covers them all: a column and the child
        column it passes through, a set query's column and the same column of each branch."""
        nodes = list({id(node): node for node in self.optimizer.subquery_map.values()}.values())
        seen: set[tuple[int, str]] = set()
        groups: list[list[tuple[SubqueryNode, str]]] = []
        budget = compilation_budget.get()
        for node in nodes:
            if budget is not None:
                budget.check_time()
            for name in self._column_names(node):
                if (id(node), name) in seen:
                    continue
                seen.add((id(node), name))
                group: list[tuple[SubqueryNode, str]] = []
                queue: list[tuple[SubqueryNode, str]] = [(node, name)]
                while queue:
                    member = queue.pop()
                    group.append(member)
                    for neighbor in self._neighbors(*member):
                        key = (id(neighbor[0]), neighbor[1])
                        if key not in seen:
                            seen.add(key)
                            queue.append(neighbor)
                groups.append(group)
        return groups

    def _neighbors(self, node: "SubqueryNode", name: str) -> list[tuple["SubqueryNode", str]]:
        neighbors: list[tuple[SubqueryNode, str]] = []
        if isinstance(node, ast.SelectSetQuery):
            for query in self.optimizer.union_queries(node):
                branch_name = self.optimizer.branch_column_name(node, query, name)
                if branch_name is not None:
                    neighbors.append((query, branch_name))
        else:
            passthrough = self._passthrough(node, name)
            if passthrough is not None:
                neighbors.append(passthrough)
        neighbors.extend(self.optimizer.passthrough_parents.get((id(node), name), {}).values())
        set_query = self.optimizer.union_of.get(id(node))
        if set_query is not None:
            set_name = self.optimizer.set_column_name(set_query, node, name)
            if set_name is not None:
                neighbors.append((set_query, set_name))
        return neighbors

    def _column_names(self, node: "SubqueryNode") -> list[str]:
        if isinstance(node, ast.SelectSetQuery):
            return self._column_names(self.optimizer.union_queries(node)[0])
        return [name for name in (_column_name(expr) for expr in node.select) if name is not None]

    def _select_expr(self, node: ast.SelectQuery, name: str) -> ast.Expr | None:
        exprs = self._exprs_by_name.get(id(node))
        if exprs is None:
            exprs = {}
            for expr in node.select:
                column = _column_name(expr)
                if column is not None and column not in exprs:
                    exprs[column] = expr
            self._exprs_by_name[id(node)] = exprs
        return exprs.get(name)

    def _source_field(self, node: ast.SelectQuery, name: str) -> ast.Field | None:
        expr = self._select_expr(node, name)
        source = _unwrap_aliases(expr) if expr is not None else None
        if isinstance(source, ast.Field) and isinstance(source.type, ast.FieldType):
            return source
        return None

    def _passthrough(self, node: ast.SelectQuery, name: str) -> tuple["SubqueryNode", str] | None:
        source = self._source_field(node, name)
        if source is None:
            return None
        assert isinstance(source.type, ast.FieldType)
        child = self.optimizer.child_for(source.type.table_type)
        return (child, source.type.name) if child is not None else None

    def _events_source(self, node: ast.SelectQuery, name: str) -> ast.Field | None:
        source = self._source_field(node, name)
        if source is None or not isinstance(source.type, ast.FieldType) or not self._is_events_properties(source.type):
            return None
        return source

    def _allows_map(self, node: "SubqueryNode", name: str) -> bool:
        """Whether this member of a column group can carry the map instead of the blob.

        A select may only pass a `properties` column along, or export it from the events table, when nothing in it
        consumes the column's value: no reader of the column itself (a bare field read, or a clause naming it by alias
        or by position), no DISTINCT, GROUP BY or HAVING, which compare or group by every column or the named ones, no
        set operation but UNION ALL, and the select is neither the query's output nor a recursive CTE. These are the
        ways a ClickHouse select can use a column's value without a field reference, so the check lives here in one
        place rather than in the pruner's read tracking.
        """
        reads = self.optimizer.reads.get((id(node), name))
        if reads is not None and reads.whole:
            return False
        set_query = self.optimizer.union_of.get(id(node))
        if set_query is not None and not self._lines_up_with_set(set_query, node, name):
            return False
        if isinstance(node, ast.SelectSetQuery):
            return all(set_node.set_operator.startswith("UNION ALL") for set_node in node.subsequent_select_queries)
        if id(node) in self.optimizer.roots or id(node) in self.optimizer.recursive_cte_exprs:
            return False
        if id(node) not in self._registered and id(node) not in self.optimizer.union_of:
            # A select inside an expression: its columns are its output
            return False
        if node.distinct or node.group_by or node.group_by_mode is not None or node.having is not None:
            return False
        if id(node) in self.optimizer.strict_set_branches:
            return False
        expr = self._select_expr(node, name)
        if expr is None:
            return False
        if any(expr is column for column in self.optimizer.positional_columns(node)):
            return False
        if expr.type is not None and id(expr.type) in self.optimizer.alias_referenced_types:
            return False
        if self._passthrough(node, name) is not None:
            return True
        source = self._events_source(node, name)
        if source is None:
            return False
        keys = reads.keys if reads is not None else set()
        return all(_key_json_text(source, key, self.context) is not None for key in keys)

    def _lines_up_with_set(self, set_query: ast.SelectSetQuery, node: "SubqueryNode", name: str) -> bool:
        """Whether the branch column sits at the position of the set query's column it feeds. A set operation pairs
        columns by position, so a map exported from a column matched by name at another position would meet the blob
        or another column there."""
        set_name = self.optimizer.set_column_name(set_query, node, name)
        if set_name is None:
            return False
        return self.optimizer.select_position(node, name) == self.optimizer.select_position(set_query, set_name)

    def _is_events_properties(self, field_type: ast.FieldType) -> bool:
        table_type = field_type.table_type
        if isinstance(table_type, ast.TableAliasType):
            table_type = table_type.table_type
        if not isinstance(table_type, ast.TableType) or not isinstance(table_type.table, EventsTable):
            return False
        database_field = field_type.resolve_database_field(self.context)
        return isinstance(database_field, StringJSONDatabaseField) and database_field.name == "properties"

    def _rewrite_reads(self, node: "SubqueryNode", name: str) -> None:
        reads = self.optimizer.reads.get((id(node), name))
        if reads is not None:
            for alias_node, field_node in reads.sites.values():
                self._rewrite_read(alias_node, field_node)

    def _rewrite_read(self, alias_node: ast.Alias, field_node: ast.Field) -> None:
        property_type = field_node.type
        assert isinstance(property_type, ast.PropertyType)
        base_chain = field_node.chain[: len(field_node.chain) - len(property_type.chain)]
        base = ast.Field(chain=list(base_chain) or [property_type.field_type.name], type=property_type.field_type)
        lookup = ast.ArrayAccess(
            array=base, property=ast.Constant(value=property_type.chain[0]), type=ast.StringType(nullable=True)
        )
        new_expr = document_key_extract(lookup, list(property_type.chain[1:]))
        alias_node.expr = new_expr
        if isinstance(alias_node.type, ast.FieldAliasType):
            # The resolver shares this type object with the select scope's column and alias maps
            alias_node.type.type = new_expr.type or ast.UnknownType()

    def _rewrite_export(self, node: ast.SelectQuery, name: str) -> None:
        expr = self._select_expr(node, name)
        source = self._events_source(node, name)
        assert expr is not None and source is not None
        reads = self.optimizer.reads.get((id(node), name))
        map_expr = self._map_expr(source, sorted(reads.keys) if reads is not None else [])
        innermost: ast.Alias | None = None
        current = expr
        while isinstance(current, ast.Alias):
            innermost = current
            current = current.expr
        if innermost is None:
            replacement = ast.Alias(
                alias=name,
                expr=map_expr,
                hidden=True,
                type=ast.FieldAliasType(alias=name, type=_map_type()),
            )
            node.select[node.select.index(expr)] = replacement
            self._exprs_by_name.pop(id(node), None)
            if isinstance(node.type, ast.SelectQueryType):
                node.type.columns[name] = replacement.type or ast.UnknownType()
            return
        innermost.expr = map_expr
        if isinstance(innermost.type, ast.FieldAliasType):
            innermost.type.type = _map_type()

    def _map_expr(self, source: ast.Field, keys: list[str]) -> ast.Expr:
        args: list[ast.Expr] = []
        for key in keys:
            text = _key_json_text(source, key, self.context)
            assert text is not None
            args.append(ast.Constant(value=key))
            args.append(text)
        map_call = ast.Call(name="map", args=args, type=_map_type())
        if keys:
            return map_call
        # Nobody reads a key; `map()` alone has the type Nothing, which a pass-through cannot carry
        return ast.Call(name="accurateCast", args=[map_call, ast.Constant(value=_MAP_TYPE_NAME)], type=_map_type())
