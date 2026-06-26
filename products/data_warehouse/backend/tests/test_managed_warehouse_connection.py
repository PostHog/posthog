from typing import TypedDict

import pytest
from unittest.mock import MagicMock, patch

from posthog.hogql.errors import ExposedHogQLError, QueryError
from posthog.hogql.query import HogQLQueryExecutor

from posthog.ducklake.models import DuckgresServer, DuckgresServerTeam
from posthog.models import Organization, Team

from products.data_warehouse.backend.direct_postgres import DIRECT_POSTGRES_URL_PATTERN
from products.data_warehouse.backend.managed_warehouse_connection import (
    MANAGED_WAREHOUSE_SOURCE_PREFIX,
    ensure_managed_warehouse_direct_source,
    reconcile_managed_warehouse_tables,
    soft_delete_managed_warehouse_sources,
    update_managed_warehouse_password,
)
from products.data_warehouse.backend.presentation.views import managed_warehouse
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


def _ensure(team: Team) -> ExternalDataSource:
    return ensure_managed_warehouse_direct_source(team_id=team.id, organization_id=team.organization_id)


@pytest.mark.django_db
class TestEnsureManagedWarehouseDirectSource:
    def test_creates_a_restricted_postgres_query_source_from_the_server(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        server = DuckgresServer.objects.create(
            organization=org,
            host=_CONNECTION["host"],
            port=_CONNECTION["port"],
            database=_CONNECTION["database"],
            username=_CONNECTION["username"],
            password=_CONNECTION["password"],
        )
        DuckgresServerTeam.objects.create(server=server, team=team, table_suffix="prod")

        source = _ensure(team)

        assert source.source_type == "Postgres"
        assert source.access_method == ExternalDataSource.AccessMethod.WAREHOUSE
        assert source.direct_query_enabled is True
        assert isinstance(source.connection_metadata, dict)
        assert source.connection_metadata["engine"] == "duckdb"
        assert source.prefix == MANAGED_WAREHOUSE_SOURCE_PREFIX
        # job_inputs carry the warehouse connection so live queries reach it.
        assert source.job_inputs["host"] == _CONNECTION["host"]
        assert source.job_inputs["user"] == _CONNECTION["username"]
        assert source.job_inputs["password"] == _CONNECTION["password"]

    def test_is_idempotent(self) -> None:
        # Without dedup, every status poll / re-enable would spawn a duplicate connection.
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        server = DuckgresServer.objects.create(
            organization=org,
            host=_CONNECTION["host"],
            port=_CONNECTION["port"],
            database=_CONNECTION["database"],
            username=_CONNECTION["username"],
            password=_CONNECTION["password"],
        )
        DuckgresServerTeam.objects.create(server=server, team=team, table_suffix="prod")

        first = _ensure(team)
        second = _ensure(team)

        assert first.pk == second.pk
        assert ExternalDataSource.objects.filter(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX).count() == 1

    def test_does_not_expose_legacy_shared_tables(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        server = DuckgresServer.objects.create(
            organization=org,
            host=_CONNECTION["host"],
            port=_CONNECTION["port"],
            database=_CONNECTION["database"],
            username=_CONNECTION["username"],
            password=_CONNECTION["password"],
        )
        DuckgresServerTeam.objects.create(server=server, team=team, table_suffix=None)

        with pytest.raises(ValueError, match="shared managed warehouse tables"):
            _ensure(team)

        assert not ExternalDataSource.objects.filter(team_id=team.id).exists()

    def test_does_not_promote_a_user_source_with_the_reserved_prefix(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        server = DuckgresServer.objects.create(
            organization=org,
            host=_CONNECTION["host"],
            port=_CONNECTION["port"],
            database=_CONNECTION["database"],
            username=_CONNECTION["username"],
            password=_CONNECTION["password"],
        )
        DuckgresServerTeam.objects.create(server=server, team=team, table_suffix="prod")
        user_source = ExternalDataSource.objects.create(
            team=team,
            source_id="user-source",
            connection_id="user-connection",
            destination_id="user-destination",
            status=ExternalDataSource.Status.RUNNING,
            source_type="Postgres",
            prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"password": "user-password"},
            connection_metadata={"engine": "duckdb"},
        )
        user_schema = ExternalDataSchema.objects.create(
            team=team,
            source=user_source,
            name="events_other_team",
            should_sync=True,
        )

        managed_source = _ensure(team)

        user_source.refresh_from_db()
        user_schema.refresh_from_db()
        assert managed_source.id != user_source.id
        assert managed_source.is_system_managed is True
        assert user_source.is_system_managed is False
        assert user_source.job_inputs == {"password": "user-password"}
        assert user_schema.source_id == user_source.id

    def test_removes_existing_schemas_when_upgrading_a_trusted_managed_source(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        server = DuckgresServer.objects.create(
            organization=org,
            host=_CONNECTION["host"],
            port=_CONNECTION["port"],
            database=_CONNECTION["database"],
            username=_CONNECTION["username"],
            password=_CONNECTION["password"],
        )
        DuckgresServerTeam.objects.create(server=server, team=team, table_suffix="prod")
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
        assert managed_source.access_method == ExternalDataSource.AccessMethod.WAREHOUSE
        assert not ExternalDataSchema.objects.filter(id=schema.id).exists()


def _source_schema(table_name: str) -> SourceSchema:
    return SourceSchema(
        name=table_name,
        supports_incremental=False,
        supports_append=False,
        columns=[("uuid", "uuid", False), ("timestamp", "timestamp", True)],
        source_schema="main",
        source_table_name=table_name,
    )


@pytest.mark.django_db
class TestReconcileManagedWarehouseTables:
    def _setup(self) -> tuple[Organization, Team]:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        server = DuckgresServer.objects.create(
            organization=org,
            host=_CONNECTION["host"],
            port=_CONNECTION["port"],
            database=_CONNECTION["database"],
            username=_CONNECTION["username"],
            password=_CONNECTION["password"],
        )
        DuckgresServerTeam.objects.create(server=server, team=team, backfill_enabled=True, table_suffix="prod")
        return org, team

    def test_discovers_only_the_teams_tables_and_makes_them_queryable(self) -> None:
        org, team = self._setup()
        # The endpoint would also list other environments' tables; only this team's two are exposed.
        discovered = [_source_schema("events_prod"), _source_schema("persons_prod"), _source_schema("events_other")]

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            return_value=discovered,
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        source = ExternalDataSource.objects.get(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX)
        assert source.access_method == ExternalDataSource.AccessMethod.WAREHOUSE
        assert not DataWarehouseTable.raw_objects.filter(external_data_source_id=source.id).exists()
        assert set(
            ExternalDataSchema.objects.filter(source_id=source.id, should_sync=True).values_list("name", flat=True)
        ) == {"events_prod", "persons_prod"}

        allowed_query = HogQLQueryExecutor(
            query="SELECT uuid FROM events_prod",
            team=team,
            connection_id=str(source.id),
        )
        sql, _context = allowed_query.generate_clickhouse_sql()
        assert "events_prod" in sql

        forbidden_query = HogQLQueryExecutor(
            query="SELECT uuid FROM events_other",
            team=team,
            connection_id=str(source.id),
        )
        with pytest.raises(QueryError):
            forbidden_query.generate_clickhouse_sql()

        with patch("posthog.hogql.direct_sql.postgres_adapter.psycopg.connect") as connect:
            raw_query = HogQLQueryExecutor(
                query="SELECT uuid FROM events_other",
                team=team,
                connection_id=str(source.id),
                send_raw_query=True,
            )
            with pytest.raises(ExposedHogQLError):
                raw_query.execute()
            connect.assert_not_called()

    def test_skips_live_introspection_once_tables_exist(self) -> None:
        # The warehouse-status poll drives this; re-introspecting on every tick would hammer the DB.
        org, team = self._setup()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            return_value=[_source_schema("events_prod"), _source_schema("persons_prod")],
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
        ) as get_schemas:
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)
            get_schemas.assert_not_called()

    def test_does_nothing_for_a_team_that_has_not_joined_the_warehouse(self) -> None:
        # A non-member team polling status while the warehouse is ready must not get a connection.
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        DuckgresServer.objects.create(
            organization=org, host=_CONNECTION["host"], port=5432, database="ducklake", username="root", password="pw"
        )

        reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        assert not ExternalDataSource.objects.filter(team_id=team.id).exists()

    def test_does_not_reconcile_legacy_shared_tables(self) -> None:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        server = DuckgresServer.objects.create(
            organization=org,
            host=_CONNECTION["host"],
            port=_CONNECTION["port"],
            database=_CONNECTION["database"],
            username=_CONNECTION["username"],
            password=_CONNECTION["password"],
        )
        DuckgresServerTeam.objects.create(server=server, team=team, table_suffix=None)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas"
        ) as get_schemas:
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        assert not ExternalDataSource.objects.filter(team_id=team.id).exists()
        get_schemas.assert_not_called()

    def test_rejects_a_team_membership_from_another_organization(self) -> None:
        org_a = Organization.objects.create(name="Org A")
        org_b = Organization.objects.create(name="Org B")
        team_b = Team.objects.create(organization=org_b)
        server_a = DuckgresServer.objects.create(
            organization=org_a,
            host="a.example.com",
            port=5432,
            database="ducklake",
            username="root",
            password="org-a-password",
        )
        server_b = DuckgresServer.objects.create(
            organization=org_b,
            host="b.example.com",
            port=5432,
            database="ducklake",
            username="root",
            password="org-b-password",
        )
        DuckgresServerTeam.objects.create(server=server_b, team=team_b, table_suffix="b")

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas"
        ) as get_schemas:
            reconcile_managed_warehouse_tables(team_id=team_b.id, organization_id=org_a.id)

        assert server_a.organization_id == org_a.id
        assert not ExternalDataSource.objects.filter(team_id=team_b.id).exists()
        get_schemas.assert_not_called()


