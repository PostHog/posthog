import pytest
from unittest import mock

from psycopg import sql as psql

from posthog.schema import HogQLQuery, HogQLVariable

from posthog.ducklake.client import _SEARCH_PATH_SCHEMAS, compile_hogql_to_ducklake_sql, execute_ducklake_query

pytestmark = [pytest.mark.django_db]


class TestCompileHogQLToDuckLakeSQL:
    def test_substitutes_variable_placeholders(self):
        from posthog.models import Organization, Team

        from products.product_analytics.backend.models.insight_variable import InsightVariable

        org = Organization.objects.create(name="ducklake-vars")
        team = Team.objects.create(organization=org)
        variable = InsightVariable.objects.create(
            team=team, name="Event name", code_name="event_name", type="String", default_value="$pageview"
        )

        query = HogQLQuery(
            query="SELECT event FROM events WHERE event = {variables.event_name} LIMIT 10",
            variables={
                str(variable.id): HogQLVariable(variableId=str(variable.id), code_name="event_name", value="purchase")
            },
        )

        postgres_sql, values, _hogql_pretty = compile_hogql_to_ducklake_sql(team.pk, query)

        assert "purchase" in values.values()
        assert "variables" not in postgres_sql


class TestDuckLakeModelRedirect:
    def test_materialized_model_resolves_to_ducklake_table_not_s3(self):
        from posthog.models import Organization, Team

        from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
        from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable

        org = Organization.objects.create(name="ducklake-redirect")
        team = Team.objects.create(organization=org)
        credential = DataWarehouseCredential.objects.create(team=team, access_key="key", access_secret="secret")
        source_table = DataWarehouseTable.objects.create(
            name="vitally_source",
            team=team,
            columns={"org_id": "String"},
            credential=credential,
            url_pattern="https://bucket.s3.amazonaws.com/vitally/*.parquet",
            format="Parquet",
        )
        DataWarehouseSavedQuery.objects.create(
            team=team,
            name="vitally_org",
            query={"query": "SELECT org_id FROM vitally_source"},
            columns={"org_id": {"clickhouse": "String", "hogql": "StringDatabaseField"}},
            table=source_table,
            is_materialized=True,
            status=DataWarehouseSavedQuery.Status.COMPLETED,
        )

        query = HogQLQuery(query="SELECT org_id FROM vitally_org")
        postgres_sql, _values, _hogql = compile_hogql_to_ducklake_sql(team.pk, query)

        # The duckgres path must read the DuckLake-materialized model, not the
        # ClickHouse s3() table function, which DuckDB cannot execute.
        assert "s3(" not in postgres_sql.lower()
        assert f"shadow_{team.pk}_models" in postgres_sql

    def test_source_table_resolves_to_ducklake_table_not_s3(self):
        from posthog.ducklake.common import duckgres_data_imports_schema, duckgres_data_imports_table_name
        from posthog.models import Organization, Team

        from products.warehouse_sources.backend.facade.models import (
            DataWarehouseCredential,
            DataWarehouseTable,
            ExternalDataSchema,
            ExternalDataSource,
        )
        from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

        org = Organization.objects.create(name="ducklake-source-redirect")
        team = Team.objects.create(organization=org)
        source = ExternalDataSource.objects.create(
            team=team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
            prefix="myprefix_",
        )
        credential = DataWarehouseCredential.objects.create(team=team, access_key="key", access_secret="secret")
        warehouse_table = DataWarehouseTable.objects.create(
            name="myprefix_stripe_customers",
            format="Parquet",
            team=team,
            external_data_source=source,
            external_data_source_id=source.id,
            credential=credential,
            url_pattern="https://bucket.s3.amazonaws.com/stripe/customers/*.parquet",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )
        schema = ExternalDataSchema.objects.create(
            team=team,
            name="customers",
            source=source,
            table=warehouse_table,
            should_sync=True,
        )

        query = HogQLQuery(query="SELECT id FROM myprefix_stripe_customers")
        postgres_sql, _values, _hogql = compile_hogql_to_ducklake_sql(team.pk, query)

        # The duckgres path must read the DuckLake-copied source table, not the
        # ClickHouse s3() table function, which DuckDB cannot execute.
        assert "s3(" not in postgres_sql.lower()
        assert duckgres_data_imports_schema(team.pk) in postgres_sql
        assert duckgres_data_imports_table_name(schema) in postgres_sql


class TestDuckgresShadowCompilation:
    @mock.patch("posthog.ducklake.client.compile_hogql_to_ducklake_sql")
    def test_materialization_compile_bypasses_warehouse_access_control(self, mock_compile):
        from posthog.temporal.data_modeling.activities.materialize_view_duckgres import _compile_hogql_to_postgres_sql

        mock_compile.return_value = ("SELECT * FROM source", {}, "SELECT * FROM source")

        _compile_hogql_to_postgres_sql("SELECT * FROM source", 1)

        query = mock_compile.call_args.args[1]
        assert query.query == "SELECT * FROM source"
        assert mock_compile.call_args.kwargs == {"bypass_warehouse_access_control": True}


