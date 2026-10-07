"""Save-time table-access check for property filters that scheduled jobs run without a user.

An action's step filters and a team's test-account filters are evaluated by background jobs
that have no acting user, such as the web analytics weekly digest and the achievements sweep.
Those jobs run with warehouse access control bypassed, so the person who saves a filter must be
able to read every warehouse table it reaches. Otherwise the filter would be an escalation
channel: point it at a restricted table through a join, and read the effect in the output.
"""

from typing import Any

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import TableAccessDeniedError
from posthog.hogql.modifiers import create_default_modifiers_for_user
from posthog.hogql.printer import prepare_ast_for_printing
from posthog.hogql.property import property_to_expr

from posthog.constants import AvailableFeature
from posthog.models.team import Team
from posthog.models.user import User


def table_blocking_property_filters(user: User, team: Team, filters: list[dict[str, Any]]) -> str | None:
    """The first warehouse table the user cannot read among those the filters reach, or None
    when the filters pass the check."""
    if not filters:
        return None
    # No access rule can deny a table in an organization without the feature, so the filters are
    # not compiled for it.
    if not team.organization.is_feature_available(AvailableFeature.ACCESS_CONTROL):
        return None

    context = HogQLContext(
        team_id=team.pk,
        team=team,
        user=user,
        enable_select_queries=True,
        modifiers=create_default_modifiers_for_user(user, team),
    )
    query = ast.SelectQuery(
        select=[ast.Constant(value=1)],
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=property_to_expr(filters, team),
    )
    try:
        prepare_ast_for_printing(query, context=context, dialect="clickhouse")
    except TableAccessDeniedError as e:
        return e.table_name
    except Exception:
        # Only access denials gate the save; anything else is the filter's own problem.
        return None
    return None


def access_denied_message(table_name: str) -> str:
    return f"This filter uses the table '{table_name}', which you don't have access to."
