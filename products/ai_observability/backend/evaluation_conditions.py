"""HogQL filter for an evaluation's condition sets, shared by the test-Hog preview and backfills."""

from typing import Any

from posthog.hogql import ast
from posthog.hogql.property import property_to_expr

from posthog.models.team import Team

# cityHash64(key) % 10000 < rollout * 100 gives 0.01% steps, matching the rollout slider. The hash
# differs from the live scheduler's md5 on purpose: the two paths never need to agree, because
# dedupe removes any unit the live path already covered.
_SAMPLING_BUCKETS = 10000


def _sampling_predicate(unit_key: ast.Expr, rollout_percentage: float) -> ast.Expr | None:
    if rollout_percentage >= 100:
        return None
    return ast.CompareOperation(
        op=ast.CompareOperationOp.Lt,
        left=ast.ArithmeticOperation(
            op=ast.ArithmeticOperationOp.Mod,
            left=ast.Call(name="cityHash64", args=[unit_key]),
            right=ast.Constant(value=_SAMPLING_BUCKETS),
        ),
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
