"""Table-access check for property filters at save time.

Background jobs evaluate the step filters of an action and the test-account filters of a team.
The web analytics weekly digest and the achievements sweep are two of these jobs. These jobs
have no user, so they bypass warehouse access control. The person who saves a filter must
therefore have read access to each warehouse table that the filter reaches. Without this check,
a person could point a filter at a denied table through a join and read the effect in the
output of the job.
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

# The only filter types that can reach a warehouse table. A behavioral filter can through its nested
# event filters. Event and person property filters cannot.
_WAREHOUSE_REACHING_TYPES = frozenset({"behavioral", "data_warehouse", "data_warehouse_person_property", "hogql"})


def table_blocking_property_filters(user: User, team: Team, filters: list[dict[str, Any]]) -> str | None:
    """The first warehouse table the user cannot read among those the filters reach, or None
    when the filters pass the check."""
    filters = [f for f in filters if f.get("type") in _WAREHOUSE_REACHING_TYPES]
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
    # Each filter is compiled on its own, so one that does not compile cannot hide a denial in
    # another. Only access denials gate the save; anything else is the filter's own problem.
    for property_filter in filters:
        try:
            query = ast.SelectQuery(
                select=[ast.Constant(value=1)],
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                where=property_to_expr(property_filter, team),
            )
            prepare_ast_for_printing(query, context=context, dialect="clickhouse")
        except TableAccessDeniedError as e:
            return e.table_name
        except Exception:
            continue
    return None
