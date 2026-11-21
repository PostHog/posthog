"""Check that a user's access control lets them read everything a HogQL query selects from.

Enforcement lives in the schema: Database.create_for(user) leaves out tables and views the user
is denied, so resolving a query against it fails on anything they can't read - including tables
reached through nested views. Extracting table names and checking them individually would miss
those, so resolution is the only faithful definition of "what this query reads".
"""

from rest_framework import exceptions

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import ExposedHogQLError, ResolutionError, TableAccessDeniedError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_ast_for_printing

from posthog.models import User

from products.access_control.backend.facade import api as access_control_api


def assert_user_can_read_sql(sql: str, team_id: int, user: User, database: Database | None = None) -> None:
    """Raise PermissionDenied unless `user` can read everything `sql` selects from.

    Raise ValidationError when `sql` does not resolve for a reason other than access.

    Pass `database` to reuse an already-built user-scoped schema; building one is the dominant
    cost, so callers checking several queries should build once and share it.
    """
    if not sql.strip():
        raise exceptions.ValidationError("Query is missing.")

    context = HogQLContext(team_id=team_id, user=user, enable_select_queries=True, database=database)
    try:
        # Resolution is where access is enforced, so this doesn't need to print.
        prepare_ast_for_printing(node=parse_select(sql), context=context, dialect="clickhouse")
    except TableAccessDeniedError as err:
        raise exceptions.PermissionDenied(str(err))
    except (ExposedHogQLError, ResolutionError) as err:
        # A query that no longer resolves, such as one reading a renamed column, can't be safely
        # published either, but the user is not denied anything, so it is a bad request.
        raise exceptions.ValidationError(str(err))

    # A materialized copy runs without the user and keeps only the team's default property rules.
    if context.restricted_properties and not context.restricted_properties.issubset(
        access_control_api.get_restricted_properties_with_group_type_index_for_team(user=None, team_id=team_id)
    ):
        raise exceptions.PermissionDenied(
            "Your property access permissions do not allow materializing queries. Ask a project administrator for help."
        )
