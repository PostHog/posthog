from collections.abc import Callable
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from django.db.models import Model

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.database.database import Database
from posthog.hogql.timings import HogQLTimings

from posthog.ph_client import feature_enabled_or_false
from posthog.shared_link_user import SharedLinkUser
from posthog.synthetic_user import SyntheticUser

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceAccessMethod, ManagedWarehouseSQLMode

if TYPE_CHECKING:
    from posthog.models import Team, User


INVALID_CONNECTION_ID_ERROR = (
    "Invalid connectionId: no direct-query-capable data source with this id in this team, "
    "or you don't have access to it."
)

RAW_QUERY_TABLE_DENIED_ERROR = (
    "You don't have access to every table on this connection, so raw SQL is not allowed here. "
    "Drop sendRawQuery to run the query as HogQL, which enforces access per table."
)


def raw_query_denied_by_table_access(
    team: "Team",
    source: ExternalDataSource,
    *,
    user: Optional["User | SyntheticUser | SharedLinkUser"],
    user_access_control: Optional[UserAccessControl] = None,
    bypass_warehouse_access_control: bool = False,
) -> bool:
    """Whether table-level access control forbids running a *raw* query against this connection.

    Raw SQL is opaque — we never parse it, so we can't tell which tables it reads — and therefore the
    per-table check the HogQL path runs (`Database._is_warehouse_table_denied`) can't be applied
    statement by statement. To stop raw mode from becoming a way around that check, it may run only
    when the caller can read *every* table on the connection; a denial on even one table forbids it.
    Gating mirrors the HogQL build: the feature flag must be on, principals that bypass warehouse
    access control by design are exempt, and a userless context fails closed.
    """
    if bypass_warehouse_access_control or isinstance(user, SyntheticUser | SharedLinkUser):
        return False

    if not feature_enabled_or_false(
        "hogql-warehouse-access-control",
        str(team.uuid),
        groups={"organization": str(team.organization_id), "project": str(team.id)},
        group_properties={
            "organization": {"id": str(team.organization_id)},
            "project": {"id": str(team.id)},
        },
        send_feature_flag_events=False,
    ):
        return False

    if user is None:
        return True

    uac = user_access_control or UserAccessControl(user=user, team=team)
    if uac.is_organization_admin:
        return False

    tables: list[Model] = list(
        DataWarehouseTable.objects.queryable().filter(team_id=team.pk, external_data_source_id=source.id)
    )
    if not tables:
        return False
    uac.preload_object_access_controls(tables)
    return any(not uac.check_access_level_for_object(table, required_level="viewer") for table in tables)


def get_direct_connection_source(
    team: "Team", connection_id: str | None, *, user: Optional["User"] = None, require_pure_direct: bool = False
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
        .defer("job_inputs")
        .first()
    )
    if source is None or not is_direct_capable(source):
        return None

    managed_warehouse_mode: ManagedWarehouseSQLMode | None = None
    if source.has_managed_warehouse_prefix:
        managed_warehouse_mode = source.managed_warehouse_sql_mode
        if managed_warehouse_mode == ManagedWarehouseSQLMode.UNAVAILABLE:
            return None

    # Synced (warehouse) sources only expose their `should_sync` catalog — raw SQL bypasses that
    # boundary and reads any upstream table, so raw queries are pure-direct only. Pure-direct
    # sources have no restricted catalog to bypass; the whole external database is the intended
    # surface.
    if require_pure_direct and source.access_method != ExternalDataSourceAccessMethod.DIRECT:
        return None

    if (
        user is not None
        and managed_warehouse_mode != ManagedWarehouseSQLMode.BUILT_IN
        and not UserAccessControl(user=user, team=team).check_access_level_for_object(source, required_level="viewer")
    ):
        return None

    return source


def get_direct_connection_source_none_or_raise(
    team: "Team",
    connection_id: str | None,
    *,
    user: Optional["User"] = None,
    error_factory: Callable[[str], Exception],
    require_pure_direct: bool = False,
) -> ExternalDataSource | None:
    source = get_direct_connection_source(team, connection_id, user=user, require_pure_direct=require_pure_direct)
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
