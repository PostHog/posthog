"""Which tables a user cannot read among a set of saved queries.

The compile core behind every save-time access gate: publishing a public link, editing an exposed
artifact, and saving a subscription all ask this one question about the acting person.
"""

from typing import Any

from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import TableAccessDeniedError
from posthog.hogql.modifiers import create_default_modifiers_for_user
from posthog.hogql.printer import prepare_ast_for_printing

from posthog.hogql_queries.query_runner import get_query_runner_or_none
from posthog.models import Team, User

from products.access_control.backend.facade.user_access_control import UserAccessControlError


def blocked_access_for_user(user: User, team: Team, queries: list[dict[str, Any]]) -> list[str]:
    """Tables (and runner-level resources) the user can't access among everything the given
    queries read. Each query is compiled (resolved, not executed) as the user, the same resolution
    the read path uses. Non-access compile errors don't gate. Empty list = the user can run them all."""
    if not queries:
        return []

    # One context for all queries: the publisher's schema is built on first prepare and reused.
    context = HogQLContext(
        team_id=team.pk,
        team=team,
        user=user,
        enable_select_queries=True,
        modifiers=create_default_modifiers_for_user(user, team),
    )
    blocked: set[str] = set()
    for query in queries:
        try:
            # get_query_runner unwraps container nodes (DataTableNode, InsightVizNode, ...) itself.
            runner = get_query_runner_or_none(query, team, user=user)
            if runner is None:
                continue
            # Resource-level check first for product runners (logs, metrics, customer analytics, ...)
            runner.validate_query_runner_access(user)
            prepare_ast_for_printing(runner.to_query(), context=context, dialect="clickhouse")
        except UserAccessControlError as e:
            blocked.add(e.resource)
        except TableAccessDeniedError as e:
            blocked.add(e.table_name)
        except Exception:
            # Only access denials gate publishing; anything else is the query's own problem.
            continue
    return sorted(blocked)
