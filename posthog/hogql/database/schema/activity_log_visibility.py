from functools import lru_cache

from posthog.hogql import ast
from posthog.hogql.base import Expr
from posthog.hogql.parser import parse_expr

# Scopes whose rows the REST viewsets restrict per user, which a static predicate cannot express.
#
# `restrict_loop_activity` allows the loops a user may see, computed from live per-loop visibility
# and object-level RBAC. There is no `system.loops` table to defer that decision to, so SQL drops
# every Loop row rather than guess. `restrict_canvas_activity` has the same shape, but
# `system.canvases` already exposes exactly the canvases a caller may read, so Canvas rows defer to
# it. That table is stricter than the viewset — public channels only, and no soft-deleted rows — so
# SQL hides a superset of what REST hides, never less.
_LOOP_ROWS_HIDDEN = "NOT (scope = 'Loop')"
_CANVAS_ROWS_LIMITED_TO_READABLE_CANVASES = "NOT (scope = 'Canvas' AND item_id NOT IN (SELECT id FROM system.canvases))"


@lru_cache(maxsize=1)
def activity_visibility_predicates() -> tuple[Expr, ...]:
    """HogQL form of the activity-log visibility rules, for the federated `system.activity_logs` read.

    A second compiler over the same rule list that `ActivityLogVisibilityManager.build_exclusion_query`
    compiles to a Django Q, plus the per-user scope rules above that the list cannot hold. Together
    these hide at least what the REST viewsets hide. They are deliberately not an exact port: every
    difference below over-hides, so a row readable here is readable through the API too.

    - `allow_staff` is ignored. This table is the customer's surface, so restricted rows stay hidden
      on it unconditionally.
    - `exclude_when` is ignored, so a rule matches on (scope, activity) alone. The only rule using it
      keys on `was_impersonated`, and exposing that column would itself disclose the impersonation the
      rule exists to hide. Over-excluding costs nothing: login rows carry `team_id=None` (see
      `log_login_activity`), so the mandatory team guard already puts them out of reach.
    - Loop rows are dropped outright, and Canvas rows follow `system.canvases`, per the note above.
    """
    # Deferred to keep the ORM off this module's import path, as elsewhere in the schema layer.
    from posthog.models.activity_logging.activity_log import activity_visibility_restrictions  # noqa: PLC0415

    compiled = [
        parse_expr(
            "NOT (scope = {scope} AND activity IN {activities})",
            {
                "scope": ast.Constant(value=rule["scope"]),
                "activities": ast.Constant(value=list(rule["activities"])),
            },
        )
        for rule in activity_visibility_restrictions
    ]
    compiled.append(parse_expr(_LOOP_ROWS_HIDDEN))
    compiled.append(parse_expr(_CANVAS_ROWS_LIMITED_TO_READABLE_CANVASES))
    return tuple(compiled)