class TestExecuteDuckLakeQuery:
    def test_rejects_both_sql_and_query(self):
        with pytest.raises(ValueError, match="not both"):
            execute_ducklake_query(1, sql="SELECT 1", query=HogQLQuery(query="SELECT 1"))

    def test_rejects_neither_sql_nor_query(self):
        with pytest.raises(ValueError, match="either sql or query"):
            execute_ducklake_query(1)

    @mock.patch("posthog.ducklake.client.psycopg")
    @mock.patch("posthog.ducklake.client.is_dev_mode", return_value=True)
    def test_sql_path_executes_directly(self, _mock_dev_mode, mock_psycopg):
        mock_cursor = mock.MagicMock()
        mock_cursor.description = [
            mock.MagicMock(name="col1", type_code=25),
            mock.MagicMock(name="col2", type_code=20),
        ]
        mock_cursor.description[0].name = "event"
        mock_cursor.description[1].name = "count"
        mock_cursor.fetchall.return_value = [("$pageview", 42)]
        mock_conn = mock.MagicMock()
        mock_conn.cursor.return_value.__enter__ = mock.Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mock.Mock(return_value=False)
        mock_psycopg.connect.return_value.__enter__ = mock.Mock(return_value=mock_conn)
        mock_psycopg.connect.return_value.__exit__ = mock.Mock(return_value=False)

        result = execute_ducklake_query(1, sql="SELECT event, count(*) FROM events")

        assert result.columns == ["event", "count"]
        assert result.results == [["$pageview", 42]]
        assert result.sql == "SELECT event, count(*) FROM events"
        assert result.hogql is None

    @mock.patch("posthog.ducklake.client.psycopg")
    @mock.patch("posthog.ducklake.client.is_dev_mode", return_value=True)
    @mock.patch("posthog.ducklake.client.compile_hogql_to_ducklake_sql")
    def test_query_path_compiles_and_executes(self, mock_compile, _mock_dev_mode, mock_psycopg):
        mock_compile.return_value = ("SELECT count(*) FROM events", {}, "SELECT count() FROM events")
        mock_cursor = mock.MagicMock()
        mock_cursor.description = [mock.MagicMock(name="cnt", type_code=20)]
        mock_cursor.description[0].name = "cnt"
        mock_cursor.fetchall.return_value = [(42,)]
        mock_conn = mock.MagicMock()
        mock_conn.cursor.return_value.__enter__ = mock.Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mock.Mock(return_value=False)
        mock_psycopg.connect.return_value.__enter__ = mock.Mock(return_value=mock_conn)
        mock_psycopg.connect.return_value.__exit__ = mock.Mock(return_value=False)

        query = HogQLQuery(query="SELECT count() FROM events")
        result = execute_ducklake_query(1, query=query)

        mock_compile.assert_called_once_with(1, query, team=None, user=None, bypass_warehouse_access_control=False)
        assert result.sql == "SELECT count(*) FROM events"
        assert result.hogql == "SELECT count() FROM events"
        assert result.results == [[42]]

    @mock.patch("posthog.ducklake.client.psycopg")
    @mock.patch("posthog.ducklake.client.is_dev_mode", return_value=True)
    def test_sets_search_path(self, _mock_dev_mode, mock_psycopg):
        mock_cursor = mock.MagicMock()
        mock_cursor.description = []
        mock_cursor.fetchall.return_value = []
        mock_conn = mock.MagicMock()
        mock_conn.cursor.return_value.__enter__ = mock.Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mock.Mock(return_value=False)
        mock_psycopg.connect.return_value.__enter__ = mock.Mock(return_value=mock_conn)
        mock_psycopg.connect.return_value.__exit__ = mock.Mock(return_value=False)

        execute_ducklake_query(1, sql="SELECT 1")

        expected_sql = psql.SQL("SET search_path TO {}").format(psql.Literal(",".join(_SEARCH_PATH_SCHEMAS)))
        mock_conn.execute.assert_called_once_with(expected_sql)

    @mock.patch("posthog.ducklake.client.psycopg")
    @mock.patch("posthog.ducklake.client.get_duckgres_config_for_org")
    @mock.patch("posthog.ducklake.client.is_dev_mode", return_value=False)
    def test_production_path_resolves_org(self, _mock_dev_mode, mock_config_for_org, mock_psycopg):
        mock_config_for_org.return_value = {
            "DUCKGRES_HOST": "prod.duckgres.com",
            "DUCKGRES_PORT": "5432",
            "DUCKGRES_DATABASE": "warehouse",
            "DUCKGRES_USERNAME": "root",
            "DUCKGRES_PASSWORD": "secret",
        }
        mock_cursor = mock.MagicMock()
        mock_cursor.description = [mock.MagicMock(name="cnt", type_code=20)]
        mock_cursor.description[0].name = "cnt"
        mock_cursor.fetchall.return_value = [(1,)]
        mock_conn = mock.MagicMock()
        mock_conn.cursor.return_value.__enter__ = mock.Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mock.Mock(return_value=False)
        mock_psycopg.connect.return_value.__enter__ = mock.Mock(return_value=mock_conn)
        mock_psycopg.connect.return_value.__exit__ = mock.Mock(return_value=False)

        with mock.patch("posthog.ducklake.common._get_org_id_for_team", return_value="org-456"):
            result = execute_ducklake_query(1, sql="SELECT 1")

        mock_config_for_org.assert_called_once_with("org-456")
        assert result.results == [[1]]
