from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import cast

from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.query import HogQLQueryExecutor

from posthog.models.organization import OrganizationMembership

from products.data_warehouse.backend.direct_postgres import get_direct_postgres_table_options, postgres_schema_metadata
from products.data_warehouse.backend.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource
from products.data_warehouse.backend.models.tenant_query_config import DataWarehouseTenantQueryConfig
from products.data_warehouse.backend.models.util import postgres_columns_to_dwh_columns
from products.data_warehouse.backend.tenant_query import (
    TENANT_QUERY_NO_TENANT_FIELD,
    TENANT_QUERY_TABLE_DISABLED,
    _apply_top_level_tenant_query_limit,
    apply_tenant_query_config,
    configure_tenant_query,
    execute_tenant_query,
    get_tenant_query_config,
    get_tenant_query_execution,
    infer_tenant_column_type,
    list_tenant_query_executions,
    summarize_tenant_query_errors,
    summarize_tenant_query_usage,
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
        postgres_foreign_keys: list[tuple[str, str, str]] | None = None,
        should_sync: bool = True,
        source_schema: str = "public",
        source_table_name: str | None = None,
    ) -> DataWarehouseTable:
        columns = postgres_columns or POSTGRES_TRIPS_COLUMNS
        resolved_source_table_name = source_table_name or name
        table = DataWarehouseTable.objects.create(
            name=name,
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            url_pattern="direct://postgres",
            external_data_source=source,
            options=get_direct_postgres_table_options(
                source_schema=source_schema,
                source_table_name=resolved_source_table_name,
            ),
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
                    postgres_foreign_keys,
                    source_schema=source_schema,
                    source_table_name=resolved_source_table_name,
                )
            },
        )
        return table

    def _create_config(
        self,
        source: ExternalDataSource,
        tenant_column_name: str = "customer_id",
        tenant_column_names_by_table: dict[str, str] | None = None,
    ) -> DataWarehouseTenantQueryConfig:
        return DataWarehouseTenantQueryConfig.objects.create(
            team=self.team,
            external_data_source=source,
            enabled=True,
            tenant_column_name=tenant_column_name,
            tenant_column_type=DataWarehouseTenantQueryConfig.TenantColumnType.INTEGER,
            tenant_column_names_by_table=tenant_column_names_by_table or {},
            max_result_limit=100_000,
        )

    def _prepare_sql(
        self,
        source: ExternalDataSource,
        config: DataWarehouseTenantQueryConfig,
        query: str,
        tenant_value: object = 42,
        database_callback: Callable[[Database], None] | None = None,
    ) -> str:
        parsed_query = parse_select(query)
        _apply_top_level_tenant_query_limit(parsed_query, config.max_result_limit)
        database = Database.create_for(team=self.team, connection_id=str(source.id))
        if database_callback is not None:
            database_callback(database)
        apply_tenant_query_config(database, config, tenant_value)
        context = HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            database=database,
            limit_top_select=False,
        )
        executor = HogQLQueryExecutor(
            query=parsed_query,
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
        assert config.tenant_column_names_by_table == {}
        assert response["enabled_tables"] == ["trips"]
        assert response["disabled_tables"] == []

    def test_configure_tenant_query_stores_per_table_tenant_column_overrides(self):
        source = self._create_direct_source()
        self._create_table(source)
        self._create_table(
            source,
            name="bookings",
            postgres_columns=[("id", "bigint", False), ("account_id", "bigint", False), ("name", "text", True)],
            should_sync=False,
        )

        response = configure_tenant_query(
            team=self.team,
            connection_id=str(source.id),
            enabled=True,
            tenant_column_name="customer_id",
            tenant_column_names_by_table={"bookings": "account_id"},
        )

        config = DataWarehouseTenantQueryConfig.objects.get(team=self.team, external_data_source=source)
        assert config.tenant_column_type == DataWarehouseTenantQueryConfig.TenantColumnType.INTEGER
        assert config.tenant_column_names_by_table == {"bookings": "account_id"}
        assert response["tenant_column_names_by_table"] == {"bookings": "account_id"}
        assert response["enabled_tables"] == ["bookings", "trips"]
        assert response["disabled_tables"] == []
        assert ExternalDataSchema.objects.get(source=source, name="bookings").should_sync is True

    def test_configure_tenant_query_stores_foreign_key_tenant_column_override(self):
        source = self._create_direct_source()
        self._create_table(
            source,
            name="posthog_dashboards",
            postgres_columns=[("id", "bigint", False), ("team_id", "bigint", False), ("name", "text", True)],
        )
        self._create_table(
            source,
            name="posthog_dashboard_tiles",
            postgres_columns=[("id", "bigint", False), ("dashboard_id", "bigint", False), ("name", "text", True)],
            postgres_foreign_keys=[("dashboard_id", "posthog_dashboards", "id")],
            should_sync=False,
        )

        response = configure_tenant_query(
            team=self.team,
            connection_id=str(source.id),
            enabled=True,
            tenant_column_name="team_id",
            tenant_column_names_by_table={"posthog_dashboard_tiles": "dashboard.team_id"},
        )

        config = DataWarehouseTenantQueryConfig.objects.get(team=self.team, external_data_source=source)
        assert config.tenant_column_type == DataWarehouseTenantQueryConfig.TenantColumnType.INTEGER
        assert config.tenant_column_names_by_table == {"posthog_dashboard_tiles": "dashboard.team_id"}
        assert response["tenant_column_names_by_table"] == {"posthog_dashboard_tiles": "dashboard.team_id"}
        assert response["foreign_key_tenant_paths_by_table"] == {"posthog_dashboard_tiles": ["dashboard.team_id"]}
        assert response["enabled_tables"] == ["posthog_dashboard_tiles", "posthog_dashboards"]
        assert response["disabled_tables"] == []
        assert ExternalDataSchema.objects.get(source=source, name="posthog_dashboard_tiles").should_sync is True

    def test_configure_tenant_query_rejects_nullable_foreign_key_tenant_column_override(self):
        source = self._create_direct_source()
        self._create_table(
            source,
            name="posthog_dashboard",
            postgres_columns=[("id", "bigint", False), ("team_id", "bigint", False), ("name", "text", True)],
        )
        self._create_table(
            source,
            name="posthog_dashboarditem",
            postgres_columns=[
                ("id", "bigint", False),
                ("team_id", "bigint", False),
                ("dashboard_id", "bigint", True),
                ("name", "text", True),
            ],
            postgres_foreign_keys=[("dashboard_id", "posthog_dashboard", "id")],
        )

        response = configure_tenant_query(
            team=self.team,
            connection_id=str(source.id),
            enabled=True,
            tenant_column_name="team_id",
        )

        assert response["foreign_key_tenant_paths_by_table"] == {}
        with self.assertRaisesRegex(Exception, "not a valid foreign key tenancy path"):
            configure_tenant_query(
                team=self.team,
                connection_id=str(source.id),
                enabled=True,
                tenant_column_name="team_id",
                tenant_column_names_by_table={"posthog_dashboarditem": "dashboard.team_id"},
            )

    def test_configure_tenant_query_allows_table_without_tenant_column_as_dimension(self):
        source = self._create_direct_source()
        self._create_table(source)
        self._create_table(
            source,
            name="countries",
            postgres_columns=[("id", "bigint", False), ("name", "text", True)],
            should_sync=False,
        )

        response = configure_tenant_query(
            team=self.team,
            connection_id=str(source.id),
            enabled=True,
            tenant_column_name="customer_id",
            tenant_column_names_by_table={"countries": TENANT_QUERY_NO_TENANT_FIELD},
        )

        config = DataWarehouseTenantQueryConfig.objects.get(team=self.team, external_data_source=source)
        assert config.tenant_column_type == DataWarehouseTenantQueryConfig.TenantColumnType.INTEGER
        assert config.tenant_column_names_by_table == {"countries": TENANT_QUERY_NO_TENANT_FIELD}
        assert response["tenant_column_names_by_table"] == {"countries": TENANT_QUERY_NO_TENANT_FIELD}
        assert response["enabled_tables"] == ["countries", "trips"]
        assert response["disabled_tables"] == []
        assert ExternalDataSchema.objects.get(source=source, name="countries").should_sync is True

    def test_configure_tenant_query_disables_table_from_per_table_setting(self):
        source = self._create_direct_source()
        self._create_table(source)
        self._create_table(source, name="payments")

        response = configure_tenant_query(
            team=self.team,
            connection_id=str(source.id),
            enabled=True,
            tenant_column_name="customer_id",
            tenant_column_names_by_table={"payments": TENANT_QUERY_TABLE_DISABLED},
        )

        config = DataWarehouseTenantQueryConfig.objects.get(team=self.team, external_data_source=source)
        assert config.tenant_column_names_by_table == {"payments": TENANT_QUERY_TABLE_DISABLED}
        assert response["tenant_column_names_by_table"] == {"payments": TENANT_QUERY_TABLE_DISABLED}
        assert response["enabled_tables"] == ["trips"]
        assert response["disabled_tables"] == []
        assert ExternalDataSchema.objects.get(source=source, name="payments").should_sync is False

    def test_configure_tenant_query_rejects_per_table_tenant_column_with_different_type(self):
        source = self._create_direct_source()
        self._create_table(source)
        self._create_table(
            source,
            name="bookings",
            postgres_columns=[("id", "bigint", False), ("account_id", "text", False)],
        )

        with self.assertRaisesRegex(Exception, "global tenant column type is `integer`"):
            configure_tenant_query(
                team=self.team,
                connection_id=str(source.id),
                enabled=True,
                tenant_column_name="customer_id",
                tenant_column_names_by_table={"bookings": "account_id"},
            )

    def test_configure_tenant_query_disables_tables_without_tenant_column(self):
        source = self._create_direct_source()
        self._create_table(source)
        self._create_table(source, name="payments", postgres_columns=[("id", "bigint", False)])

        response = configure_tenant_query(
            team=self.team,
            connection_id=str(source.id),
            enabled=True,
            tenant_column_name="customer_id",
        )

        assert response["enabled"] is True
        assert response["enabled_tables"] == ["trips"]
        assert response["disabled_tables"] == ["payments"]
        assert ExternalDataSchema.objects.get(source=source, name="trips").should_sync is True
        assert ExternalDataSchema.objects.get(source=source, name="payments").should_sync is False

    def test_configure_tenant_query_saves_when_all_tables_are_missing_tenant_column(self):
        source = self._create_direct_source()
        self._create_table(source, name="payments", postgres_columns=[("id", "bigint", False)])

        response = configure_tenant_query(
            team=self.team,
            connection_id=str(source.id),
            enabled=True,
            tenant_column_name="customer_id",
        )

        config = DataWarehouseTenantQueryConfig.objects.get(team=self.team, external_data_source=source)
        assert config.enabled is True
        assert config.tenant_column_name == "customer_id"
        assert config.tenant_column_type == DataWarehouseTenantQueryConfig.TenantColumnType.STRING
        assert response["enabled_tables"] == []
        assert response["disabled_tables"] == ["payments"]
        assert ExternalDataSchema.objects.get(source=source, name="payments").should_sync is False

    def test_configure_tenant_query_keeps_tables_enabled_when_type_validation_fails(self):
        source = self._create_direct_source()
        self._create_table(source)
        self._create_table(
            source,
            name="bookings",
            postgres_columns=[("id", "bigint", False), ("customer_id", "text", False)],
        )
        self._create_table(source, name="payments", postgres_columns=[("id", "bigint", False)])

        with self.assertRaisesRegex(Exception, "inconsistent types"):
            configure_tenant_query(
                team=self.team,
                connection_id=str(source.id),
                enabled=True,
                tenant_column_name="customer_id",
            )

        assert ExternalDataSchema.objects.get(source=source, name="payments").should_sync is True

    def test_get_tenant_query_config_returns_disabled_defaults_without_creating_config(self):
        source = self._create_direct_source()
        self._create_table(source)

        response = get_tenant_query_config(team=self.team, connection_id=str(source.id))

        assert response["enabled"] is False
        assert response["tenant_column_name"] is None
        assert response["disabled_tables"] == []
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

    def test_injects_per_table_tenant_predicate_and_keeps_override_column_in_asterisk(self):
        source = self._create_direct_source()
        self._create_table(
            source,
            name="bookings",
            postgres_columns=[
                ("id", "bigint", False),
                ("customer_id", "bigint", False),
                ("account_id", "bigint", False),
                ("name", "text", True),
            ],
        )
        config = self._create_config(source, tenant_column_names_by_table={"bookings": "account_id"})

        sql = self._prepare_sql(source, config, "select * from bookings")

        normalized_sql = sql.lower()
        assert normalized_sql.count("bookings.account_id") >= 2
        assert "bookings.customer_id" not in normalized_sql
        assert "account_id = 42" in sql
        assert "LIMIT 100" in sql

    def test_injects_id_tenant_predicate_and_keeps_id_column_in_asterisk(self):
        source = self._create_direct_source()
        self._create_table(
            source,
            name="posthog_team",
            postgres_columns=[("id", "bigint", False), ("name", "text", True)],
        )
        config = self._create_config(source, tenant_column_names_by_table={"posthog_team": "id"})

        sql = self._prepare_sql(source, config, "select * from posthog_team")

        normalized_sql = sql.lower()
        assert normalized_sql.count("posthog_team.id") >= 2
        assert "id = 42" in sql
        assert "LIMIT 100" in sql

    def test_injects_foreign_key_tenant_predicate(self):
        source = self._create_direct_source()
        self._create_table(
            source,
            name="posthog_dashboards",
            postgres_columns=[("id", "bigint", False), ("team_id", "bigint", False), ("name", "text", True)],
        )
        self._create_table(
            source,
            name="posthog_dashboard_tiles",
            postgres_columns=[("id", "bigint", False), ("dashboard_id", "bigint", False), ("name", "text", True)],
            postgres_foreign_keys=[("dashboard_id", "posthog_dashboards", "id")],
        )
        config = self._create_config(
            source,
            tenant_column_name="team_id",
            tenant_column_names_by_table={"posthog_dashboard_tiles": "dashboard.team_id"},
        )

        sql = self._prepare_sql(source, config, "select * from posthog_dashboard_tiles")

        assert "team_id = 42" in sql
        assert "dashboard_id" in sql
        assert "LEFT JOIN" in sql
        assert " IN (" not in sql
        assert "LIMIT 100" in sql

    def test_injects_foreign_key_tenant_predicate_for_unqualified_direct_table_alias(self):
        source = self._create_direct_source()
        self._create_table(
            source,
            name="public.posthog_dashboard",
            source_table_name="posthog_dashboard",
            postgres_columns=[("id", "bigint", False), ("team_id", "bigint", False), ("name", "text", True)],
        )
        self._create_table(
            source,
            name="public.posthog_dashboarditem",
            source_table_name="posthog_dashboarditem",
            postgres_columns=[("id", "bigint", False), ("dashboard_id", "bigint", False), ("name", "text", True)],
            postgres_foreign_keys=[("dashboard_id", "posthog_dashboard", "id")],
        )
        config = self._create_config(
            source,
            tenant_column_name="team_id",
            tenant_column_names_by_table={"public.posthog_dashboarditem": "dashboard.team_id"},
        )

        sql = self._prepare_sql(source, config, "select * from posthog_dashboarditem")

        assert "team_id = 42" in sql
        assert "dashboard_id" in sql
        assert "LEFT JOIN" in sql
        assert " IN (" not in sql
        assert "LIMIT 100" in sql

    def test_rejects_nullable_foreign_key_tenant_predicate(self):
        source = self._create_direct_source()
        self._create_table(
            source,
            name="posthog_dashboard",
            postgres_columns=[("id", "bigint", False), ("team_id", "bigint", False), ("name", "text", True)],
        )
        self._create_table(
            source,
            name="posthog_dashboarditem",
            postgres_columns=[
                ("id", "bigint", False),
                ("team_id", "bigint", False),
                ("dashboard_id", "bigint", True),
                ("name", "text", True),
            ],
            postgres_foreign_keys=[("dashboard_id", "posthog_dashboard", "id")],
        )
        config = self._create_config(
            source,
            tenant_column_name="team_id",
            tenant_column_names_by_table={"posthog_dashboarditem": "dashboard.team_id"},
        )

        with self.assertRaisesRegex(Exception, "not a valid foreign key tenancy path"):
            self._prepare_sql(source, config, "select * from posthog_dashboarditem")

    def test_injects_foreign_key_tenant_predicate_without_runtime_lazy_join(self):
        source = self._create_direct_source()
        self._create_table(
            source,
            name="posthog_dashboard",
            postgres_columns=[("id", "bigint", False), ("team_id", "bigint", False), ("name", "text", True)],
        )
        self._create_table(
            source,
            name="posthog_dashboarditem",
            postgres_columns=[("id", "bigint", False), ("dashboard_id", "bigint", False), ("name", "text", True)],
            postgres_foreign_keys=[("dashboard_id", "posthog_dashboard", "id")],
        )
        config = self._create_config(
            source,
            tenant_column_name="team_id",
            tenant_column_names_by_table={"posthog_dashboarditem": "dashboard.team_id"},
        )

        def remove_dashboard_lazy_join(database: Database) -> None:
            database.get_table("posthog_dashboarditem").fields.pop("dashboard", None)

        sql = self._prepare_sql(
            source,
            config,
            "select * from posthog_dashboarditem",
            database_callback=remove_dashboard_lazy_join,
        )

        assert "team_id = 42" in sql
        assert "dashboard_id" in sql
        assert " IN (" in sql
        assert "LIMIT 100" in sql

    def test_no_tenant_field_table_exposes_all_columns_without_tenant_predicate(self):
        source = self._create_direct_source()
        self._create_table(
            source,
            name="countries",
            postgres_columns=[("id", "bigint", False), ("name", "text", True)],
        )
        config = self._create_config(source, tenant_column_names_by_table={"countries": TENANT_QUERY_NO_TENANT_FIELD})

        sql = self._prepare_sql(source, config, "select * from countries", tenant_value=None)

        assert "customer_id" not in sql
        assert "WHERE" not in sql
        assert "LIMIT 100" in sql

    def test_allows_unqualified_table_names_for_single_schema_direct_connections(self):
        source = self._create_direct_source()
        self._create_table(
            source,
            name="public.posthog_activitylog",
            source_schema="public",
            source_table_name="posthog_activitylog",
        )
        config = self._create_config(source)

        sql = self._prepare_sql(source, config, "select id from posthog_activitylog")

        assert "posthog_activitylog" in sql
        assert "customer_id = 42" in sql

    def test_requires_qualified_table_names_for_multi_schema_direct_connections(self):
        source = self._create_direct_source()
        self._create_table(
            source,
            name="public.posthog_activitylog",
            source_schema="public",
            source_table_name="posthog_activitylog",
        )
        self._create_table(
            source,
            name="analytics.posthog_activitylog",
            source_schema="analytics",
            source_table_name="posthog_activitylog",
        )
        config = self._create_config(source)

        with self.assertRaisesRegex(Exception, "Unknown table `posthog_activitylog`"):
            self._prepare_sql(source, config, "select id from posthog_activitylog")

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

    def test_allows_explicit_per_table_tenant_column_output(self):
        source = self._create_direct_source()
        self._create_table(source)
        self._create_table(
            source,
            name="bookings",
            postgres_columns=[("id", "bigint", False), ("account_id", "bigint", False)],
        )
        self._create_config(source, tenant_column_names_by_table={"bookings": "account_id"})

        response = Mock()
        response.results = [[42]]
        response.model_dump.return_value = {"columns": ["account_id"], "results": [[42]], "types": []}

        with patch("products.data_warehouse.backend.tenant_query.HogQLQueryExecutor") as executor_class:
            executor = executor_class.return_value
            executor.execute.return_value = response
            executor.direct_postgres_sql = "SELECT account_id FROM bookings WHERE account_id = 42"
            executor._get_select_query_type.return_value = None

            result, row_count = execute_tenant_query(
                team=self.team,
                user=self.user,
                connection_id=str(source.id),
                tenant_value=42,
                query="select account_id from bookings",
            )

        assert row_count == 1
        assert result["columns"] == ["account_id"]
        assert result["results"] == [[42]]

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

    def test_injects_per_table_tenant_column_predicates(self):
        source = self._create_direct_source()
        self._create_table(source)
        self._create_table(
            source,
            name="bookings",
            postgres_columns=[("id", "bigint", False), ("account_id", "bigint", False), ("name", "text", True)],
        )
        config = self._create_config(source, tenant_column_names_by_table={"bookings": "account_id"})

        sql = self._prepare_sql(
            source,
            config,
            "select t.id, b.id from trips as t join bookings as b on t.id = b.id",
        )

        assert "customer_id = 42" in sql
        assert "account_id = 42" in sql
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

    def test_metadata_tables_omit_schema_for_single_schema_direct_connections(self):
        source = self._create_direct_source()
        self._create_table(
            source,
            name="public.posthog_activitylog",
            source_schema="public",
            source_table_name="posthog_activitylog",
        )
        self._create_config(source)

        result, _row_count = execute_tenant_query(
            team=self.team,
            user=self.user,
            connection_id=str(source.id),
            tenant_value=None,
            query="select * from system.tables",
        )

        assert result["results"] == [["posthog_activitylog", "public", "posthog_activitylog"]]

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

    def test_regular_query_logs_success(self):
        source = self._create_direct_source()
        self._create_table(source)
        self._create_config(source)

        response = Mock()
        response.results = [[1]]
        response.model_dump.return_value = {"columns": ["id"], "results": [[1]], "types": []}

        with (
            patch("products.data_warehouse.backend.tenant_query.HogQLQueryExecutor") as executor_class,
            patch("products.data_warehouse.backend.tenant_query.logger.info") as log_info,
        ):
            executor = executor_class.return_value
            executor.execute.return_value = response
            executor.direct_postgres_sql = "SELECT id FROM trips WHERE customer_id = 42"
            executor._get_select_query_type.return_value = None

            execute_tenant_query(
                team=self.team,
                user=self.user,
                connection_id=str(source.id),
                tenant_value=42,
                query="select id from trips",
            )

        log_info.assert_called_once()
        assert log_info.call_args.args == ("tenant_query_execution",)
        assert log_info.call_args.kwargs["success"] is True
        assert log_info.call_args.kwargs["metadata_only"] is False
        assert log_info.call_args.kwargs["row_count"] == 1
        assert log_info.call_args.kwargs["tenant_value"] == "42"
        assert log_info.call_args.kwargs["postgres_sql"] == "SELECT id FROM trips WHERE customer_id = 42"

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

    def test_metadata_fields_query_keeps_per_table_tenant_column(self):
        source = self._create_direct_source()
        self._create_table(source)
        self._create_table(
            source,
            name="bookings",
            postgres_columns=[
                ("id", "bigint", False),
                ("customer_id", "bigint", False),
                ("account_id", "bigint", False),
                ("name", "text", True),
            ],
        )
        self._create_config(source, tenant_column_names_by_table={"bookings": "account_id"})

        result, _row_count = execute_tenant_query(
            team=self.team,
            user=self.user,
            connection_id=str(source.id),
            tenant_value=None,
            query="select table, name, postgres_type from system.fields where table = 'bookings'",
        )

        assert ["bookings", "id", "bigint"] in result["results"]
        assert ["bookings", "account_id", "bigint"] in result["results"]
        assert ["bookings", "name", "text"] in result["results"]
        assert all(row[1] != "customer_id" for row in result["results"])

    def test_metadata_fields_query_exposes_no_tenant_field_table_columns(self):
        source = self._create_direct_source()
        self._create_table(source)
        self._create_table(
            source,
            name="countries",
            postgres_columns=[("id", "bigint", False), ("customer_id", "bigint", False), ("name", "text", True)],
        )
        self._create_config(source, tenant_column_names_by_table={"countries": TENANT_QUERY_NO_TENANT_FIELD})

        result, _row_count = execute_tenant_query(
            team=self.team,
            user=self.user,
            connection_id=str(source.id),
            tenant_value=None,
            query="select table, name, postgres_type from system.fields where table = 'countries'",
        )

        assert ["countries", "id", "bigint"] in result["results"]
        assert ["countries", "customer_id", "bigint"] in result["results"]
        assert ["countries", "name", "text"] in result["results"]

    def test_metadata_nested_asterisk_query_uses_resolved_subquery_columns(self):
        source = self._create_direct_source()
        self._create_table(source)
        self._create_config(source)

        result, row_count = execute_tenant_query(
            team=self.team,
            user=self.user,
            connection_id=str(source.id),
            tenant_value=None,
            query="select * from (select * from system.tables) as tables",
        )

        assert row_count == 1
        assert result["columns"] == ["name", "source_schema", "source_table_name"]
        assert result["results"] == [["trips", "public", "trips"]]

    def test_metadata_cte_asterisk_query_uses_resolved_cte_columns(self):
        source = self._create_direct_source()
        self._create_table(source)
        self._create_config(source)

        result, _row_count = execute_tenant_query(
            team=self.team,
            user=self.user,
            connection_id=str(source.id),
            tenant_value=None,
            query="with fields as (select * from system.fields) select * from fields where table = 'trips'",
        )

        assert result["columns"] == ["table", "name", "postgres_type", "nullable"]
        assert ["trips", "id", "bigint", False] in result["results"]
        assert ["trips", "name", "text", True] in result["results"]
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

    def test_disabled_query_logs_failure(self):
        source = self._create_direct_source()
        self._create_table(source)
        config = self._create_config(source)
        config.enabled = False
        config.save()

        with patch("products.data_warehouse.backend.tenant_query.logger.info") as log_info:
            with self.assertRaisesRegex(Exception, "Tenant query service is disabled"):
                execute_tenant_query(
                    team=self.team,
                    user=self.user,
                    connection_id=str(source.id),
                    tenant_value=42,
                    query="select id from trips",
                )

        log_info.assert_called_once()
        assert log_info.call_args.args == ("tenant_query_execution",)
        assert log_info.call_args.kwargs["success"] is False
        assert log_info.call_args.kwargs["metadata_only"] is False
        assert log_info.call_args.kwargs["tenant_value"] == "42"
        assert "disabled" in log_info.call_args.kwargs["error"]

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

    def test_lists_tenant_query_executions_from_logs(self):
        timestamp = datetime(2026, 1, 1, tzinfo=UTC)
        response = Mock()
        response.results = [
            [
                "execution-1",
                timestamp,
                "00000000-0000-0000-0000-000000000001",
                "42",
                "select id from trips",
                "SELECT id FROM trips WHERE customer_id = 42",
                1,
                "",
                12.5,
                1,
                '["trips"]',
                0,
            ]
        ]

        with patch(
            "products.data_warehouse.backend.tenant_query.execute_hogql_query", return_value=response
        ) as execute:
            result = list_tenant_query_executions(
                team=self.team,
                connection_id="00000000-0000-0000-0000-000000000001",
                tenant_value=42,
                date_from=timestamp - timedelta(hours=1),
                date_to=timestamp,
                success=True,
            )

        assert result["count"] == 1
        assert result["executions"][0]["referenced_tables"] == ["trips"]
        assert result["executions"][0]["success"] is True
        assert result["executions"][0]["metadata_only"] is False
        assert execute.call_args.kwargs["query_type"] == "TenantQueryLogs"

    def test_gets_tenant_query_execution_detail_from_logs(self):
        timestamp = datetime(2026, 1, 1, tzinfo=UTC)
        response = Mock()
        response.results = [
            [
                "execution-1",
                timestamp,
                "00000000-0000-0000-0000-000000000001",
                "42",
                "select id from trips",
                "SELECT id FROM trips WHERE customer_id = 42",
                1,
                "",
                12.5,
                1,
                '["trips"]',
                0,
                '[{"name": "trips", "postgres_schema": "public"}]',
                '{"engine": "postgres"}',
                {"connection_id": "00000000-0000-0000-0000-000000000001"},
            ]
        ]

        with patch("products.data_warehouse.backend.tenant_query.execute_hogql_query", return_value=response):
            result = get_tenant_query_execution(team=self.team, execution_id="execution-1", timestamp=timestamp)

        assert result is not None
        assert result["referenced_table_metadata"] == [{"name": "trips", "postgres_schema": "public"}]
        assert result["connection_metadata"] == {"engine": "postgres"}
        assert result["attributes"] == {"connection_id": "00000000-0000-0000-0000-000000000001"}

    def test_summarizes_tenant_query_errors_from_logs(self):
        timestamp = datetime(2026, 1, 1, tzinfo=UTC)
        response = Mock()
        response.results = [
            [
                "00000000-0000-0000-0000-000000000001",
                "42",
                '["trips"]',
                "select bad from trips",
                "Unknown field",
                3,
                timestamp,
                9.5,
            ]
        ]

        with patch("products.data_warehouse.backend.tenant_query.execute_hogql_query", return_value=response):
            result = summarize_tenant_query_errors(
                team=self.team,
                date_from=timestamp - timedelta(hours=1),
                date_to=timestamp,
            )

        assert result["errors"][0]["count"] == 3
        assert result["errors"][0]["referenced_tables"] == ["trips"]
        assert result["errors"][0]["error"] == "Unknown field"

    def test_summarizes_tenant_query_usage_from_logs(self):
        timestamp = datetime(2026, 1, 1, tzinfo=UTC)
        response = Mock()
        response.results = [
            [
                "00000000-0000-0000-0000-000000000001",
                "42",
                '["trips"]',
                7,
                6,
                1,
                123,
                13.5,
                timestamp,
            ]
        ]

        with patch("products.data_warehouse.backend.tenant_query.execute_hogql_query", return_value=response):
            result = summarize_tenant_query_usage(
                team=self.team,
                tenant_value="42",
                date_from=timestamp - timedelta(hours=1),
                date_to=timestamp,
            )

        assert result["usage"][0]["count"] == 7
        assert result["usage"][0]["success_count"] == 6
        assert result["usage"][0]["error_count"] == 1
        assert result["usage"][0]["total_rows"] == 123

    def test_executions_endpoint_uses_tenant_query_log_service(self):
        with patch("products.data_warehouse.backend.api.tenant_query.list_tenant_query_executions") as list_executions:
            list_executions.return_value = {"executions": [], "count": 0}
            response = self.client.post(
                f"/api/environments/{self.team.id}/tenant_query/executions/",
                {
                    "connection_id": "00000000-0000-0000-0000-000000000001",
                    "tenant_value": "42",
                    "success": True,
                },
                format="json",
            )

        assert response.status_code == 200
        assert response.json() == {"executions": [], "count": 0}
        list_executions.assert_called_once()
        call_kwargs = cast(dict, list_executions.call_args.kwargs)
        assert call_kwargs["connection_id"] == "00000000-0000-0000-0000-000000000001"
        assert call_kwargs["tenant_value"] == "42"
        assert call_kwargs["success"] is True

    def test_execution_endpoint_returns_404_for_missing_log(self):
        with patch("products.data_warehouse.backend.api.tenant_query.get_tenant_query_execution", return_value=None):
            response = self.client.post(
                f"/api/environments/{self.team.id}/tenant_query/execution/",
                {"execution_id": "execution-1"},
                format="json",
            )

        assert response.status_code == 404

    def test_error_summary_endpoint_uses_tenant_query_log_service(self):
        with patch(
            "products.data_warehouse.backend.api.tenant_query.summarize_tenant_query_errors"
        ) as summarize_errors:
            summarize_errors.return_value = {"errors": [], "count": 0}
            response = self.client.post(
                f"/api/environments/{self.team.id}/tenant_query/errors/summary/",
                {"tenant_value": "42"},
                format="json",
            )

        assert response.status_code == 200
        assert response.json() == {"errors": [], "count": 0}
        summarize_errors.assert_called_once()
        call_kwargs = cast(dict, summarize_errors.call_args.kwargs)
        assert call_kwargs["tenant_value"] == "42"

    def test_usage_summary_endpoint_uses_tenant_query_log_service(self):
        with patch("products.data_warehouse.backend.api.tenant_query.summarize_tenant_query_usage") as summarize_usage:
            summarize_usage.return_value = {"usage": [], "count": 0}
            response = self.client.post(
                f"/api/environments/{self.team.id}/tenant_query/usage/summary/",
                {"tenant_value": "42"},
                format="json",
            )

        assert response.status_code == 200
        assert response.json() == {"usage": [], "count": 0}
        summarize_usage.assert_called_once()
        call_kwargs = cast(dict, summarize_usage.call_args.kwargs)
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

    def test_config_load_endpoint_uses_tenant_query_config_service(self):
        with patch("products.data_warehouse.backend.api.tenant_query.get_tenant_query_config") as get_config:
            get_config.return_value = {
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
                f"/api/environments/{self.team.id}/tenant_query/config/load/",
                {
                    "connection_id": "00000000-0000-0000-0000-000000000001",
                },
                format="json",
            )

        assert response.status_code == 200
        assert response.json()["enabled"] is True
        get_config.assert_called_once()
