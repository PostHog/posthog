"""Temporary ClickHouse pass: recover blanked `$geoip_city_name` / `$geoip_postal_code` event properties at query time.

A bad MaxMind GeoLite2-City release (June 2026 incident) blanked city and postal data on enriched events, and the
ALTER UPDATE backfill over the affected partitions is slow. Until it catches up, this pass patches reads of the two
affected properties: when the stored value is blank but geoip enrichment did run (`$geoip_country_code` is set) the
value is recovered from the event's `$ip` via the `city_postal_ip_trie` ClickHouse dictionary, which was built from a
healthy GeoLite2 build. The country-code guard keeps never-enriched rows (geoip disabled, pre-geoip events) blank, so
only rows the incident could have affected change.

Gated behind `HogQLQueryModifiers.useGeoipDictFallback`, default off (`HOGQL_GEOIP_DICT_FALLBACK` env sets the
instance default). Delete this file with its callsite in `printer/utils.py`, the modifier, and the `lookupGeoip*`
functions once the backfill is done.

Runs between logical property lowering and ClickHouse property resolution: each affected `PropertyAccess` becomes a
conditional over three property reads (the property itself, `$geoip_country_code`, `$ip`), and the resolution pass
then routes each read through its materialized column where one exists — so on cloud the whole fallback runs off
`mat_*` columns plus an in-RAM dictionary lookup, without touching the `properties` blob.
"""

from typing import cast

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.visitor import CloningVisitor, clone_expr

FALLBACK_PROPERTY_TO_FUNCTION = {
    "$geoip_city_name": "lookupGeoipCityName",
    "$geoip_postal_code": "lookupGeoipPostalCode",
}


class GeoipDictFallback(CloningVisitor):
    """Wraps events `properties.$geoip_city_name` / `properties.$geoip_postal_code` reads with the dictionary fallback."""

    def __init__(self, context: HogQLContext) -> None:
        super().__init__(clear_types=False)
        self.context = context

    def visit_property_access(self, node: ast.PropertyAccess) -> ast.Expr:
        node = super().visit_property_access(node)
        if len(node.keys) != 1:
            return node
        function_name = FALLBACK_PROPERTY_TO_FUNCTION.get(str(node.keys[0]))
        if function_name is None or not self._is_events_properties(node):
            return node
        return self._with_fallback(node, function_name)

    def _is_events_properties(self, node: ast.PropertyAccess) -> bool:
        """Only the events `properties` blob is affected — person/group properties keep their stored values."""
        expr_type = node.expr.type
        if not isinstance(expr_type, ast.FieldType) or expr_type.name != "properties":
            return False
        table_type: ast.Type | None = expr_type.table_type
        while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType, ast.VirtualTableType)):
            table_type = table_type.table_type
        if not isinstance(table_type, ast.TableType):
            return False
        return table_type.table.to_printed_clickhouse(self.context) == "events"

    def _with_fallback(self, node: ast.PropertyAccess, function_name: str) -> ast.Expr:
        # The stored value wins whenever it is set; both NULL and '' mean "not set" for these string properties.
        def blob_read(key: str) -> ast.PropertyAccess:
            return ast.PropertyAccess(expr=clone_expr(node.expr), keys=[key], type=ast.StringType(nullable=True))

        def is_set(expr: ast.Expr) -> ast.Expr:
            return ast.Call(
                name="notEmpty",
                args=[ast.Call(name="ifNull", args=[expr, ast.Constant(value="")])],
                type=ast.BooleanType(),
            )

        # nullIf keeps the property's "blank means NULL" semantics when the dictionary has no entry for the IP either.
        recovered = ast.Call(
            name="nullIf",
            args=[
                ast.Call(name=function_name, args=[blob_read("$ip")], type=ast.StringType()),
                ast.Constant(value=""),
            ],
            type=ast.StringType(nullable=True),
        )
        guarded = ast.Call(
            name="if",
            args=[is_set(blob_read("$geoip_country_code")), recovered, clone_expr(node)],
            type=ast.StringType(nullable=True),
        )
        return ast.Call(
            name="if",
            args=[is_set(clone_expr(node)), clone_expr(node), guarded],
            type=ast.StringType(nullable=True),
        )


def apply_geoip_dict_fallback(node: _T_AST, context: HogQLContext) -> _T_AST:
    return cast(_T_AST, GeoipDictFallback(context).visit(node))
