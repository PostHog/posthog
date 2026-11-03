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

The map holds each key's JSON text as `JSONExtractRaw(blob, key)` returned it. On the native table that text is
`toJSONString` over an untyped read of the key, which the ClickHouse property pass serves from one subcolumn. Neither
is a property read: a property read gets the property-definition type and, on the legacy table, a materialized column,
which reads an empty string as NULL and decodes escapes. The reader's own extract stays around the lookup, so a missing
key still reads as `''` and then NULL.

A blob stays a blob when any reader reads it whole (`SELECT properties`, `JSONHas(properties, k)`, a DISTINCT, GROUP BY
or ORDER BY on the column, a bare alias reference), when a native reader asks for `$feature_flags`, which the rebuilt
document leaves out in favour of its `$feature/<key>` pairs, or when any column that carries the same value cannot be
narrowed: the columns a blob passes through and the branches of a UNION ALL form one group, decided together. The
decision runs on the reads `ProjectionPushdownOptimizer` collected, after it pruned.
"""

from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import StringJSONDatabaseField
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.util.null_sentinels import null_if_sentinels
from posthog.hogql.transforms.logical_property_lowering import lower_property_access
from posthog.hogql.visitor import clone_expr

if TYPE_CHECKING:
    from posthog.schema import HogQLQueryModifiers

    from posthog.hogql.transforms.projection_pushdown import ProjectionPushdownOptimizer, SubqueryNode

_MAP_TYPE_NAME = "Map(String, Nullable(String))"


def narrow_subquery_properties_enabled(modifiers: "HogQLQueryModifiers") -> bool:
    """On unless a project turns it off. Unset means on, so the default stays out of the query cache key."""
    return modifiers.narrowSubqueryProperties is not False


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


def _key_json_text(source: ast.Field, key: str, context: HogQLContext) -> ast.Expr:
    """The key's JSON text as `JSONExtractRaw(blob, key)` returns it, read from the events table (module docstring)."""
    if not context.uses_new_events_schema():
        return ast.Call(
            name="JSONExtractRaw",
            args=[clone_expr(source, clear_types=False), ast.Constant(value=key)],
            type=ast.StringType(nullable=False),
        )
    field_type = source.type
    assert isinstance(field_type, ast.FieldType)
    first_key = ast.Field(chain=[*source.chain, key], type=ast.PropertyType(chain=[key], field_type=field_type))
    return ast.Call(
        name="toJSONString",
        args=[lower_property_access(first_key, context)],
        type=ast.StringType(nullable=True),
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
        for node in nodes:
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
            neighbors.extend((query, name) for query in self.optimizer.union_queries(node))
        else:
            passthrough = self._passthrough(node, name)
            if passthrough is not None:
                neighbors.append(passthrough)
        neighbors.extend(self.optimizer.passthrough_parents.get((id(node), name), {}).values())
        set_query = self.optimizer.union_of.get(id(node))
        if set_query is not None:
            neighbors.append((set_query, name))
        return neighbors

    def _column_names(self, node: "SubqueryNode") -> list[str]:
        if isinstance(node, ast.SelectSetQuery):
            return self._column_names(self.optimizer.union_queries(node)[0])
        return [name for name in (_column_name(expr) for expr in node.select) if name is not None]

    def _select_expr(self, node: ast.SelectQuery, name: str) -> ast.Expr | None:
        return next((expr for expr in node.select if _column_name(expr) == name), None)

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
        reads = self.optimizer.reads.get((id(node), name))
        if reads is not None and reads.whole:
            return False
        if isinstance(node, ast.SelectSetQuery):
            # INTERSECT, EXCEPT and UNION DISTINCT compare whole rows, so every column's value counts
            return all(set_node.set_operator.startswith("UNION ALL") for set_node in node.subsequent_select_queries)
        if id(node) in self.optimizer.roots:
            return False
        if id(node) not in self._registered and id(node) not in self.optimizer.union_of:
            # A select inside an expression: its columns are its output
            return False
        if id(node) in self.optimizer.recursive_cte_exprs:
            return False
        if self._passthrough(node, name) is not None:
            return True
        if self._events_source(node, name) is None:
            return False
        # The column's values take part in these, so they have to stay the blob
        if node.distinct or node.group_by or node.group_by_mode is not None or node.having is not None:
            return False
        if self.context.uses_new_events_schema() and reads is not None and "$feature_flags" in reads.keys:
            return False
        return True

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
            if isinstance(node.type, ast.SelectQueryType):
                node.type.columns[name] = replacement.type or ast.UnknownType()
            return
        innermost.expr = map_expr
        if isinstance(innermost.type, ast.FieldAliasType):
            innermost.type.type = _map_type()

    def _map_expr(self, source: ast.Field, keys: list[str]) -> ast.Expr:
        args: list[ast.Expr] = []
        for key in keys:
            args.append(ast.Constant(value=key))
            args.append(_key_json_text(source, key, self.context))
        map_call = ast.Call(name="map", args=args, type=_map_type())
        if keys:
            return map_call
        # Nobody reads a key; `map()` alone has the type Nothing, which a pass-through cannot carry
        return ast.Call(name="accurateCast", args=[map_call, ast.Constant(value=_MAP_TYPE_NAME)], type=_map_type())
