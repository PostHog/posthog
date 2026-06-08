"""Logical property lowering: `properties.X` (a `Field` typed as `PropertyType`) → the `JSONFieldAccess` node.

This is the first of the two passes that replaced the printer's old property handling. It does one thing: turn every
JSON-blob property read into a plain "read this key path from this blob" node (`JSONFieldAccess`). It makes **no decision
about how** to read the property — it does not look at materialized columns. That keeps it schema-driven and
dialect-agnostic: after it runs, each printer renders the node mechanically in its own JSON syntax, and the property is no
longer something the printer has to resolve. On ClickHouse, the *second* pass (the materialized-column / property-group /
skip-index physical passes) runs next and rewrites the node to a concrete column read when a backing column exists; for
the warehouse dialects there is no second pass, so this lowering is the whole story.

What it deliberately does NOT touch (left to the printer or a later pass, to keep this pass minimal and behavior-
preserving):

- Struct / array (data-warehouse) columns — different access syntax; only `StringJSONDatabaseField` sources lower here.
- `joined_subquery` refs — a repointed person/group property prints as `alias.field`, not a property read.
- The scalar cast — for ClickHouse it is applied by `PropertySwapper` *around* the property before this pass runs, so
  the cast `Call` simply ends up wrapping the `JSONFieldAccess` and is preserved automatically.
- Access control (restricted-key drop) — the `JSONFieldAccess.expr` is the blob `Field`, which the ClickHouse printer
  still `JSONDropKeys`-wraps in `visit_field_type`, so the restricted value collapses to `''` exactly as on master.
"""

from dataclasses import replace
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
        # An `Alias` over a property read (e.g. the hidden `properties.x AS x` the resolver/swapper inserts) carries a
        # `FieldAliasType` whose `.type` is the original `PropertyType`. When we lower the inner Field to a
        # `JSONFieldAccess`, that wrapper's type must stop pointing at the `PropertyType` too — otherwise the printer's
        # `resolve_field_type` unwraps the `FieldAliasType` back to the `PropertyType` and routes the operand into its
        # property-decision code (defeating the deletion gate). Repoint it at the lowered value type. This
        # only rewrites the alias-type wrapper; printing reads `expr` + `alias`, not the wrapper's inner type, so output
        # is unchanged.
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
        if not chain:
            return None

        base_field_type = property_type.field_type
        # Only lower reads off a JSON blob column (`properties` / `person_properties`). Struct/array warehouse columns
        # resolve to a non-JSON database field and keep their existing printer handling.
        if not isinstance(base_field_type.resolve_database_field(self.context), StringJSONDatabaseField):
            return None

        # chain[0] is always the top-level property name (a string). Deeper elements keep their Python type: an integer
        # is an array index that must reach the JSON extract as an integer, not the string "1" (object key "1"). This
        # mirrors how the legacy `visit_property_type` blob fallback passes the chain through untyped.
        keys: list[str | int] = [str(chain[0])]
        keys.extend(link if isinstance(link, int) else str(link) for link in chain[1:])

        # On the within_non_hogql_query (lightweight-DELETE) path the raw blob column must also print unqualified — the
        # mutation analyzer rejects `sharded_events.properties` just as it rejects qualified mat columns. Mark the blob
        # field's type so the printer drops the prefix when this access stays a JSON-blob read (no materialized backing).
        blob_field_type = (
            replace(base_field_type, unqualified=True) if self.context.within_non_hogql_query else base_field_type
        )

        # The node carries its *value* type (the raw JSON-extract result, a nullable String), NOT the original
        # `PropertyType`. Carrying the `PropertyType` would make the node mean "this is still a property access" (the
        # ambient-meaning smell) — and would route a lowered comparison operand back into the printer's property-decision
        # code via `resolve_field_type`, defeating the deletion gate. Everything a downstream pass needs (table, field,
        # property name) is in `expr` (the blob `Field`, whose `.type` is the source `FieldType`) plus `keys`. The
        # nullable String keeps the printer's comparison `ifNull(...)` wrapping identical to the `PropertyType` it
        # replaced (`_is_type_nullable` returns True for both).
        return ast.JSONFieldAccess(
            expr=ast.Field(chain=[blob_field_type.name], type=blob_field_type),
            keys=keys,
            type=ast.StringType(nullable=True),
        )


def lower_property_access(node: _T_AST, context: HogQLContext) -> _T_AST:
    """Lower JSON-blob property reads to `JSONFieldAccess`, including the within-non-HogQL (lightweight-DELETE) path.

    On that path the lowered reads carry `unqualified=True` on their source field (and the ClickHouse physical pass marks
    the synthetic materialized-column fields the same way), so the printer drops the table prefix the lightweight-DELETE
    mutation analyzer rejects.
    """
    return cast(_T_AST, LogicalPropertyLowering(context).visit(node))
