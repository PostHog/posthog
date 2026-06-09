"""First pass: turn every `properties.x` read into a plain `JSONFieldAccess` node.

A property read starts life as a `Field` tagged with a `PropertyType` ("this is a property"). This pass rewrites each one
into a `JSONFieldAccess` — "read this key path out of this JSON blob". It makes no decision about *how* to read the
property and never looks at materialized columns; that keeps it simple and the same for every database backend. After it
runs, each printer just renders the node in its own JSON syntax — the property is no longer something the printer has to
figure out. On ClickHouse a second pass (`clickhouse_physical_passes`) runs next and swaps the node for a faster column
when one exists; the warehouse backends have no second pass, so for them this lowering is the whole story.

It deliberately leaves four things alone, to stay minimal and change nothing about the output:

- Struct / array (data-warehouse) columns — they use different access syntax, so only JSON-blob columns lower here.
- Person/group properties read through a joined subquery — those print as `alias.field`, not as a property read.
- The numeric/boolean cast — on ClickHouse the swapper wraps the property in a cast before this pass runs, so the cast
  simply ends up wrapping the `JSONFieldAccess` and is carried through untouched.
- Access control — the node still points at the raw blob `Field`, which the ClickHouse printer drops restricted keys
  from later, so a restricted value still collapses to `''`.
"""

from typing import cast

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import StringJSONDatabaseField
from posthog.hogql.visitor import CloningVisitor


class LogicalPropertyLowering(CloningVisitor):
    """Replaces JSON-blob `properties.X` Field reads with `JSONFieldAccess`. Descends every position (CloningVisitor)."""

    def __init__(self, context: HogQLContext) -> None:
        # The lowered AST is printed directly after this pass, so keep resolved types rather than clearing them.
        super().__init__(clear_types=False)
        self.context = context

    def visit_field(self, node: ast.Field) -> ast.Expr:
        lowered = self._lower_property_field(node)
        return lowered if lowered is not None else super().visit_field(node)

    def visit_alias(self, node: ast.Alias) -> ast.Alias:
        # A property read is often wrapped in a hidden alias (`properties.x AS x`). That alias node holds the
        # `PropertyType` in two places: on the inner field, and again inside its own `FieldAliasType` wrapper. Lowering
        # the inner field fixes the first; if we leave the wrapper pointing at the old `PropertyType`, later code that
        # unwraps the alias still sees "this is a property" and sends the operand back into the property-handling path we
        # just bypassed. So repoint the wrapper at the lowered value type. This is type bookkeeping only — printing uses
        # `expr` and `alias`, never the wrapper's inner type, so the output is unchanged.
        lowered = super().visit_alias(node)
        if (
            isinstance(lowered.expr, ast.JSONFieldAccess)
            and lowered.expr.type is not None
            and isinstance(lowered.type, ast.FieldAliasType)
            and isinstance(lowered.type.type, ast.PropertyType)
        ):
            lowered.type = ast.FieldAliasType(alias=lowered.type.alias, type=lowered.expr.type)
        return lowered

    def _lower_property_field(self, node: ast.Field) -> ast.JSONFieldAccess | None:
        property_type = node.type
        if not isinstance(property_type, ast.PropertyType):
            return None
        # A repointed person/group property is read as a plain aliased column from its joined subquery, not a property.
        if property_type.joined_subquery is not None:
            return None
        chain = property_type.chain
        base_field_type = property_type.field_type
        # Only lower reads off a JSON blob column (`properties` / `person_properties`). Struct/array warehouse columns
        # resolve to a non-JSON database field and keep their existing printer handling.
        if not isinstance(base_field_type.resolve_database_field(self.context), StringJSONDatabaseField):
            return None

        # chain[0] is always the top-level property name (a string). Deeper elements keep their Python type: an integer
        # is an array index that must reach the JSON extract as an integer, not the string "1" (which would be the object
        # key "1").
        keys: list[str | int] = [str(chain[0])]
        keys.extend(link if isinstance(link, int) else str(link) for link in chain[1:])

        # The node's type is its *value* type — the JSON-extract result, a nullable String — not a `PropertyType`. A
        # `PropertyType` here would still mean "this is a property" and send a lowered comparison operand back into the
        # property-handling path we just bypassed. Everything a later pass needs (table, field, property name) is already
        # on `expr` (the blob `Field`, whose `.type` is the source `FieldType`) and `keys`. The type must be nullable so
        # the printer keeps wrapping the read in `ifNull(...)`; a JSON read can always miss the key.
        return ast.JSONFieldAccess(
            expr=ast.Field(chain=[base_field_type.name], type=base_field_type),
            keys=keys,
            type=ast.StringType(nullable=True),
        )


def lower_property_access(node: _T_AST, context: HogQLContext) -> _T_AST:
    """Lower JSON-blob property reads to `JSONFieldAccess`, including the within-non-HogQL (lightweight-DELETE) path."""
    return cast(_T_AST, LogicalPropertyLowering(context).visit(node))
