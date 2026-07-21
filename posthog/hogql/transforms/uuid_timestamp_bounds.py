"""Derive events.timestamp bounds from UUIDv7 uuid point lookups.

An events query filtering on `uuid = '<constant>'` with no timestamp filter scans the team's full
event history. Event UUIDs are UUIDv7: server-assigned ones embed the event's own timestamp, and
SDK-generated ones embed the client clock at event creation. So a UUIDv7 constant pins the matched
row's timestamp to the constant's embedded time, give or take client clock skew. When every row a
SELECT's WHERE can match has its uuid pinned to known UUIDv7 constants, we AND a constant
`timestamp` range (buffered each side) onto that WHERE, letting ClickHouse prune partitions and
granules by primary key instead of reading full history.

Fail-safe, mirroring the sessions WhereClauseExtractor: each AND conjunct contributes bounds
independently; an OR contributes only when every branch is bounded (union of the ranges); NOT and
anything unrecognized contribute nothing. Constants that are not valid UUIDv7s contribute nothing,
so lookups for legacy or foreign uuids keep their unbounded scan.

The buffer absorbs divergence between the uuid's embedded clock and the stored (skew-corrected)
timestamp. Events further out than the buffer — e.g. backfills captured with an SDK-fresh uuid but
an explicitly historical timestamp — are missed by a bounded lookup; that trade-off is accepted as
part of the move to all-UUIDv7 event uuids, and `uuidV7TimestampBounds: false` opts a query out.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.visitor import TraversingVisitor

if TYPE_CHECKING:
    from posthog.schema import HogQLQueryModifiers

UUID_V7_TIMESTAMP_BUFFER = timedelta(days=3)


def uuid_v7_timestamp_bounds_enabled(modifiers: "HogQLQueryModifiers") -> bool:
    """On unless explicitly disabled, so ad-hoc queries benefit without opting in."""
    return modifiers.uuidV7TimestampBounds is not False


def apply_uuid_v7_timestamp_bounds(node: _T_AST) -> _T_AST:
    UuidV7TimestampBoundsTransform().visit(node)
    return node


@dataclass
class _Bound:
    lower: datetime
    upper: datetime
    # Chain prefix of the uuid field reference that produced the bound (e.g. ["e"] for e.uuid),
    # reused to reference `timestamp` on the same scan.
    chain_prefix: list[str | int]


def _uuid_v7_embedded_datetime(value: object) -> Optional[datetime]:
    if isinstance(value, UUID):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = UUID(value)
        except ValueError:
            return None
    else:
        return None
    if parsed.version != 7:
        return None
    # The high 48 bits of a UUIDv7 hold the Unix-millisecond timestamp.
    return datetime.fromtimestamp((parsed.int >> 80) / 1000, tz=UTC)


def _unwrap_aliases(expr: ast.Expr) -> ast.Expr:
    while isinstance(expr, ast.Alias):
        expr = expr.expr
    return expr


def _constant_embedded_datetime(expr: ast.Expr) -> Optional[datetime]:
    expr = _unwrap_aliases(expr)
    if isinstance(expr, ast.Call) and expr.name in ("toUUID", "toUUIDOrNull", "toUUIDOrZero") and len(expr.args) == 1:
        expr = _unwrap_aliases(expr.args[0])
    if isinstance(expr, ast.Constant):
        return _uuid_v7_embedded_datetime(expr.value)
    return None


class UuidV7TimestampBoundsTransform(TraversingVisitor):
    def visit_select_query(self, node: ast.SelectQuery):
        super().visit_select_query(node)

        scan_ids = self._events_scan_ids(node)
        if not scan_ids:
            return

        bounds: dict[int, _Bound] = {}
        for clause in (node.where, node.prewhere):
            if clause is not None:
                bounds = _intersect_bounds(bounds, self._bounds_from_expr(clause, scan_ids))

        for scan_id, bound in bounds.items():
            # The injected fields are typed by hand (this runs after the type resolver), against
            # the same table type the uuid comparison resolved to.
            scan_type = scan_ids[scan_id]
            lower_field = ast.Field(
                chain=[*bound.chain_prefix, "timestamp"],
                type=ast.FieldType(name="timestamp", table_type=scan_type),
            )
            upper_field = ast.Field(
                chain=[*bound.chain_prefix, "timestamp"],
                type=ast.FieldType(name="timestamp", table_type=scan_type),
            )
            condition = ast.And(
                exprs=[
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.GtEq,
                        left=lower_field,
                        right=ast.Constant(value=bound.lower - UUID_V7_TIMESTAMP_BUFFER),
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.LtEq,
                        left=upper_field,
                        right=ast.Constant(value=bound.upper + UUID_V7_TIMESTAMP_BUFFER),
                    ),
                ]
            )
            node.where = condition if node.where is None else ast.And(exprs=[node.where, condition])

    def _events_scan_ids(self, node: ast.SelectQuery) -> dict[int, ast.TableType | ast.TableAliasType]:
        """Table types of events-table scans in this SELECT's FROM/JOIN chain, keyed by identity."""
        result: dict[int, ast.TableType | ast.TableAliasType] = {}
        join = node.select_from
        while join is not None:
            join_type = join.type
            if isinstance(join_type, (ast.TableType, ast.TableAliasType)):
                base: ast.Type = join_type
                while isinstance(base, ast.TableAliasType):
                    base = base.table_type
                if isinstance(base, ast.TableType) and isinstance(base.table, EventsTable):
                    result[id(join_type)] = join_type
            join = join.next_join
        return result

    def _bounds_from_expr(
        self, expr: ast.Expr, scan_ids: dict[int, ast.TableType | ast.TableAliasType]
    ) -> dict[int, _Bound]:
        if isinstance(expr, ast.And):
            merged: dict[int, _Bound] = {}
            for child in expr.exprs:
                merged = _intersect_bounds(merged, self._bounds_from_expr(child, scan_ids))
            return merged

        if isinstance(expr, ast.Or):
            branch_bounds = [self._bounds_from_expr(child, scan_ids) for child in expr.exprs]
            if not branch_bounds:
                return {}
            shared_keys = set(branch_bounds[0])
            for branch in branch_bounds[1:]:
                shared_keys &= set(branch)
            return {
                key: _Bound(
                    lower=min(branch[key].lower for branch in branch_bounds),
                    upper=max(branch[key].upper for branch in branch_bounds),
                    chain_prefix=branch_bounds[0][key].chain_prefix,
                )
                for key in shared_keys
            }

        if isinstance(expr, ast.Call):
            if expr.name == "and":
                return self._bounds_from_expr(ast.And(exprs=expr.args), scan_ids)
            if expr.name == "or":
                return self._bounds_from_expr(ast.Or(exprs=expr.args), scan_ids)
            if expr.name == "equals" and len(expr.args) == 2:
                return self._bounds_from_compare(
                    ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=expr.args[0], right=expr.args[1]),
                    scan_ids,
                )
            if expr.name == "in" and len(expr.args) == 2:
                return self._bounds_from_compare(
                    ast.CompareOperation(op=ast.CompareOperationOp.In, left=expr.args[0], right=expr.args[1]),
                    scan_ids,
                )
            return {}

        if isinstance(expr, ast.CompareOperation):
            return self._bounds_from_compare(expr, scan_ids)

        return {}

    def _bounds_from_compare(
        self, node: ast.CompareOperation, scan_ids: dict[int, ast.TableType | ast.TableAliasType]
    ) -> dict[int, _Bound]:
        if node.op == ast.CompareOperationOp.Eq:
            for field_side, constant_side in ((node.left, node.right), (node.right, node.left)):
                scan_match = self._match_uuid_field(field_side, scan_ids)
                if scan_match is None:
                    continue
                embedded = _constant_embedded_datetime(constant_side)
                if embedded is None:
                    return {}
                scan_id, chain_prefix = scan_match
                return {scan_id: _Bound(lower=embedded, upper=embedded, chain_prefix=chain_prefix)}
            return {}

        if node.op == ast.CompareOperationOp.In:
            scan_match = self._match_uuid_field(node.left, scan_ids)
            if scan_match is None:
                return {}
            if isinstance(node.right, (ast.Tuple, ast.Array)):
                elements = node.right.exprs
            else:
                elements = [node.right]
            if not elements:
                return {}
            embedded_datetimes = [_constant_embedded_datetime(element) for element in elements]
            if any(embedded is None for embedded in embedded_datetimes):
                return {}
            resolved = [embedded for embedded in embedded_datetimes if embedded is not None]
            scan_id, chain_prefix = scan_match
            return {scan_id: _Bound(lower=min(resolved), upper=max(resolved), chain_prefix=chain_prefix)}

        return {}

    def _match_uuid_field(
        self, expr: ast.Expr, scan_ids: dict[int, ast.TableType | ast.TableAliasType]
    ) -> Optional[tuple[int, list[str | int]]]:
        expr = _unwrap_aliases(expr)
        if not isinstance(expr, ast.Field):
            return None
        field_type = expr.type
        if isinstance(field_type, ast.FieldAliasType):
            field_type = field_type.type
        if not isinstance(field_type, ast.FieldType) or field_type.name != "uuid":
            return None
        if id(field_type.table_type) not in scan_ids:
            return None
        return id(field_type.table_type), list(expr.chain[:-1])


def _intersect_bounds(left: dict[int, _Bound], right: dict[int, _Bound]) -> dict[int, _Bound]:
    """Merge bounds from two conjuncts; overlapping scans keep the tighter (intersected) range."""
    merged = dict(left)
    for key, bound in right.items():
        existing = merged.get(key)
        if existing is None:
            merged[key] = bound
        else:
            merged[key] = _Bound(
                lower=max(existing.lower, bound.lower),
                upper=min(existing.upper, bound.upper),
                chain_prefix=existing.chain_prefix,
            )
    return merged
