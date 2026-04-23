import pytest
from unittest import mock

from psycopg import sql as psql

from posthog.schema import HogQLQuery

from posthog.ducklake.client import _SEARCH_PATH_SCHEMAS, execute_ducklake_query

pytestmark = [pytest.mark.django_db]


class TestExecuteDuckLakeQuery:
    def test_rejects_both_sql_and_query(self):
        with pytest.raises(ValueError, match="not both"):
            execute_ducklake_query(1, sql="SELECT 1", query=HogQLQuery(query="SELECT 1"))

    def test_rejects_neither_sql_nor_query(self):
        with pytest.raises(ValueError, match="either sql or query"):
            execute_ducklake_query(1)

    @mock.patch("posthog.ducklake.client.psycopg")
    @mock.patch("posthog.ducklake.client.get_duckgres_config")
    def test_sql_path_executes_directly(self, mock_config, mock_psycopg):
        mock_config.return_value = {
            "DUCKGRES_HOST": "localhost",
            "DUCKGRES_PORT": "5432",
            "DUCKGRES_DATABASE": "ducklake",
            "DUCKGRES_USERNAME": "posthog",
            "DUCKGRES_PASSWORD": "posthog",
        }
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
    @mock.patch("posthog.ducklake.client.get_duckgres_config")
    @mock.patch("posthog.ducklake.client.compile_hogql_to_ducklake_sql")
    def test_query_path_compiles_and_executes(self, mock_compile, mock_config, mock_psycopg):
        mock_compile.return_value = ("SELECT count(*) FROM events", {}, "SELECT count() FROM events")
        mock_config.return_value = {
            "DUCKGRES_HOST": "localhost",
            "DUCKGRES_PORT": "5432",
            "DUCKGRES_DATABASE": "ducklake",
            "DUCKGRES_USERNAME": "posthog",
            "DUCKGRES_PASSWORD": "posthog",
        }
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
    @mock.patch("posthog.ducklake.client.get_duckgres_config")
    def test_sets_search_path(self, mock_config, mock_psycopg):
        mock_config.return_value = {
            "DUCKGRES_HOST": "localhost",
            "DUCKGRES_PORT": "5432",
            "DUCKGRES_DATABASE": "ducklake",
            "DUCKGRES_USERNAME": "posthog",
            "DUCKGRES_PASSWORD": "posthog",
        }
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