@pytest.mark.django_db
class TestManagedWarehouseLifecycle:
    def _org_team_source(self) -> tuple[Organization, Team, ExternalDataSource, DuckgresServer]:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        server = DuckgresServer.objects.create(
            organization=org,
            host=_CONNECTION["host"],
            port=_CONNECTION["port"],
            database=_CONNECTION["database"],
            username=_CONNECTION["username"],
            password=_CONNECTION["password"],
        )
        DuckgresServerTeam.objects.create(server=server, team=team, table_suffix="prod")
        source = ensure_managed_warehouse_direct_source(team_id=team.id, organization_id=org.id)
        return org, team, source, server

    def test_update_password_rewrites_authoritative_and_query_connection_credentials(self) -> None:
        org, _team, source, server = self._org_team_source()

        update_managed_warehouse_password(organization_id=org.id, password="rotated")

        source.refresh_from_db()
        server.refresh_from_db()
        assert source.job_inputs["password"] == "rotated"
        assert server.password == "rotated"

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
        assert DuckgresServerTeam.objects.get(team=team).backfill_enabled is False

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
        server = DuckgresServer.objects.create(
            organization=org,
            host=_CONNECTION["host"],
            port=_CONNECTION["port"],
            database=_CONNECTION["database"],
            username=_CONNECTION["username"],
            password=_CONNECTION["password"],
        )
        team_a = Team.objects.create(organization=org)
        team_b = Team.objects.create(organization=org)
        DuckgresServerTeam.objects.create(server=server, team=team_a, table_suffix="a")
        DuckgresServerTeam.objects.create(server=server, team=team_b, table_suffix="b")
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


@patch("products.data_warehouse.backend.facade.api.schedule_managed_warehouse_tables_reconcile")
def test_ready_status_queues_table_discovery(mock_schedule: MagicMock) -> None:
    organization_id = "a8fd15f0-1ed3-480b-a859-b10bba374acf"

    managed_warehouse.ensure_direct_connection_tables(team_id=42, organization_id=organization_id)

    mock_schedule.assert_called_once_with(team_id=42, organization_id=organization_id)
