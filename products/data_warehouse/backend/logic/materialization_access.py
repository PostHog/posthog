"""Access check for turning a view into materialized data.

Materialization runs the query as the system and stores the rows in a table of its own, which then
resolves under the view's access rules alone - the underlying tables are no longer part of the query
at read time. That makes enabling it a declassification, so it has to be gated on the requester's
access to what the query reads.

Writing a view's query is already gated this way (the serializer resolves it as the author), but
enabling materialization on an existing view never touches the query, so it needs the same check
applied at every door that can turn it on.
"""

from rest_framework import exceptions

from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import ExposedHogQLError, ResolutionError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_ast_for_printing

from posthog.models import User


def assert_can_materialize(query: dict | None, team_id: int, user: User) -> None:
    """Raise PermissionDenied unless `user` can read everything `query` selects from.

    Resolution is where table and view access is enforced, so this resolves without printing.
    """
    sql = (query or {}).get("query")
    if not isinstance(sql, str) or not sql.strip():
        raise exceptions.ValidationError("Cannot materialize a view with no query.")

    context = HogQLContext(team_id=team_id, user=user, enable_select_queries=True)
    try:
        prepare_ast_for_printing(node=parse_select(sql), context=context, dialect="clickhouse")
    except (ExposedHogQLError, ResolutionError) as err:
        # Surfaces "You don't have access to table `X`." for a denial; a query that no longer
        # resolves for any reason also can't be safely published, so it's refused the same way.
        raise exceptions.PermissionDenied(f"Cannot materialize this view: {err}")
