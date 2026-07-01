from collections.abc import Callable
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.database.database import Database
from posthog.hogql.timings import HogQLTimings

from posthog.rbac.user_access_control import UserAccessControl

from products.warehouse_sources.backend.facade.models import ExternalDataSource

if TYPE_CHECKING:
    from posthog.models import Team, User


INVALID_CONNECTION_ID_ERROR = (
    "Invalid connectionId: no direct-query-capable data source with this id in this team, "
    "or you don't have access to it."
)


def get_direct_connection_source(
    team: "Team", connection_id: str | None, *, user: Optional["User"] = None
) -> ExternalDataSource | None:
    if not connection_id:
        return None

    try:
        source_uuid = UUID(connection_id)
    except ValueError:
        return None

    # Function-local: keeps the direct-SQL driver imports off the django.setup() path (startup-import-budget).
    from posthog.hogql.direct_sql.capability import is_direct_capable  # noqa: PLC0415

    source = (
        ExternalDataSource.objects.filter(
            team_id=team.pk,
            id=source_uuid,
        )
        .exclude(deleted=True)
        .first()
    )
    if source is None or not is_direct_capable(source):
        return None

    if user is not None and not UserAccessControl(user=user, team=team).check_access_level_for_object(
        source, required_level="viewer"
    ):
        return None

    return source


def get_direct_connection_source_none_or_raise(
    team: "Team",
    connection_id: str | None,
    *,
    user: Optional["User"] = None,
    error_factory: Callable[[str], Exception],
) -> ExternalDataSource | None:
    source = get_direct_connection_source(team, connection_id, user=user)
    if connection_id and source is None:
        raise error_factory(INVALID_CONNECTION_ID_ERROR)
    return source


def resolve_database_for_connection(
    team: "Team",
    connection_id: str | None,
    *,
    user: Optional["User"] = None,
    modifiers: HogQLQueryModifiers | None = None,
    timings: HogQLTimings | None = None,
    error_factory: Callable[[str], Exception],
) -> tuple[ExternalDataSource | None, Database]:
    source = get_direct_connection_source_none_or_raise(team, connection_id, user=user, error_factory=error_factory)
    database = Database.create_for(
        team=team,
        user=user,
        modifiers=modifiers,
        timings=timings,
        connection_id=str(source.id) if source else None,
    )
    return source, database
