from collections.abc import Callable
from typing import TYPE_CHECKING, Optional, cast
from uuid import UUID

from common.hogql.backend import resolve_backend_symbol as _resolve_backend_symbol
from common.hogql.database.database import Database
from common.hogql.errors import ExposedHogQLError
from common.hogql.timings import HogQLTimings

HogQLQueryModifiers = _resolve_backend_symbol("posthog.schema", "HogQLQueryModifiers")
UserAccessControl = _resolve_backend_symbol("posthog.rbac.user_access_control", "UserAccessControl")
ExternalDataSource = _resolve_backend_symbol(
    "products.warehouse_sources.backend.models.external_data_source", "ExternalDataSource"
)


if TYPE_CHECKING:
    Team = _resolve_backend_symbol("posthog.models", "Team")
    User = _resolve_backend_symbol("posthog.models", "User")
    MySQLSourceConfig = _resolve_backend_symbol(
        "posthog.temporal.data_imports.sources.generated_configs", "MySQLSourceConfig"
    )
    PostgresSourceConfig = _resolve_backend_symbol(
        "posthog.temporal.data_imports.sources.generated_configs", "PostgresSourceConfig"
    )
    MySQLImplementation = _resolve_backend_symbol(
        "posthog.temporal.data_imports.sources.mysql.mysql", "MySQLImplementation"
    )
    PostgresSource = _resolve_backend_symbol("posthog.temporal.data_imports.sources.postgres.source", "PostgresSource")


INVALID_CONNECTION_ID_ERROR = (
    "Invalid connectionId: not a direct external data source (access_method='direct') in this team. "
    "Warehouse import sources are not valid here."
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

    source = (
        ExternalDataSource.objects.filter(
            team_id=team.pk,
            id=source_uuid,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
        )
        .exclude(deleted=True)
        .first()
    )
    if source is None:
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


def validate_direct_postgres_source_config(
    source: ExternalDataSource, team: "Team"
) -> tuple["PostgresSource", "PostgresSourceConfig"]:
    SourceRegistry = _resolve_backend_symbol("posthog.temporal.data_imports.sources", "SourceRegistry")
    PostgresSource = _resolve_backend_symbol("posthog.temporal.data_imports.sources.postgres.source", "PostgresSource")

    ExternalDataSourceType = _resolve_backend_symbol("products.data_warehouse.backend.types", "ExternalDataSourceType")

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


def validate_direct_mysql_source_config(
    source: ExternalDataSource, team: "Team"
) -> tuple["MySQLImplementation", "MySQLSourceConfig"]:
    SourceRegistry = _resolve_backend_symbol("posthog.temporal.data_imports.sources", "SourceRegistry")
    MySQLSource = _resolve_backend_symbol("posthog.temporal.data_imports.sources.mysql.source", "MySQLSource")

    ExternalDataSourceType = _resolve_backend_symbol("products.data_warehouse.backend.types", "ExternalDataSourceType")

    if not source.is_direct_mysql:
        raise ExposedHogQLError("Invalid direct MySQL connection.")

    mysql_source = cast(MySQLSource, SourceRegistry.get_source(ExternalDataSourceType.MYSQL))
    config = mysql_source.parse_config(source.job_inputs or {})

    is_ssh_valid, ssh_valid_errors = mysql_source.ssh_tunnel_is_valid(config, team.pk)
    if not is_ssh_valid:
        raise ExposedHogQLError(ssh_valid_errors or "Invalid SSH tunnel configuration.")

    valid_host, host_errors = mysql_source.is_database_host_valid(
        config.host, team.pk, using_ssh_tunnel=config.ssh_tunnel.enabled if config.ssh_tunnel else False
    )
    if not valid_host:
        raise ExposedHogQLError(host_errors or "Invalid MySQL host.")

    return mysql_source.get_implementation, config
