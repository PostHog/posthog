from typing import cast

from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.query import HogQLQueryExecutor

from posthog.models.organization import OrganizationMembership

from products.data_warehouse.backend.direct_postgres import postgres_schema_metadata
from products.data_warehouse.backend.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource
from products.data_warehouse.backend.models.tenant_query_config import DataWarehouseTenantQueryConfig
from products.data_warehouse.backend.models.util import postgres_columns_to_dwh_columns
from products.data_warehouse.backend.tenant_query import (
    apply_tenant_query_config,
    configure_tenant_query,
    execute_tenant_query,
    get_tenant_query_config,
    infer_tenant_column_type,
)
from products.data_warehouse.backend.types import ExternalDataSourceType

POSTGRES_TRIPS_COLUMNS = [
    ("id", "bigint", False),
    ("customer_id", "bigint", False),
    ("name", "text", True),
]


class TestTenantQuery(APIBaseTest):
    def _create_direct_source(self) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            source_id="source",
            connection_id="connection",
            destination_id="destination",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={},
        )

    def _create_table(
        self,
        source: ExternalDataSource,
        name: str = "trips",
        postgres_columns: list[tuple[str, str, bool]] | None = None,
        should_sync: bool = True,
    ) -> DataWarehouseTable:
        columns = postgres_columns or POSTGRES_TRIPS_COLUMNS
        table = DataWarehouseTable.objects.create(
            name=name,
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            url_pattern="direct://postgres",
            external_data_source=source,
            columns=postgres_columns_to_dwh_columns(columns),
        )
        ExternalDataSchema.objects.create(
            name=name,
            team=self.team,
            source=source,
            table=table,
            should_sync=should_sync,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
            sync_type_config={
                "schema_metadata": postgres_schema_metadata(
                    columns,
                    source_schema="public",
                    source_table_name=name,
                )
            },
        )
        return table

    def _create_config(self, source: ExternalDataSource) -> DataWarehouseTenantQueryConfig:
        return DataWarehouseTenantQueryConfig.objects.create(
            team=self.team,
            external_data_source=source,
            enabled=True,
            tenant_column_name="customer_id",
            tenant_column_type=DataWarehouseTenantQueryConfig.TenantColumnType.INTEGER,
            max_result_limit=100_000,
        )

    def _prepare_sql(
        self,
        source: ExternalDataSource,
        config: DataWarehouseTenantQueryConfig,
        query: str,
        tenant_value: object = 42,
    ) -> str:
        database = Database.create_for(team=self.team, connection_id=str(source.id))
        apply_tenant_query_config(database, config, tenant_value)
        context = HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            database=database,
            max_limit_override=config.max_result_limit,
        )
        executor = HogQLQueryExecutor(
            query=query,
            team=self.team,
            settings=HogQLGlobalSettings(max_execution_time=30),
            limit_context=LimitContext.TENANT_QUERY,
            context=context,
            connection_id=str(source.id),
        )
        return executor._prepare_execution().sql

    def test_infers_tenant_column_type_from_enabled_direct_tables(self):
        source = self._create_direct_source()
        self._create_table(source)

        assert (
            infer_tenant_column_type(source, "customer_id") == DataWarehouseTenantQueryConfig.TenantColumnType.INTEGER
        )

    def test_rejects_enabled_tables_without_tenant_column(self):
        source = self._create_direct_source()
        self._create_table(source)
        self._create_table(source, name="payments", postgres_columns=[("id", "bigint", False)])

        with self.assertRaisesRegex(Exception, "missing from enabled tables: payments"):
            infer_tenant_column_type(source, "customer_id")

    def test_ignores_disabled_tables_when_inferring_tenant_column_type(self):
        source = self._create_direct_source()
        self._create_table(source)
        self._create_table(
            source,
            name="payments",
            postgres_columns=[("id", "bigint", False)],
            should_sync=False,
        )

        assert (
            infer_tenant_column_type(source, "customer_id") == DataWarehouseTenantQueryConfig.TenantColumnType.INTEGER
        )

    def test_configure_tenant_query_infers_type_and_stores_config(self):
        source = self._create_direct_source()
        self._create_table(source)

        response = configure_tenant_query(
            team=self.team,
            connection_id=str(source.id),
            enabled=True,
            tenant_column_name="customer_id",
            default_timeout_ms=5_000,
            max_timeout_ms=30_000,
            max_result_limit=10_000,
        )

        config = DataWarehouseTenantQueryConfig.objects.get(team=self.team, external_data_source=source)
        assert config.enabled is True
        assert config.tenant_column_name == "customer_id"
        assert config.tenant_column_type == DataWarehouseTenantQueryConfig.TenantColumnType.INTEGER
        assert config.default_timeout_ms == 5_000
        assert config.max_timeout_ms == 30_000
        assert config.max_result_limit == 10_000
        assert response["enabled_tables"] == ["trips"]

    def test_configure_tenant_query_rejects_missing_tenant_column(self):
        source = self._create_direct_source()
        self._create_table(source, name="payments", postgres_columns=[("id", "bigint", False)])

        with self.assertRaisesRegex(Exception, "missing from enabled tables: payments"):
            configure_tenant_query(
                team=self.team,
                connection_id=str(source.id),
                enabled=True,
                tenant_column_name="customer_id",
            )

    def test_get_tenant_query_config_returns_disabled_defaults_without_creating_config(self):
        source = self._create_direct_source()
        self._create_table(source)

        response = get_tenant_query_config(team=self.team, connection_id=str(source.id))

        assert response["enabled"] is False
        assert response["tenant_column_name"] is None
        assert response["max_result_limit"] == 100_000
        assert DataWarehouseTenantQueryConfig.objects.count() == 0

    def test_injects_tenant_predicate_and_hides_tenant_column_from_asterisk(self):
        source = self._create_direct_source()
        self._create_table(source)
        config = self._create_config(source)

        sql = self._prepare_sql(source, config, "select * from trips")

        assert " as customer_id" not in sql.lower()
        assert "customer_id = 42" in sql
        assert "LIMIT 100" in sql

    def test_rejects_explicit_tenant_column_output(self):
        source = self._create_direct_source()
        self._create_table(source)
        self._create_config(source)

        with self.assertRaisesRegex(Exception, "Tenant column `customer_id` cannot be selected"):
            execute_tenant_query(
                team=self.team,
                user=self.user,
                connection_id=str(source.id),
                tenant_value=42,
                query="select customer_id from trips",
            )

    def test_rejects_derived_tenant_column_output(self):
        source = self._create_direct_source()
        self._create_table(source)
        self._create_config(source)

        with self.assertRaisesRegex(Exception, "Tenant column `customer_id` cannot be selected"):
            execute_tenant_query(
                team=self.team,
                user=self.user,
                connection_id=str(source.id),
                tenant_value=42,
                query="select count(customer_id) from trips",
            )

    def test_rejects_tenant_column_output_inside_ctes(self):
        source = self._create_direct_source()
        self._create_table(source)
        self._create_config(source)

        with self.assertRaisesRegex(Exception, "Tenant column `customer_id` cannot be selected"):
            execute_tenant_query(
                team=self.team,
                user=self.user,
                connection_id=str(source.id),
                tenant_value=42,
                query="with leaked as (select customer_id from trips) select 1 from leaked",
            )

    def test_injects_tenant_predicate_inside_ctes(self):
        source = self._create_direct_source()
        self._create_table(source)
        config = self._create_config(source)

        sql = self._prepare_sql(source, config, "with scoped as (select id from trips) select id from scoped")

        assert "customer_id" in sql
        assert "LIMIT 100" in sql

    def test_injects_tenant_predicate_inside_subqueries(self):
        source = self._create_direct_source()
        self._create_table(source)
        config = self._create_config(source)

        sql = self._prepare_sql(source, config, "select id from (select id from trips) as scoped")

        assert "customer_id" in sql
        assert "LIMIT 100" in sql

    def test_injects_tenant_predicate_for_aliases_and_existing_tenant_filters(self):
        source = self._create_direct_source()
        self._create_table(source)
        config = self._create_config(source)

        sql = self._prepare_sql(source, config, "select t.id from trips as t where t.customer_id = 7")

        assert sql.count("customer_id") >= 2
        assert "LIMIT 100" in sql

    def test_injects_tenant_predicate_for_every_joined_table(self):
        source = self._create_direct_source()
        self._create_table(source)
        config = self._create_config(source)

        sql = self._prepare_sql(
            source,
            config,
            "select t.id from trips as t join trips as t2 on t.id = t2.id",
        )

        assert sql.count("customer_id") >= 2
        assert "LIMIT 100" in sql

    def test_rejects_disabled_tables(self):
        source = self._create_direct_source()
        self._create_table(source)
        self._create_table(source, name="payments", should_sync=False)
        config = self._create_config(source)

        with self.assertRaisesRegex(Exception, "Unknown table `payments`"):
            self._prepare_sql(source, config, "select id from payments")

    def test_clamps_explicit_limit_to_configured_maximum(self):
        source = self._create_direct_source()
        self._create_table(source)
        config = self._create_config(source)
        config.max_result_limit = 500
        config.save()

        sql = self._prepare_sql(source, config, "select id from trips limit 1000")

        assert "LIMIT 500" in sql

    def test_requested_timeout_is_capped_by_configured_maximum(self):
        source = self._create_direct_source()
        self._create_table(source)
        config = self._create_config(source)
        config.default_timeout_ms = 5_000
        config.max_timeout_ms = 12_000
        config.save()

        response = Mock()
        response.results = []
        response.model_dump.return_value = {"columns": [], "results": [], "types": []}

        with patch("products.data_warehouse.backend.tenant_query.HogQLQueryExecutor") as executor_class:
            executor = executor_class.return_value
            executor.execute.return_value = response
            executor.direct_postgres_sql = "SELECT 1"
            executor._get_select_query_type.return_value = None

            execute_tenant_query(
                team=self.team,
                user=self.user,
                connection_id=str(source.id),
                tenant_value=42,
                query="select id from trips",
                timeout_ms=20_000,
            )

        assert executor_class.call_args.kwargs["settings"].max_execution_time == 12

    def test_metadata_tables_query_does_not_require_tenant_value(self):
        source = self._create_direct_source()
        self._create_table(source)
        self._create_config(source)

        result, row_count = execute_tenant_query(
            team=self.team,
            user=self.user,
            connection_id=str(source.id),
            tenant_value=None,
            query="select * from system.tables",
        )

        assert row_count == 1
        assert result["columns"] == ["name", "source_schema", "source_table_name"]
        assert result["results"] == [["trips", "public", "trips"]]

    def test_metadata_query_logs_success(self):
        source = self._create_direct_source()
        self._create_table(source)
        self._create_config(source)

        with patch("products.data_warehouse.backend.tenant_query.logger.info") as log_info:
            execute_tenant_query(
                team=self.team,
                user=self.user,
                connection_id=str(source.id),
                tenant_value=None,
                query="select * from system.tables",
            )

        log_info.assert_called_once()
        assert log_info.call_args.args == ("tenant_query_execution",)
        assert log_info.call_args.kwargs["success"] is True
        assert log_info.call_args.kwargs["metadata_only"] is True
        assert log_info.call_args.kwargs["row_count"] == 1

    def test_metadata_fields_query_hides_tenant_column(self):
        source = self._create_direct_source()
        self._create_table(source)
        self._create_config(source)

        result, _row_count = execute_tenant_query(
            team=self.team,
            user=self.user,
            connection_id=str(source.id),
            tenant_value=None,
            query="select table, name, postgres_type from system.fields where table = 'trips'",
        )

        assert result["columns"] == ["table", "name", "postgres_type"]
        assert ["trips", "id", "bigint"] in result["results"]
        assert ["trips", "name", "text"] in result["results"]
        assert all(row[1] != "customer_id" for row in result["results"])

    def test_query_errors_are_logged(self):
        source = self._create_direct_source()
        self._create_table(source)
        self._create_config(source)

        with patch("products.data_warehouse.backend.tenant_query.logger.info") as log_info:
            with self.assertRaisesRegex(Exception, "Tenant column `customer_id` cannot be selected"):
                execute_tenant_query(
                    team=self.team,
                    user=self.user,
                    connection_id=str(source.id),
                    tenant_value=42,
                    query="select customer_id from trips",
                )

        log_info.assert_called_once()
        assert log_info.call_args.args == ("tenant_query_execution",)
        assert log_info.call_args.kwargs["success"] is False
        assert log_info.call_args.kwargs["metadata_only"] is False
        assert "cannot be selected" in log_info.call_args.kwargs["error"]

    def test_endpoint_uses_tenant_query_service(self):
        with patch("products.data_warehouse.backend.api.tenant_query.execute_tenant_query") as execute_tenant_query:
            execute_tenant_query.return_value = ({"columns": ["id"], "results": [[1]], "types": []}, 1)
            response = self.client.post(
                f"/api/environments/{self.team.id}/tenant_query/",
                {
                    "connection_id": "00000000-0000-0000-0000-000000000001",
                    "tenant_value": "42",
                    "query": "select id from trips",
                },
                format="json",
            )

        assert response.status_code == 200
        assert response.json()["results"] == [[1]]
        execute_tenant_query.assert_called_once()
        call_kwargs = cast(dict, execute_tenant_query.call_args.kwargs)
        assert call_kwargs["connection_id"] == "00000000-0000-0000-0000-000000000001"
        assert call_kwargs["tenant_value"] == "42"

    def test_configure_endpoint_uses_tenant_query_config_service(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        with patch("products.data_warehouse.backend.api.tenant_query.configure_tenant_query") as configure_query:
            configure_query.return_value = {
                "connection_id": "00000000-0000-0000-0000-000000000001",
                "enabled": True,
                "tenant_column_name": "customer_id",
                "tenant_column_type": "integer",
                "default_timeout_ms": 30_000,
                "max_timeout_ms": 120_000,
                "max_result_limit": 100_000,
                "enabled_tables": ["trips"],
            }
            response = self.client.post(
                f"/api/environments/{self.team.id}/tenant_query/config/",
                {
                    "connection_id": "00000000-0000-0000-0000-000000000001",
                    "enabled": True,
                    "tenant_column_name": "customer_id",
                },
                format="json",
            )

        assert response.status_code == 200
        assert response.json()["tenant_column_type"] == "integer"
        configure_query.assert_called_once()
