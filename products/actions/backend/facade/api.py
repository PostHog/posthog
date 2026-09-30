"""
Facade API for actions.

This is the module that other apps / the presentation layer should
import from. It accepts plain inputs and returns HogQL conditions or
contract DTOs, never ORM instances or QuerySets.

Do NOT:
- Import DRF / serializers / HTTP concerns here
- Return ORM instances or QuerySets
"""

from __future__ import annotations

from collections.abc import Sequence

from posthog.hogql import ast
from posthog.hogql.property import action_to_expr

from posthog.models import Team

from products.actions.backend.models.action import Action


def action_filter_conditions(*, team: Team, action_ids: Sequence[int]) -> dict[int, ast.Expr]:
    """The HogQL condition matching each action's events, keyed by action id.

    Lets another product filter events by action without holding the Action model, which stays in
    this product. A caller that puts a condition in two places in one query must clone it with
    `clone_expr`, because the HogQL resolver annotates the nodes it walks.

    Scoped to the team's project, the same way actions are read everywhere else.

    An action is absent from the result when it belongs to another project, when it is deleted, or
    when it has no steps. A stepless action compiles to a condition that matches every event, which
    reads as a filter but is not one.
    """
    if not action_ids:
        return {}

    conditions: dict[int, ast.Expr] = {}
    for action in Action.objects.filter(team__project_id=team.project_id, id__in=action_ids, deleted=False):
        if not action.steps:
            continue
        try:
            conditions[action.id] = action_to_expr(action)
        except Exception:
            # One action with an uncompilable step must not cost the caller the rest of them.
            continue
    return conditions
