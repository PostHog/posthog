from functools import lru_cache

from posthog.hogql import ast
from posthog.hogql.base import Expr
from posthog.hogql.parser import parse_expr


@lru_cache(maxsize=1)
def activity_visibility_predicates() -> tuple[Expr, ...]:
    """HogQL form of the activity-log visibility rules, for the federated `system.activity_logs` read.

    A second compiler over the same rule list that `ActivityLogVisibilityManager.build_exclusion_query`
    compiles to a Django Q, so SQL hides what REST hides. Adding a rule covers both surfaces.

    Two deliberate differences, both fail-closed:

    - `allow_staff` is ignored. Staff read activity through the API; this table is the customer's
      surface, so the restricted rows stay hidden on it unconditionally.
    - `exclude_when` is ignored, so a rule matches on (scope, activity) alone. The only rule using it
      keys on `was_impersonated`, and exposing that column would itself disclose the impersonation the
      rule exists to hide. Over-excluding costs nothing: login rows carry `team_id=None` (see
      `log_login_activity`), so the mandatory team guard already puts them out of reach.
    """
    # Deferred to keep the ORM off this module's import path, as elsewhere in the schema layer.
    from posthog.models.activity_logging.visibility_rules import activity_visibility_restrictions  # noqa: PLC0415

    return tuple(
        parse_expr(
            "NOT (scope = {scope} AND activity IN {activities})",
            {
                "scope": ast.Constant(value=rule["scope"]),
                "activities": ast.Constant(value=list(rule["activities"])),
            },
        )
        for rule in activity_visibility_restrictions
    )
