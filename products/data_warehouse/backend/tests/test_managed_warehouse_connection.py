from typing import TypedDict

import pytest
from unittest.mock import MagicMock, patch

from posthog.hogql.direct_connection import get_direct_connection_source
from posthog.hogql.query import HogQLQueryExecutor

from posthog.ducklake import cp_teams
from posthog.ducklake.models import DuckgresServer
from posthog.models import Organization, Team

from products.data_warehouse.backend.direct_postgres import DIRECT_POSTGRES_URL_PATTERN
from products.data_warehouse.backend.managed_warehouse_connection import (
    MANAGED_WAREHOUSE_SOURCE_PREFIX,
    ensure_managed_warehouse_direct_source,
    internal_schemas,
    reconcile_managed_warehouse_tables,
    soft_delete_managed_warehouse_sources,
    update_managed_warehouse_root_password,
)
from products.data_warehouse.backend.presentation.views import managed_warehouse
from products.data_warehouse.backend.tasks import reconcile_all_managed_warehouse_tables_task
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema


class _Connection(TypedDict):
    host: str
    port: int
    database: str
    username: str
    password: str


_CONNECTION: _Connection = {
    "host": "wh.dw.us.postwh.com",
    "port": 5432,
    "database": "ducklake",
    "username": "root",
    "password": "pw",
}


# Per-test control-plane membership rows, keyed by org id. The CP is the read source for
# the periodic sweep's team enumeration, so tests register rows here instead of creating
# Django rows — the per-team connection itself no longer consults the control plane.
_MEMBERSHIPS: dict[str, list[dict]] = {}


def _add_membership(
    team: Team, schema_name: str = "prod", *, legacy_shared: bool = False, backfill_enabled: bool = True
) -> None:
    org_id = str(team.organization_id)
    row = {
        "org_id": org_id,
        "team_id": team.id,
        "schema_name": f"team_{team.id}" if legacy_shared else schema_name,
        "enabled": True,
        "backfill_enabled": backfill_enabled,
        "events_table_name": "events" if legacy_shared else f"events_{schema_name}",
        "persons_table_name": "persons" if legacy_shared else f"persons_{schema_name}",
        "schema_data_imports_name": None,
        "earliest_event_date": None,
    }
    _MEMBERSHIPS.setdefault(org_id, []).append(row)
    cp_teams.clear_cache()


def _clear_memberships() -> None:
    _MEMBERSHIPS.clear()
    cp_teams.clear_cache()


@pytest.fixture(autouse=True)
def _cp_memberships():
    _clear_memberships()
    with patch(
        "posthog.ducklake.cp_teams._fetch_org_rows",
        side_effect=lambda org_id: list(_MEMBERSHIPS.get(str(org_id), [])),
    ):
        yield
    _clear_memberships()


def _ensure(team: Team) -> ExternalDataSource:
    return ensure_managed_warehouse_direct_source(team_id=team.id, organization_id=team.organization_id)


def _create_server(org: Organization, **overrides: object) -> DuckgresServer:
    return DuckgresServer.objects.create(organization=org, **{**_CONNECTION, **overrides})


