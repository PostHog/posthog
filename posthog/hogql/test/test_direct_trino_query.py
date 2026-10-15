from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import DateRange, HogLanguage, HogQLFilters, HogQLMetadata, HogQLQuery, HogQLVariable

from posthog.hogql.metadata import get_hogql_metadata
from posthog.hogql.query import HogQLQueryExecutor
from posthog.hogql.transforms.trino.errors import TrinoLoweringError

from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner

from products.actions.backend.models.action import Action
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_warehouse.backend.facade.api import DIRECT_TRINO_URL_PATTERN
from products.data_warehouse.backend.facade.sources import (
    DIRECT_TRINO_CATALOG_OPTION,
    DIRECT_TRINO_SCHEMA_OPTION,
    DIRECT_TRINO_TABLE_OPTION,
)
from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehouseTableNames,
    ManagedWarehouseTeamMembership,
    TrinoExpansionMode,
)
from products.managed_warehouse.backend.trino_compiler import (
    compile_hogql_to_trino_sql,
    is_managed_trino_editor_connection,
)
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType


class TestDirectTrinoQuery(APIBaseTest):
    def _create_source_and_table(self) -> ExternalDataSource:
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id=str(uuid4()),
            connection_id=str(uuid4()),
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.TRINO,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="analytics",
            job_inputs={
                "host": "trino.example.com",
                "port": 443,
                "catalog": "ducklake",
                "schema": "analytics",
                "auth_type": {"selection": "none", "user": "posthog"},
                "use_ssl": True,
                "verify_ssl": True,
            },
        )
        DataWarehouseTable.objects.create(
            name="orders",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            external_data_source=source,
            url_pattern=DIRECT_TRINO_URL_PATTERN,
            columns={
                "id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True},
                "status": {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True},
            },
            options={
                DIRECT_TRINO_CATALOG_OPTION: "ducklake",
                DIRECT_TRINO_SCHEMA_OPTION: "analytics",
                DIRECT_TRINO_TABLE_OPTION: "materialized_orders",
            },
        )
        return source

    def test_query_editor_compiles_to_explicit_trino_relation(self) -> None:
        source = self._create_source_and_table()
        executor = HogQLQueryExecutor(
            query="SELECT ID FROM ORDERS WHERE STATUS = 'paid'",
            team=self.team,
            connection_id=str(source.id),
        )

        sql, context = executor.generate_clickhouse_sql()

        self.assertIn('"ducklake"."analytics"."materialized_orders"', sql)
        self.assertEqual(executor.direct_dialect, "trino")
        self.assertEqual(executor.direct_values, context.values)
        self.assertIn("paid", context.values.values())

    @parameterized.expand(
        [
            ("action", "SELECT matchesAction(1) FROM orders", {}, "TRINO_PURE_ACTION_UNSUPPORTED"),
            ("cohort", "SELECT id FROM orders WHERE id IN COHORT 1", {}, "TRINO_PURE_COHORT_UNSUPPORTED"),
            (
                "filters",
                "SELECT id FROM orders",
                {"filters": HogQLFilters(dateRange=DateRange(date_from="-7d"))},
                "TRINO_PURE_FILTERS_UNSUPPORTED",
            ),
            (
                "variables",
                "SELECT id FROM orders",
                {"variables": {"value": HogQLVariable(code_name="value", variableId="1", value=1)}},
                "TRINO_PURE_VARIABLES_UNSUPPORTED",
            ),
            ("placeholder", "SELECT id FROM orders WHERE {filters}", {}, "TRINO_PURE_PLACEHOLDER_UNSUPPORTED"),
        ]
    )
    def test_query_editor_uses_pure_compilation(self, _name: str, query: str, options: dict, code: str) -> None:
        source = self._create_source_and_table()
        metadata = get_hogql_metadata(
            HogQLMetadata(query=query, language=HogLanguage.HOG_QL, connectionId=str(source.id), **options),
            team=self.team,
            user=self.user,
        )
        runner = HogQLQueryRunner(
            team=self.team, user=self.user, query=HogQLQuery(query=query, connectionId=str(source.id), **options)
        )
        with self.assertRaises(TrinoLoweringError) as error:
            runner.calculate()
        self.assertEqual(error.exception.feature_code, code)
        self.assertFalse(metadata.isValid)
        self.assertEqual(metadata.errors[0].code, code)
        self.assertEqual(metadata.errors[0].start, error.exception.start)
        self.assertEqual(metadata.errors[0].end, error.exception.end)

    def test_metadata_reports_approximate_quantile_parity_without_rejecting_query(self) -> None:
        source = self._create_source_and_table()
        query = "SELECT quantile(0.5)(id) FROM orders"
        metadata = get_hogql_metadata(
            HogQLMetadata(query=query, language=HogLanguage.HOG_QL, connectionId=str(source.id)),
            team=self.team,
            user=self.user,
        )
        self.assertTrue(metadata.isValid, metadata.errors)
        self.assertEqual([notice.code for notice in metadata.warnings], ["TRINO_APPROXIMATE_QUANTILE_PARITY"])
        self.assertEqual(metadata.warnings[0].start, query.index("quantile"))

    @parameterized.expand(
        [
            ("enabled", True, True, "duckgres_service", True),
            ("flag_off", False, True, "duckgres_service", False),
            ("not_system_managed", True, False, "duckgres_service", False),
            ("legacy_credentials", True, True, "project_reader", False),
        ]
    )
    def test_managed_semantics_require_server_identity_and_rollout(
        self,
        _name: str,
        flag: bool,
        system_managed: bool,
        credential_kind: str,
        expected: bool,
    ) -> None:
        source = self._create_source_and_table()
        source.source_type = ExternalDataSourceType.POSTGRES
        source.prefix = "managed_warehouse"
        source.job_inputs = {}
        source.direct_query_enabled = True
        source.connection_metadata = {
            "engine": "duckdb",
            "system_managed": system_managed,
            "credential_kind": credential_kind,
            "lifecycle_generation": 1,
        }
        source.save()
        with patch("posthog.ph_client.feature_enabled_or_false", return_value=flag):
            self.assertEqual(is_managed_trino_editor_connection(self.team.pk, str(source.id)), expected)
            self.assertFalse(is_managed_trino_editor_connection(self.team.pk + 1, str(source.id)))

    @parameterized.expand([("connection", False), ("hosted", True)])
    def test_managed_editor_expands_actions_and_saved_queries_with_model_compiler(
        self, _name: str, hosted: bool
    ) -> None:
        source = self._create_source_and_table()
        source.source_type = ExternalDataSourceType.POSTGRES
        source.prefix = "managed_warehouse"
        source.job_inputs = {}
        source.direct_query_enabled = True
        source.connection_metadata = {
            "engine": "duckdb",
            "system_managed": True,
            "credential_kind": "duckgres_service",
            "lifecycle_generation": 1,
        }
        source.save()
        action = Action.objects.create(team=self.team, name="checkout", steps_json=[{"event": "checkout"}])
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="checkout_events",
            query={"kind": "HogQLQuery", "query": f"SELECT event FROM events WHERE matchesAction({action.pk})"},
            columns={"event": {"clickhouse": "String", "hogql": "StringDatabaseField"}},
        )
        query = "SELECT event FROM checkout_events LIMIT 10"
        membership = ManagedWarehouseTeamMembership(
            team_id=self.team.pk,
            organization_id=str(self.organization.pk),
            enabled=True,
            backfill_enabled=True,
            schema_name="production",
            earliest_event_date=None,
            table_names=ManagedWarehouseTableNames(
                events_table="events_production", persons_table="persons_production", data_imports_schema="imports"
            ),
        )
        with (
            patch(
                "products.managed_warehouse.backend.query_execution.posthoganalytics.feature_enabled", return_value=True
            ),
            patch(
                "products.managed_warehouse.backend.logic.sql_editor.managed_warehouse_sql_editor_uses_trino",
                return_value=True,
            ),
            patch(
                "products.managed_warehouse.backend.facade.sql_editor.managed_warehouse_sql_editor_uses_trino",
                return_value=True,
            ),
            patch(
                "posthog.ph_client.feature_enabled_or_false",
                side_effect=lambda key, *args, **kwargs: key == "managed-warehouse-trino-editor",
            ),
            patch(
                "products.managed_warehouse.backend.trino_compiler.get_ready_trino_catalog_name",
                return_value="org_catalog",
            ),
            patch("products.managed_warehouse.backend.trino_compiler.get_org_team_membership", return_value=membership),
            patch("products.managed_warehouse.backend.cp_teams.list_org_teams", return_value=[]),
        ):
            metadata = get_hogql_metadata(
                HogQLMetadata(
                    query=query,
                    language=HogLanguage.HOG_QL,
                    connectionId=None if hosted else str(source.id),
                    sourceQuery=HogQLQuery(query=query, executionTarget="managed_trino") if hosted else None,
                ),
                team=self.team,
                user=self.user,
            )
            executor = HogQLQueryExecutor(query=query, team=self.team, user=self.user, connection_id=str(source.id))
            sql, context = executor.generate_clickhouse_sql()
            model = compile_hogql_to_trino_sql(
                self.team.pk, HogQLQuery(query=query), user=self.user, expansion_mode=TrinoExpansionMode.DJANGO
            )
        self.assertTrue(metadata.isValid, metadata.errors)
        self.assertEqual(" ".join(sql.split()), " ".join(model.sql.split()))
        self.assertEqual(context.values, model.values)
        self.assertNotIn("matchesAction", sql)
        self.assertIn('"org_catalog"."posthog"."events_production"', sql)

    @patch("posthog.hogql.direct_sql.trino_adapter.TrinoAdapter.validate_source_config")
    @patch("products.warehouse_sources.backend.facade.source_management.connect_trino")
    def test_query_editor_executes_compiled_values_as_driver_parameters(
        self, mock_connect_trino: MagicMock, mock_validate_source_config: MagicMock
    ) -> None:
        source = self._create_source_and_table()
        mock_validate_source_config.return_value = (MagicMock(), MagicMock())
        cursor = MagicMock()
        cursor.fetchmany.return_value = [(7,)]
        cursor.description = [("id", "bigint")]
        connection = MagicMock()
        connection.cursor.return_value = cursor
        mock_connect_trino.return_value.__enter__.return_value = connection
        runner = HogQLQueryRunner(
            team=self.team,
            query=HogQLQuery(
                query="SELECT id FROM orders WHERE status = {status} LIMIT 1",
                values={"status": "paid"},
                connectionId=str(source.id),
            ),
        )

        metadata = get_hogql_metadata(
            HogQLMetadata(
                query=runner.query.query,
                globals=runner.query.values,
                language=HogLanguage.HOG_QL,
                connectionId=str(source.id),
                includeOutputTypes=True,
            ),
            team=self.team,
            user=self.user,
        )
        self.assertTrue(metadata.isValid, metadata.errors)
        assert metadata.output_columns is not None
        self.assertEqual(metadata.output_columns[0].name, "id")
        response = runner.calculate()

        submitted_sql, submitted_values = cursor.execute.call_args.args
        self.assertIn('"ducklake"."analytics"."materialized_orders"', submitted_sql)
        self.assertIn("?", submitted_sql)
        self.assertNotIn("paid", submitted_sql)
        self.assertEqual(submitted_values, ["paid"])
        self.assertEqual(response.results, [(7,)])
