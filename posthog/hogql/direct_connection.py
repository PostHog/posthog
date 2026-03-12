from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Optional, cast
from uuid import UUID

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.database.database import Database
from posthog.hogql.database.ducklake_database import DuckLakeDatabase
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.timings import HogQLTimings

from products.data_warehouse.backend.models import ExternalDataSource

if TYPE_CHECKING:
    from posthog.models import Team, User
    from posthog.temporal.data_imports.sources.generated_configs import PostgresSourceConfig
    from posthog.temporal.data_imports.sources.postgres.source import PostgresSource


INVALID_CONNECTION_ID_ERROR = "Invalid connectionId for this team"
DUCKLAKE_CONNECTION_ID = "ducklake://default"


@dataclass(frozen=True)
class ResolvedConnection:
    connection_id: str
    kind: Literal["direct_postgres", "ducklake"]
    source: ExternalDataSource | None = None


def is_ducklake_connection_id(connection_id: str | None) -> bool:
    return connection_id == DUCKLAKE_CONNECTION_ID


def get_direct_connection_source(team: "Team", connection_id: str | None) -> ExternalDataSource | None:
    if not connection_id:
        return None

    try:
        source_uuid = UUID(connection_id)
    except ValueError:
        return None

    return (
        ExternalDataSource.objects.filter(
            team_id=team.pk,
            id=source_uuid,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
        )
        .exclude(deleted=True)
        .first()
    )


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


def resolve_connection_none_or_raise(
    team: "Team",
    connection_id: str | None,
    *,
    error_factory: Callable[[str], Exception],
) -> ResolvedConnection | None:
    if not connection_id:
        return None

    if is_ducklake_connection_id(connection_id):
        if not team.has_ducklake:
            raise error_factory(INVALID_CONNECTION_ID_ERROR)
        return ResolvedConnection(connection_id=DUCKLAKE_CONNECTION_ID, kind="ducklake")

    source = get_direct_connection_source_none_or_raise(team, connection_id, error_factory=error_factory)
    if source is None:
        return None

    return ResolvedConnection(connection_id=str(source.id), kind="direct_postgres", source=source)


def resolve_database_for_connection(
    team: "Team",
    connection_id: str | None,
    *,
    user: Optional["User"] = None,
    modifiers: HogQLQueryModifiers | None = None,
    timings: HogQLTimings | None = None,
    error_factory: Callable[[str], Exception],
) -> tuple[ResolvedConnection | None, Database]:
    resolved_connection = resolve_connection_none_or_raise(team, connection_id, error_factory=error_factory)

    if resolved_connection is not None and resolved_connection.kind == "ducklake":
        database = DuckLakeDatabase.create_for(
            team=team,
            user=user,
            modifiers=modifiers,
            timings=timings,
            connection_id=resolved_connection.connection_id,
        )
        return resolved_connection, database

    database = Database.create_for(
        team=team,
        user=user,
        modifiers=modifiers,
        timings=timings,
        connection_id=resolved_connection.connection_id if resolved_connection else None,
    )
    return resolved_connection, database


def validate_direct_postgres_source_config(
    source: ExternalDataSource, team: "Team"
) -> tuple["PostgresSource", "PostgresSourceConfig"]:
    from posthog.temporal.data_imports.sources import SourceRegistry
    from posthog.temporal.data_imports.sources.postgres.source import PostgresSource

    from products.data_warehouse.backend.types import ExternalDataSourceType

    if not source.is_direct_postgres:
        raise ExposedHogQLError("Invalid direct Postgres connection.")

    postgres_source = cast(PostgresSource, SourceRegistry.get_source(ExternalDataSourceType.POSTGRES))
    config = postgres_source.parse_config(source.job_inputs or {})

    is_ssh_valid, ssh_valid_errors = postgres_source.ssh_tunnel_is_valid(config, team.pk)
    if not is_ssh_valid:
        raise ExposedHogQLError(ssh_valid_errors or "Invalid SSH tunnel configuration.")

    valid_host, host_errors = postgres_source.is_database_host_valid(
        config.host, team.pk, using_ssh_tunnel=config.ssh_tunnel.enabled if config.ssh_tunnel else False
    )
    if not valid_host:
        raise ExposedHogQLError(host_errors or "Invalid Postgres host.")

    return postgres_source, config
