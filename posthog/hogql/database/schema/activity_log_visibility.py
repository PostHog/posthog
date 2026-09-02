import json
import hashlib
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
# SQL hides a superset of what REST hides, never less. Deferring to it makes activity-log rows depend
# on the caller's canvas grants, so a read of this table also partitions the query cache on `canvas`
# (see `_TRANSITIVE_SYSTEM_TABLE_SCOPES`) — a cache hit returns before these predicates ever print.
CANVASES_TABLE = "system.canvases"
_LOOP_ROWS_HIDDEN = "NOT (scope = 'Loop')"
_CANVAS_ROWS_HIDDEN = "NOT (scope = 'Canvas')"
# `toString` on the canvas id is load-bearing. `item_id` is a String holding the id of whatever object
# the row is about, and most of those are numeric (`11510926` for an insight), while a canvas id is a
# real UUID once the federated read types it. ClickHouse coerces the left side of an IN to the set's
# type, and it does that for every row rather than only the Canvas ones, so an unconverted set makes
# any read of this table die on the first numeric id: "Cannot parse uuid 11510926".
_CANVAS_ROWS_LIMITED_TO_READABLE_CANVASES = (
    f"NOT (scope = 'Canvas' AND item_id NOT IN (SELECT toString(id) FROM {CANVASES_TABLE}))"
)

# Bumped whenever the compilation shape changes in a way the hashed inputs below cannot see, e.g. a rule
# key starting to matter, or a predicate gaining a clause that reads a new column.
_POLICY_SHAPE = 1


@lru_cache(maxsize=1)
def activity_log_visibility_policy_version() -> str:
    """Fingerprint of the rules this module compiles, for the query cache key.

    Nothing else in the key tracks them, and a cache hit returns before they print, so a result stored
    under the previous rules would keep serving the rows the current ones hide.
    `HogQLQueryRunner.get_cache_payload` folds this into the key of every query reading the table, so a
    rule change retires those results. Hashing the inputs rather than hand-bumping a version means
    editing the shared rule list is enough; nobody has to remember the second step.
    """
    # Deferred to keep the ORM off this module's import path, as elsewhere in the schema layer.
    from posthog.models.activity_logging.activity_log import activity_visibility_restrictions  # noqa: PLC0415

    material = json.dumps(
        {
            "shape": _POLICY_SHAPE,
            "rules": [[rule["scope"], sorted(rule["activities"])] for rule in activity_visibility_restrictions],
            "scope_predicates": [_LOOP_ROWS_HIDDEN, _CANVAS_ROWS_HIDDEN, _CANVAS_ROWS_LIMITED_TO_READABLE_CANVASES],
        },
        sort_keys=True,
    )
    return hashlib.sha256(material.encode()).hexdigest()[:16]


@lru_cache(maxsize=2)
def activity_visibility_predicates(canvases_readable: bool) -> tuple[Expr, ...]:
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

    `canvases_readable` says whether `system.canvases` is in the caller's schema. When the canvas
    resource is denied outright the table is removed (see `_apply_system_table_access`), and a
    predicate referencing it would raise rather than filter — so Canvas rows are dropped instead,
    which is what a caller who may read no canvas would see anyway.
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
    compiled.append(parse_expr(_CANVAS_ROWS_LIMITED_TO_READABLE_CANVASES if canvases_readable else _CANVAS_ROWS_HIDDEN))
    return tuple(compiled)