@pytest.mark.django_db
class TestEnsureManagedWarehouseDirectSource:
    def test_creates_a_query_source_with_the_org_root_credential(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _create_server(org)

        source = _ensure(team)

        assert source.source_type == "Postgres"
        assert source.access_method == ExternalDataSource.AccessMethod.DIRECT
        assert source.direct_query_enabled is True
        assert isinstance(source.connection_metadata, dict)
        assert source.connection_metadata["engine"] == "duckdb"
        assert source.prefix == MANAGED_WAREHOUSE_SOURCE_PREFIX
        # job_inputs carry the org root credential so live queries see every schema.
        assert source.job_inputs["host"] == _CONNECTION["host"]
        assert source.job_inputs["user"] == _CONNECTION["username"]
        assert source.job_inputs["password"] == _CONNECTION["password"]
        assert source.connection_metadata["credential_kind"] == "org_root"

    def test_is_idempotent(self) -> None:
        # Without dedup, every status poll / re-enable would spawn a duplicate connection.
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _create_server(org)

        first = _ensure(team)
        second = _ensure(team)

        assert first.pk == second.pk
        assert ExternalDataSource.objects.filter(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX).count() == 1

    def test_works_for_a_legacy_shared_tables_team(self) -> None:
        # No per-team reader policy exists anymore, so nothing about the team's row
        # layout (including the legacy shared tables) blocks its connection.
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _create_server(org)
        _add_membership(team, legacy_shared=True)

        source = _ensure(team)

        assert source.direct_query_enabled is True
        assert isinstance(source.connection_metadata, dict)
        assert source.connection_metadata["credential_kind"] == "org_root"

    def test_needs_no_control_plane_membership(self) -> None:
        # Root needs no handshake: a team the control plane doesn't know about still
        # gets its connection.
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _create_server(org)

        source = _ensure(team)

        assert source.direct_query_enabled is True
        assert isinstance(source.connection_metadata, dict)
        assert source.connection_metadata["credential_kind"] == "org_root"

    def test_refreshes_a_project_reader_source_onto_the_root_credential(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _create_server(org)
        source = ExternalDataSource.objects.create(
            team=team,
            source_id="managed-source",
            connection_id="managed-connection",
            destination_id="managed-destination",
            status=ExternalDataSource.Status.RUNNING,
            source_type="Postgres",
            prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            direct_query_enabled=True,
            job_inputs={
                "host": _CONNECTION["host"],
                "port": _CONNECTION["port"],
                "database": _CONNECTION["database"],
                "user": f"posthog_team_{team.id}",
                "password": "reader-password",
            },
            connection_metadata={
                "engine": "duckdb",
                "system_managed": True,
                "credential_kind": "project_reader",
                "reader_configured": True,
            },
        )
        team_schema = ExternalDataSchema.objects.create(
            team=team,
            source=source,
            name="posthog.events_prod",
            should_sync=True,
        )

        managed_source = _ensure(team)

        managed_source.refresh_from_db()
        team_schema.refresh_from_db()
        assert managed_source.id == source.id
        assert managed_source.job_inputs["user"] == _CONNECTION["username"]
        assert managed_source.job_inputs["password"] == _CONNECTION["password"]
        assert managed_source.direct_query_enabled is True
        assert isinstance(managed_source.connection_metadata, dict)
        assert managed_source.connection_metadata["credential_kind"] == "org_root"
        assert "reader_configured" not in managed_source.connection_metadata
        # Reader-discovered catalogs are already bounded and stay in place; only the
        # swappable credential changes.
        assert team_schema.deleted is False

    def test_removes_existing_schemas_when_upgrading_a_root_managed_source(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _create_server(org)
        source = ExternalDataSource.objects.create(
            team=team,
            source_id="managed-source",
            connection_id="managed-connection",
            destination_id="managed-destination",
            status=ExternalDataSource.Status.RUNNING,
            source_type="Postgres",
            prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"password": "old-password"},
            connection_metadata={"engine": "duckdb", "system_managed": True},
        )
        schema = ExternalDataSchema.objects.create(
            team=team,
            source=source,
            name="events_other_team",
            should_sync=True,
        )

        managed_source = _ensure(team)

        assert managed_source.id == source.id
        assert managed_source.access_method == ExternalDataSource.AccessMethod.DIRECT
        assert not ExternalDataSchema.objects.filter(id=schema.id).exists()


def _source_schema(table_name: str, source_schema: str = "posthog") -> SourceSchema:
    return SourceSchema(
        name=f"{source_schema}.{table_name}",
        supports_incremental=False,
        supports_append=False,
        columns=[("uuid", "uuid", False), ("timestamp", "timestamp", True)],
        source_schema=source_schema,
        source_table_name=table_name,
    )


@pytest.mark.django_db
class TestReconcileManagedWarehouseTables:
    def _setup(self) -> tuple[Organization, Team]:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _create_server(org)
        _add_membership(team)
        return org, team

    def test_discovers_the_whole_org_catalog_and_makes_it_queryable(self) -> None:
        org, team = self._setup()
        other_team = Team.objects.create(organization=org)
        # Discovery runs as root, so every team's schema shows up on this team's source;
        # only engine-internal schemas are excluded.
        discovered = [
            _source_schema("events_prod"),
            _source_schema("persons_prod"),
            _source_schema("events_other"),
            _source_schema("customers", "posthog_data_imports_prod"),
            _source_schema("revenue", f"shadow_{team.id}_models"),
            _source_schema("future_table", f"team_{team.id}"),
            _source_schema("orders", f"team_{other_team.id}"),
            _source_schema("pg_stat_activity", "pg_catalog"),
            _source_schema("tables", "information_schema"),
        ]

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            return_value=discovered,
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        source = ExternalDataSource.objects.get(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX)
        assert source.access_method == ExternalDataSource.AccessMethod.DIRECT
        assert set(
            ExternalDataSchema.objects.filter(source_id=source.id, should_sync=True).values_list("name", flat=True)
        ) == {
            "posthog.events_prod",
            "posthog.persons_prod",
            "posthog.events_other",
            "posthog_data_imports_prod.customers",
            f"shadow_{team.id}_models.revenue",
            f"team_{team.id}.future_table",
            f"team_{other_team.id}.orders",
        }
        assert set(
            DataWarehouseTable.raw_objects.filter(external_data_source_id=source.id, deleted=False).values_list(
                "name", flat=True
            )
        ) == {
            "posthog.events_prod",
            "posthog.persons_prod",
            "posthog.events_other",
            "posthog_data_imports_prod.customers",
            f"shadow_{team.id}_models.revenue",
            f"team_{team.id}.future_table",
            f"team_{other_team.id}.orders",
        }

        allowed_query = HogQLQueryExecutor(
            query="SELECT uuid FROM posthog.events_prod",
            team=team,
            connection_id=str(source.id),
        )
        sql, _context = allowed_query.generate_clickhouse_sql()
        assert "events_prod" in sql

        metadata_cursor = MagicMock()
        metadata_cursor.fetchone.return_value = ("ducklake", "Duckgres")
        query_cursor = MagicMock()
        query_cursor.fetchall.return_value = [("row-uuid",)]
        column = MagicMock(type_code=25)
        column.name = "uuid"
        query_cursor.description = [column]
        connection = MagicMock()
        connection.execute.side_effect = [metadata_cursor, MagicMock()]
        connection.cursor.return_value.__enter__.return_value = query_cursor
        with patch("posthog.hogql.direct_sql.postgres_adapter.psycopg.connect") as connect:
            connect.return_value.__enter__.return_value = connection
            response = allowed_query.execute()

        assert response.results == [("row-uuid",)]
        assert [call.args[0] for call in connection.execute.call_args_list] == [
            "SELECT current_database(), version()",
            "USE ducklake",
        ]
        query_cursor.execute.assert_called_once_with(sql, None)

        # Tables from other teams in the org are queryable too — org-wide visibility
        # is the point of the root credential.
        cross_team_query = HogQLQueryExecutor(
            query=f"SELECT uuid FROM team_{other_team.id}.orders",
            team=team,
            connection_id=str(source.id),
        )
        cross_sql, _context = cross_team_query.generate_clickhouse_sql()
        assert "orders" in cross_sql

        assert get_direct_connection_source(team, str(source.id), require_pure_direct=True) == source

    def test_discovers_only_internal_schemas_registers_nothing(self) -> None:
        org, team = self._setup()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            return_value=[
                _source_schema("pg_stat_activity", "pg_catalog"),
                _source_schema("tables", "information_schema"),
            ],
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        source = ExternalDataSource.objects.get(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX)
        assert not ExternalDataSchema.objects.filter(source_id=source.id).exists()

    def test_reintrospects_to_pick_up_new_tables(self) -> None:
        org, team = self._setup()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            return_value=[_source_schema("events_prod"), _source_schema("persons_prod")],
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            return_value=[
                _source_schema("events_prod"),
                _source_schema("persons_prod"),
                _source_schema("new_model", f"shadow_{team.id}_models"),
            ],
        ) as get_schemas:
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)
            get_schemas.assert_called_once()
        source = ExternalDataSource.objects.get(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX)
        assert ExternalDataSchema.objects.filter(source=source, name=f"shadow_{team.id}_models.new_model").exists()

    def test_reintrospection_revives_a_dropped_and_recreated_table(self) -> None:
        org, team = self._setup()
        table = _source_schema("recreated", f"team_{team.id}")
        events = _source_schema("events_prod")

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            return_value=[events, table],
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            return_value=[events],
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            return_value=[events, table],
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        source = ExternalDataSource.objects.get(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX)
        schema = ExternalDataSchema.objects.get(source=source, name=f"team_{team.id}.recreated")
        assert schema.deleted is False
        assert schema.table is not None
        assert schema.table.deleted is False

    def test_skips_quietly_when_the_warehouse_is_not_reachable(self) -> None:
        # A provisioning warehouse fails introspection on every sweep; that must not raise.
        org, team = self._setup()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            side_effect=ConnectionRefusedError("still provisioning"),
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        source = ExternalDataSource.objects.get(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX)
        assert not ExternalDataSchema.objects.filter(source_id=source.id).exists()

    def test_periodic_sweep_schedules_every_managed_project(self) -> None:
        org, team = self._setup()
        all_rows = _MEMBERSHIPS[str(org.id)] + [
            # Legacy shared-table membership: root-backed sources support it, so the
            # sweep schedules it like any other row.
            {
                "org_id": str(org.id),
                "team_id": team.id + 1,
                "schema_name": "team_x",
                "backfill_enabled": True,
                "events_table_name": "events",
            }
        ]

        with (
            patch("posthog.ducklake.cp_teams._fetch_all_rows", return_value=all_rows),
            patch(
                "products.data_warehouse.backend.tasks.tasks.schedule_managed_warehouse_tables_reconcile"
            ) as schedule,
        ):
            reconcile_all_managed_warehouse_tables_task()

        assert schedule.call_count == 2
        assert {call.kwargs["team_id"] for call in schedule.call_args_list} == {team.id, team.id + 1}

    def test_periodic_sweep_skips_run_when_control_plane_unreachable(self) -> None:
        with (
            patch("posthog.ducklake.cp_teams._fetch_all_rows", return_value=None),
            patch(
                "products.data_warehouse.backend.tasks.tasks.schedule_managed_warehouse_tables_reconcile"
            ) as schedule,
        ):
            reconcile_all_managed_warehouse_tables_task()

        schedule.assert_not_called()

    def test_registers_a_connection_for_a_team_without_cp_membership(self) -> None:
        # The connection no longer depends on control-plane membership: any team in an org
        # with a provisioned warehouse gets one on reconcile.
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        _create_server(org)

        reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        assert ExternalDataSource.objects.filter(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX).exists()

    def test_reconciles_for_a_legacy_shared_tables_team(self) -> None:
        org, team = self._setup()
        _clear_memberships()
        _add_membership(team, legacy_shared=True)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            return_value=[_source_schema("events")],
        ) as get_schemas:
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        get_schemas.assert_called_once()
        source = ExternalDataSource.objects.get(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX)
        assert ExternalDataSchema.objects.filter(source_id=source.id, name="posthog.events").exists()

    def test_rejects_a_team_membership_from_another_organization(self) -> None:
        org_a = Organization.objects.create(name="Org A")
        org_b = Organization.objects.create(name="Org B")
        team_b = Team.objects.create(organization=org_b)
        _create_server(org_a, host="a.example.com", password="org-a-password")
        _create_server(org_b, host="b.example.com", password="org-b-password")
        _add_membership(team_b, "b")

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas"
        ) as get_schemas:
            reconcile_managed_warehouse_tables(team_id=team_b.id, organization_id=org_a.id)

        assert not ExternalDataSource.objects.filter(team_id=team_b.id).exists()
        get_schemas.assert_not_called()


