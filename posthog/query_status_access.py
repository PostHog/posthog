from collections.abc import Collection, Iterable
from typing import TYPE_CHECKING, Optional

from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request

from posthog.schema import QueryStatus

from posthog.hogql.database.database import READ_SCOPE_QUERY_STATUS_LABEL_PREFIX, denied_posthog_table_scopes

from posthog.exceptions import InsufficientScope
from posthog.permissions import scopes_caller_lacks

if TYPE_CHECKING:
    from posthog.models import Team, User
    from posthog.shared_link_user import SharedLinkUser
    from posthog.synthetic_user import SyntheticUser


def read_scopes_from_labels(labels: Optional[Iterable[str]]) -> set[str]:
    return {
        label.removeprefix(READ_SCOPE_QUERY_STATUS_LABEL_PREFIX)
        for label in labels or []
        if label.startswith(READ_SCOPE_QUERY_STATUS_LABEL_PREFIX)
    }


def assert_read_scopes_readable(
    read_scopes: Collection[str],
    team: "Team",
    principal: "Optional[User | SyntheticUser | SharedLinkUser]",
    request: Optional[Request] = None,
) -> None:
    """Raise unless the principal may read every resource a stored result was computed from.

    The run that produced the result may have had no user, or a different one, so this is the only
    check between its rows and whoever polls for them. No principal means nobody to check, so deny.
    """
    if not read_scopes:
        return
    missing = scopes_caller_lacks(request, [f"{scope}:read" for scope in sorted(read_scopes)])
    if missing:
        raise InsufficientScope(missing, detail=f"This result also needs: {', '.join(missing)}.")
    if principal is None or not denied_posthog_table_scopes(team, principal).isdisjoint(read_scopes):
        raise PermissionDenied("You don't have access to the data this result was read from.")


def assert_query_status_readable(
    status: QueryStatus,
    team: "Team",
    principal: "Optional[User | SyntheticUser | SharedLinkUser]",
    request: Optional[Request] = None,
) -> None:
    assert_read_scopes_readable(read_scopes_from_labels(status.labels), team, principal, request)
