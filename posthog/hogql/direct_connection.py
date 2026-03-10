from collections.abc import Callable
from typing import TYPE_CHECKING, Optional

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.database.database import Database
from posthog.hogql.timings import HogQLTimings

from products.data_warehouse.backend.models import ExternalDataSource
from products.data_warehouse.backend.models.external_data_source import get_direct_external_data_source_for_connection

if TYPE_CHECKING:
    from posthog.models import Team, User


INVALID_CONNECTION_ID_ERROR = "Invalid connectionId for this team"


def get_direct_connection_source(team: "Team", connection_id: str | None) -> ExternalDataSource | None:
    return get_direct_external_data_source_for_connection(team_id=team.pk, connection_id=connection_id)


def get_direct_connection_source_none_or_raise(
    team: "Team",
    connection_id: str | None,
    *,
    error_factory: Callable[[str], Exception],
) -> ExternalDataSource | None:
    source = get_direct_connection_source(team, connection_id)
    if connection_id and source is None:
        raise error_factory(INVALID_CONNECTION_ID_ERROR)
    return source


def create_database_for_connection_source(
    team: "Team",
    *,
    user: Optional["User"] = None,
    source: ExternalDataSource | None = None,
    modifiers: HogQLQueryModifiers | None = None,
    timings: HogQLTimings | None = None,
) -> Database:
    return Database.create_for(
        team=team,
        user=user,
        modifiers=modifiers,
        timings=timings,
        connection_id=str(source.id) if source else None,
    )


def resolve_database_for_connection(
    team: "Team",
    connection_id: str | None,
    *,
    user: Optional["User"] = None,
    modifiers: HogQLQueryModifiers | None = None,
    timings: HogQLTimings | None = None,
    error_factory: Callable[[str], Exception],
) -> tuple[ExternalDataSource | None, Database]:
    source = get_direct_connection_source_none_or_raise(team, connection_id, error_factory=error_factory)
    database = create_database_for_connection_source(
        team,
        user=user,
        source=source,
        modifiers=modifiers,
        timings=timings,
    )
    return source, database
