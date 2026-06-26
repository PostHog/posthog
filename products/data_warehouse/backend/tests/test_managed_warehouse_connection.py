import pytest
from unittest.mock import patch

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
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema

_CONNECTION = {
    "host": "wh.dw.us.postwh.com",
    "port": 5432,
    "database": "ducklake",
    "username": "root",
    "password": "pw",
}


def _ensure(team: Team) -> ExternalDataSource | None:
    return ensure_managed_warehouse_direct_source(team_id=team.id, **_CONNECTION)


@pytest.mark.django_db
class TestEnsureManagedWarehouseDirectSource:
    def test_creates_a_postgres_direct_source_from_the_connection(self):
        team = Team.objects.create(organization=Organization.objects.create(name="Org"))

        source = _ensure(team)

        assert source is not None
        assert source.source_type == "Postgres"
        assert source.access_method == ExternalDataSource.AccessMethod.DIRECT
        assert source.direct_query_enabled is True
        assert source.prefix == MANAGED_WAREHOUSE_SOURCE_PREFIX
        # job_inputs carry the warehouse connection so live queries reach it.
        assert source.job_inputs["host"] == _CONNECTION["host"]
        assert source.job_inputs["user"] == _CONNECTION["username"]
        assert source.job_inputs["password"] == _CONNECTION["password"]

    def test_is_idempotent(self):
        # Without dedup, every status poll / re-enable would spawn a duplicate connection.
        team = Team.objects.create(organization=Organization.objects.create(name="Org"))

        first = _ensure(team)
        second = _ensure(team)

        assert first is not None and second is not None
        assert first.pk == second.pk
        assert ExternalDataSource.objects.filter(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX).count() == 1


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

    def test_discovers_only_the_teams_tables_and_makes_them_queryable(self):
        org, team = self._setup()
        # The endpoint would also list other environments' tables; only this team's two are exposed.
        discovered = [_source_schema("events_prod"), _source_schema("persons_prod"), _source_schema("events_other")]

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.get_schemas",
            return_value=discovered,
        ):
            reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        source = ExternalDataSource.objects.get(team_id=team.id, prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX)
        tables = set(
            DataWarehouseTable.raw_objects.queryable()
            .filter(team_id=team.id, external_data_source_id=source.id)
            .values_list("name", flat=True)
        )
        assert tables == {"events_prod", "persons_prod"}
        for table in DataWarehouseTable.objects.filter(external_data_source_id=source.id):
            assert table.url_pattern == DIRECT_POSTGRES_URL_PATTERN
        assert ExternalDataSchema.objects.filter(source_id=source.id, should_sync=True).count() == 2

    def test_skips_live_introspection_once_tables_exist(self):
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

    def test_does_nothing_for_a_team_that_has_not_joined_the_warehouse(self):
        # A non-member team polling status while the warehouse is ready must not get a connection.
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        DuckgresServer.objects.create(
            organization=org, host=_CONNECTION["host"], port=5432, database="ducklake", username="root", password="pw"
        )

        reconcile_managed_warehouse_tables(team_id=team.id, organization_id=org.id)

        assert not ExternalDataSource.objects.filter(team_id=team.id).exists()


@pytest.mark.django_db
class TestManagedWarehouseLifecycle:
    def _org_team_source(self) -> tuple[Organization, Team, ExternalDataSource]:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        source = ensure_managed_warehouse_direct_source(team_id=team.id, **_CONNECTION)
        assert source is not None
        return org, team, source

    def test_update_password_rewrites_stored_job_inputs(self):
        org, _team, source = self._org_team_source()

        update_managed_warehouse_password(organization_id=org.id, password="rotated")

        source.refresh_from_db()
        assert source.job_inputs["password"] == "rotated"

    def test_soft_delete_removes_sources_and_their_tables(self):
        org, team, source = self._org_team_source()
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