@pytest.mark.django_db
class TestManagedWarehouseLifecycle:
    def _org_team_source(self) -> tuple[Organization, Team, ExternalDataSource, DuckgresServer]:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        server = _create_server(org)
        source = ensure_managed_warehouse_direct_source(team_id=team.id, organization_id=org.id)
        return org, team, source, server

    def test_update_root_password_rotates_the_server_and_every_managed_source(self) -> None:
        org, team, source, server = self._org_team_source()
        other_team = Team.objects.create(organization=org)
        other_source = ensure_managed_warehouse_direct_source(team_id=other_team.id, organization_id=org.id)

        update_managed_warehouse_root_password(organization_id=org.id, password="rotated")

        source.refresh_from_db()
        other_source.refresh_from_db()
        server.refresh_from_db()
        assert isinstance(source.job_inputs, dict)
        assert isinstance(other_source.job_inputs, dict)
        assert source.job_inputs["password"] == "rotated"
        assert other_source.job_inputs["password"] == "rotated"
        assert server.password == "rotated"

    def test_update_root_password_skips_soft_deleted_sources(self) -> None:
        org, _team, source, server = self._org_team_source()
        soft_delete_managed_warehouse_sources(organization_id=org.id)

        update_managed_warehouse_root_password(organization_id=org.id, password="rotated")

        source.refresh_from_db()
        server.refresh_from_db()
        assert server.password == "rotated"
        assert isinstance(source.job_inputs, dict)
        assert source.job_inputs["password"] == _CONNECTION["password"]
        # The next ensure revives the source and rewrites its credential from the server.
        revived = ensure_managed_warehouse_direct_source(team_id=source.team_id, organization_id=org.id)
        assert revived.deleted is False
        assert isinstance(revived.job_inputs, dict)
        assert revived.job_inputs["password"] == "rotated"

    def test_soft_delete_removes_sources_and_their_tables(self) -> None:
        org, team, source, _server = self._org_team_source()
        table = DataWarehouseTable.objects.create(
            name="events_prod",
            format=DataWarehouseTable.TableFormat.Parquet,
            team_id=team.id,
            url_pattern=DIRECT_POSTGRES_URL_PATTERN,
            external_data_source=source,
            columns={},
            options={},
        )

        soft_delete_managed_warehouse_sources(organization_id=org.id)

        source.refresh_from_db()
        table.refresh_from_db()
        assert source.deleted is True
        assert table.deleted is True

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas"
        ) as get_schemas:
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        source.refresh_from_db()
        assert source.deleted is True
        assert (
            ExternalDataSource._base_manager.filter(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX).count()
            == 1
        )
        get_schemas.assert_not_called()

    def test_soft_delete_is_atomic_across_all_organization_sources(self) -> None:
        org = Organization.objects.create(name="Org")
        _create_server(org)
        team_a = Team.objects.create(organization=org)
        team_b = Team.objects.create(organization=org)
        source_a = _ensure(team_a)
        source_b = _ensure(team_b)
        original_save = ExternalDataSource.save

        def fail_on_second_source(instance: ExternalDataSource, *args: object, **kwargs: object) -> None:
            if instance.id == source_b.id:
                raise RuntimeError("database write failed")
            original_save(instance, *args, **kwargs)

        with (
            patch.object(ExternalDataSource, "save", new=fail_on_second_source),
            pytest.raises(RuntimeError, match="database write failed"),
        ):
            soft_delete_managed_warehouse_sources(organization_id=org.id)

        source_a.refresh_from_db()
        source_b.refresh_from_db()
        assert source_a.deleted is False
        assert source_b.deleted is False


class TestInternalSchemas:
    def test_excludes_only_engine_internals(self) -> None:
        assert internal_schemas() == {"pg_catalog", "information_schema", "pg_toast", "system"}


@patch("products.data_warehouse.backend.facade.api.schedule_managed_warehouse_tables_reconcile")
def test_ready_status_queues_table_discovery(mock_schedule: MagicMock) -> None:
    organization_id = "a8fd15f0-1ed3-480b-a859-b10bba374acf"

    managed_warehouse.ensure_direct_connection_tables(team_id=42, organization_id=organization_id)

    mock_schedule.assert_called_once_with(team_id=42, organization_id=organization_id)
