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
from posthog.hogql.database.database import Database
from posthog.hogql.errors import TableAccessDeniedError
from posthog.hogql.modifiers import create_default_modifiers_for_user
from posthog.hogql.printer import prepare_ast_for_printing
from posthog.hogql.property import property_to_expr
from posthog.hogql.visitor import TraversingVisitor

from posthog.constants import AvailableFeature
from posthog.models.team import Team
from posthog.models.user import User

from products.data_tools.backend.facade.models import DataWarehouseJoin

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
            where = property_to_expr(property_filter, team)
        except Exception:
            continue
        try:
            query = ast.SelectQuery(
                select=[ast.Constant(value=1)],
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                where=where,
            )
            prepare_ast_for_printing(query, context=context, dialect="clickhouse")
        except TableAccessDeniedError as e:
            return e.table_name
        except Exception:
            # A filter written for another query shape, such as `e.distinct_id` for a SQL tile that
            # aliases events, does not compile here. Its subqueries can still read a denied table
            # when the tile runs it, so the names it uses are checked without resolving them.
            if context.database is not None and (table := _denied_table_named_in(where, context.database, team)):
                return table
    return None


class _ChainCollector(TraversingVisitor):
    """Collects every field chain in an expression. A table in a FROM or JOIN is a field too."""

    def __init__(self) -> None:
        super().__init__()
        self.chains: list[list[str]] = []

    def visit_field(self, node: ast.Field) -> None:
        self.chains.append([part for part in node.chain if isinstance(part, str)])


def _denied_table_named_in(expr: ast.Expr, database: Database, team: Team) -> str | None:
    """The first denied table a chain in the expression names, or reaches through a warehouse join
    field, or None."""
    collector = _ChainCollector()
    collector.visit(expr)
    denied_join_targets: dict[str, str] | None = None
    for chain in collector.chains:
        for start in range(len(chain)):
            for end in range(start + 1, len(chain) + 1):
                name = ".".join(chain[start:end])
                if database.is_table_access_denied(name):
                    return name
        if denied_join_targets is None:
            denied_join_targets = {
                join.field_name: join.joining_table_name
                for join in DataWarehouseJoin.objects.filter(team=team, deleted=False)
                if database.is_table_access_denied(join.joining_table_name)
            }
        for part in chain:
            if part in denied_join_targets:
                return denied_join_targets[part]
    return None
