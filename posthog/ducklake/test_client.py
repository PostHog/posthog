import pytest
from unittest import mock

from django.conf import settings

from psycopg import sql as psql

from posthog.schema import HogQLQuery

from posthog.ducklake.client import (
    _SEARCH_PATH_SCHEMAS,
    _coerce_lossy_columns,
    execute_ducklake_query,
    export_ducklake_table_to_parquet,
)

pytestmark = [pytest.mark.django_db]


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

        mock_compile.assert_called_once_with(1, query)
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


class TestExportDuckLakeTableToParquet:
    @mock.patch("posthog.ducklake.client.psycopg")
    @mock.patch("posthog.ducklake.client.is_dev_mode", return_value=True)
    def test_copies_live_set_to_parquet_and_returns_count(self, _mock_dev_mode, mock_psycopg):
        mock_cursor = mock.MagicMock()
        mock_cursor.fetchone.return_value = (3,)
        mock_conn = mock.MagicMock()
        mock_conn.cursor.return_value.__enter__ = mock.Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mock.Mock(return_value=False)
        mock_psycopg.connect.return_value.__enter__ = mock.Mock(return_value=mock_conn)
        mock_psycopg.connect.return_value.__exit__ = mock.Mock(return_value=False)

        result = export_ducklake_table_to_parquet(1, "shadow_1_models", "my_view", organization_id="org-456")

        expected_destination = f"{settings.BUCKET_URL}/data_modeling_ducklake_export/org_org-456/team_1/my_view.parquet"
        assert result.destination == expected_destination
        assert result.schema_name == "shadow_1_models"
        assert result.table_name == "my_view"
        assert result.row_count == 3

        # COPY uses a quoted identifier and a literal destination — never string interpolation
        expected_copy = psql.SQL("COPY (SELECT * FROM {}) TO {} (FORMAT parquet)").format(
            psql.Identifier("shadow_1_models", "my_view"),
            psql.Literal(expected_destination),
        )
        assert mock_cursor.execute.call_args_list[0] == mock.call(expected_copy)

    @mock.patch("posthog.ducklake.client.psycopg")
    @mock.patch("posthog.ducklake.client.is_dev_mode", return_value=True)
    def test_resolves_org_id_when_not_provided(self, _mock_dev_mode, mock_psycopg):
        mock_cursor = mock.MagicMock()
        mock_cursor.fetchone.return_value = (0,)
        mock_conn = mock.MagicMock()
        mock_conn.cursor.return_value.__enter__ = mock.Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = mock.Mock(return_value=False)
        mock_psycopg.connect.return_value.__enter__ = mock.Mock(return_value=mock_conn)
        mock_psycopg.connect.return_value.__exit__ = mock.Mock(return_value=False)

        with mock.patch("posthog.ducklake.common._get_org_id_for_team", return_value="org-456") as mock_lookup:
            result = export_ducklake_table_to_parquet(1, "shadow_1_models", "my_view")

        mock_lookup.assert_called_once_with(1)
        assert (
            result.destination
            == f"{settings.BUCKET_URL}/data_modeling_ducklake_export/org_org-456/team_1/my_view.parquet"
        )


class TestCoerceLossyColumns:
    @pytest.mark.parametrize(
        "describe_rows,sql,expected",
        [
            pytest.param(
                # DESCRIBE rows: (column_name, column_type, ...)
                [("big_h", "HUGEINT"), ("label", "VARCHAR")],
                "SELECT big_h, label FROM t",
                psql.SQL("SELECT * REPLACE ({repl}) FROM ({inner}) AS _ph_coerce").format(
                    repl=psql.SQL(", ").join(
                        [
                            psql.SQL("CAST({col} AS {target}) AS {col}").format(
                                col=psql.Identifier("big_h"),
                                target=psql.SQL("DECIMAL(38, 0)"),
                            )
                        ]
                    ),
                    inner=psql.SQL("SELECT big_h, label FROM t"),
                ),
                id="wraps_lossy_columns_with_cast",
            ),
            pytest.param(
                [("label", "VARCHAR"), ("n", "BIGINT")],
                "SELECT label, n FROM t",
                psql.SQL("SELECT label, n FROM t"),
                id="returns_original_when_no_lossy_columns",
            ),
        ],
    )
    def test_coerces_lossy_columns(self, describe_rows, sql, expected):
        cur = mock.MagicMock()
        cur.fetchall.return_value = describe_rows

        result = _coerce_lossy_columns(cur, sql, None)

        assert result == expected

    def test_returns_original_when_probe_fails(self):
        cur = mock.MagicMock()
        cur.execute.side_effect = Exception("DESCRIBE not supported")

        result = _coerce_lossy_columns(cur, "SELECT 1", None)

        assert result == psql.SQL("SELECT 1")
