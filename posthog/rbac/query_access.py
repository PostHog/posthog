"""Check that a user's access control lets them read everything a HogQL query selects from.

Enforcement lives in the schema: Database.create_for(user) leaves out tables and views the user
is denied, so resolving a query against it fails on anything they can't read - including tables
reached through nested views. Extracting table names and checking them individually would miss
those, so resolution is the only faithful definition of "what this query reads".
"""

from rest_framework import exceptions

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import ExposedHogQLError, ResolutionError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_ast_for_printing

from posthog.models import User


def assert_user_can_read_query(query: dict | None, team_id: int, user: User, database: Database | None = None) -> None:
    """Raise PermissionDenied unless `user` can read everything `query` selects from.

    Pass `database` to reuse an already-built user-scoped schema; building one is the dominant
    cost, so callers checking several queries should build once and share it.
    """
    sql = (query or {}).get("query")
    if not isinstance(sql, str) or not sql.strip():
        raise exceptions.ValidationError("Query is missing.")

    context = HogQLContext(team_id=team_id, user=user, enable_select_queries=True, database=database)
    try:
        # Resolution is where access is enforced, so this doesn't need to print.
        prepare_ast_for_printing(node=parse_select(sql), context=context, dialect="clickhouse")
    except (ExposedHogQLError, ResolutionError) as err:
        # Surfaces "You don't have access to table `X`." for a denial; a query that no longer
        # resolves for any reason also can't be safely published, so it's refused the same way.
        raise exceptions.PermissionDenied(str(err))
