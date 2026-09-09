"""HogQL filter for an evaluation's condition sets, shared by the test-Hog preview and backfills."""

from typing import Any

from posthog.hogql import ast
from posthog.hogql.property import property_to_expr

from posthog.models.team import Team

# Buckets of 0.01%, matching the rollout slider.
_SAMPLING_BUCKETS = 10000


def _rollout_bucket(unit_key: ast.Expr) -> ast.Expr:
    """The bucket the live scheduler puts this unit in, rebuilt in SQL.

    `checkRolloutPercentage` in the evaluation scheduler reads the first four bytes of the key's
    md5 as a big-endian integer, then takes it modulo the bucket count. Any other hash would put
    the same unit in a different bucket, so a backfill would sample a disjoint share of the
    population and grade far more units than the rollout asks for.
    """
    first_four_bytes = ast.Call(
        name="unhex",
        args=[
            ast.Call(
                name="substring",
                args=[
                    ast.Call(name="hex", args=[ast.Call(name="MD5", args=[unit_key])]),
                    ast.Constant(value=1),
                    ast.Constant(value=8),
                ],
            )
        ],
    )
    return ast.ArithmeticOperation(
        op=ast.ArithmeticOperationOp.Mod,
        # reinterpretAsUInt32 reads little-endian, so the bytes are reversed to read them the way
        # the scheduler's parseInt does.
        left=ast.Call(name="reinterpretAsUInt32", args=[ast.Call(name="reverse", args=[first_four_bytes])]),
        right=ast.Constant(value=_SAMPLING_BUCKETS),
    )


def _sampling_predicate(unit_key: ast.Expr, rollout_percentage: float) -> ast.Expr | None:
    if rollout_percentage >= 100:
        return None
    return ast.CompareOperation(
        op=ast.CompareOperationOp.Lt,
        left=_rollout_bucket(unit_key),
        right=ast.Constant(value=int(round(rollout_percentage * 100))),
    )


def build_condition_filter(
    conditions: list[dict[str, Any]], team: Team, unit_key: ast.Expr | None = None
) -> ast.Expr | None:
    """OR across condition sets, AND within a set (properties, and sampling when a unit key is given)."""
    sets: list[ast.Expr] = []
    for condition in conditions:
        parts: list[ast.Expr] = []
        props = condition.get("properties") or []
        if props:
            parts.append(property_to_expr(props, team))
        if unit_key is not None:
            sampling = _sampling_predicate(unit_key, float(condition.get("rollout_percentage", 100)))
            if sampling is not None:
                parts.append(sampling)
        if len(parts) > 1:
            sets.append(ast.And(exprs=parts))
        else:
            sets.append(parts[0] if parts else ast.Constant(value=True))
    if not sets:
        return None
    return sets[0] if len(sets) == 1 else ast.Or(exprs=sets)
