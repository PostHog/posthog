import pytest
from unittest.mock import MagicMock, patch

import duckdb
from parameterized import parameterized

from posthog.ducklake.common import initialize_ducklake, is_version_mismatch, reset_ducklake_catalog

TEST_CONFIG = {
    "DUCKLAKE_RDS_HOST": "localhost",
    "DUCKLAKE_RDS_PORT": "5432",
    "DUCKLAKE_RDS_DATABASE": "ducklake",
    "DUCKLAKE_RDS_USERNAME": "posthog",
    "DUCKLAKE_RDS_PASSWORD": "posthog",
    "DUCKLAKE_BUCKET": "ducklake-dev",
    "DUCKLAKE_BUCKET_REGION": "us-east-1",
    "DUCKLAKE_S3_ACCESS_KEY": "",
    "DUCKLAKE_S3_SECRET_KEY": "",
}


class TestIsVersionMismatch:
    @parameterized.expand(
        [
            (
                "catalog_version_04",
                "DuckLake catalog version mismatch: catalog version is 0.3, but the extension requires version 0.4",
            ),
            (
                "catalog_version_03",
                "DuckLake catalog version mismatch: catalog version is 0.2, but the extension requires version 0.3",
            ),
            ("only_versions", "Not implemented Error: Only DuckLake versions 0.1, 0.2, 0.3-dev1 and 0.3 are supported"),
            (
                "ducklake_version",
                "Invalid Input Error: DuckLake version 0.3 is not compatible with extension version 0.4",
            ),
        ]
    )
    def test_detects_known_patterns(self, _name: str, message: str):
        assert is_version_mismatch(Exception(message)) is True

    @parameterized.expand(
        [
            ("connection_refused", "connection refused"),
            ("table_not_found", "Table not found: ducklake_metadata"),
            ("unrelated_not_implemented", "Not implemented Error: COPY FROM is not supported"),
            ("empty", ""),
        ]
    )
    def test_rejects_unrelated_errors(self, _name: str, message: str):
        assert is_version_mismatch(Exception(message)) is False


class TestResetDucklakeCatalog:
    @patch.dict("os.environ", {"POSTHOG_ALLOW_DUCKLAKE_CATALOG_RESET": "1"}, clear=True)
    @patch("posthog.ducklake.common.is_dev_mode", return_value=True)
    @patch("posthog.ducklake.common.psycopg")
    def test_terminates_connections_before_drop(self, mock_psycopg: MagicMock, _mock_dev: MagicMock):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_psycopg.connect.return_value = mock_conn

        reset_ducklake_catalog(TEST_CONFIG)

        calls = [str(c) for c in mock_cursor.execute.call_args_list]
        assert any("pg_terminate_backend" in c for c in calls)
        assert any("DROP DATABASE" in c for c in calls)
        assert any("CREATE DATABASE" in c for c in calls)
        terminate_idx = next(i for i, c in enumerate(calls) if "pg_terminate_backend" in c)
        drop_idx = next(i for i, c in enumerate(calls) if "DROP DATABASE" in c)
        assert terminate_idx < drop_idx

    @patch("posthog.ducklake.common.is_dev_mode", return_value=False)
    def test_raises_in_production_mode(self, _mock_dev: MagicMock):
        with pytest.raises(RuntimeError, match="only allowed in dev mode"):
            reset_ducklake_catalog(TEST_CONFIG)

    @patch.dict("os.environ", {}, clear=True)
    @patch("posthog.ducklake.common.is_dev_mode", return_value=True)
    def test_requires_explicit_env_opt_in(self, _mock_dev: MagicMock):
        with pytest.raises(RuntimeError, match="POSTHOG_ALLOW_DUCKLAKE_CATALOG_RESET=1"):
            reset_ducklake_catalog(TEST_CONFIG)


class TestInitializeDucklake:
    @patch.dict("os.environ", {"POSTHOG_ALLOW_DUCKLAKE_CATALOG_RESET": "1"}, clear=True)
    @patch("posthog.ducklake.common.is_dev_mode", return_value=True)
    @patch("posthog.ducklake.common.reset_ducklake_catalog")
    @patch("posthog.ducklake.common.run_smoke_check")
    @patch("posthog.ducklake.common.ensure_ducklake_catalog")
    @patch("posthog.ducklake.common.duckdb")
    def test_auto_resets_on_version_mismatch_dev_mode(
        self,
        mock_duckdb: MagicMock,
        mock_ensure: MagicMock,
        mock_smoke: MagicMock,
        mock_reset: MagicMock,
        _mock_dev: MagicMock,
    ):
        mock_conn = MagicMock()
        fresh_conn = MagicMock()
        mock_duckdb.connect.side_effect = [mock_conn, fresh_conn]
        mock_duckdb.NotImplementedException = duckdb.NotImplementedException
        mock_duckdb.InvalidInputException = duckdb.InvalidInputException
        mock_duckdb.CatalogException = duckdb.CatalogException

        version_exc = duckdb.NotImplementedException("Only DuckLake versions 0.1, 0.2, 0.3-dev1 and 0.3 are supported")

        def attach_side_effect(conn, config, alias="ducklake"):
            if conn is mock_conn:
                raise version_exc

        with patch("posthog.ducklake.common.attach_catalog", side_effect=attach_side_effect):
            result = initialize_ducklake(TEST_CONFIG)

        assert result is True
        mock_reset.assert_called_once_with(TEST_CONFIG)
        mock_conn.close.assert_called()

    @patch("posthog.ducklake.common.is_dev_mode", return_value=False)
    @patch("posthog.ducklake.common.ensure_ducklake_catalog")
    @patch("posthog.ducklake.common.duckdb")
    def test_raises_in_production_mode(
        self,
        mock_duckdb: MagicMock,
        mock_ensure: MagicMock,
        _mock_dev: MagicMock,
    ):
        mock_conn = MagicMock()
        mock_duckdb.connect.return_value = mock_conn
        mock_duckdb.NotImplementedException = duckdb.NotImplementedException
        mock_duckdb.InvalidInputException = duckdb.InvalidInputException
        mock_duckdb.CatalogException = duckdb.CatalogException

        version_exc = duckdb.NotImplementedException(
            "DuckLake catalog version mismatch: catalog version is 0.3, but the extension requires version 0.4"
        )

        with patch("posthog.ducklake.common.attach_catalog", side_effect=version_exc):
            with pytest.raises(duckdb.NotImplementedException):
                initialize_ducklake(TEST_CONFIG)

    @patch("posthog.ducklake.common.is_dev_mode", return_value=True)
    @patch("posthog.ducklake.common.ensure_ducklake_catalog")
    @patch("posthog.ducklake.common.duckdb")
    def test_raises_for_non_version_error_dev_mode(
        self,
        mock_duckdb: MagicMock,
        mock_ensure: MagicMock,
        _mock_dev: MagicMock,
    ):
        mock_conn = MagicMock()
        mock_duckdb.connect.return_value = mock_conn
        mock_duckdb.NotImplementedException = duckdb.NotImplementedException
        mock_duckdb.InvalidInputException = duckdb.InvalidInputException
        mock_duckdb.CatalogException = duckdb.CatalogException

        unrelated_exc = duckdb.NotImplementedException("COPY FROM is not supported")

        with patch("posthog.ducklake.common.attach_catalog", side_effect=unrelated_exc):
            with pytest.raises(duckdb.NotImplementedException, match="COPY FROM"):
                initialize_ducklake(TEST_CONFIG)

    @patch.dict("os.environ", {"POSTHOG_ALLOW_DUCKLAKE_CATALOG_RESET": "1"}, clear=True)
    @patch("posthog.ducklake.common.is_dev_mode", return_value=True)
    @patch("posthog.ducklake.common.reset_ducklake_catalog")
    @patch("posthog.ducklake.common.run_smoke_check")
    @patch("posthog.ducklake.common.ensure_ducklake_catalog")
    @patch("posthog.ducklake.common.duckdb")
    def test_auto_resets_on_invalid_input_exception(
        self,
        mock_duckdb: MagicMock,
        mock_ensure: MagicMock,
        mock_smoke: MagicMock,
        mock_reset: MagicMock,
        _mock_dev: MagicMock,
    ):
        mock_conn = MagicMock()
        fresh_conn = MagicMock()
        mock_duckdb.connect.side_effect = [mock_conn, fresh_conn]
        mock_duckdb.NotImplementedException = duckdb.NotImplementedException
        mock_duckdb.InvalidInputException = duckdb.InvalidInputException
        mock_duckdb.CatalogException = duckdb.CatalogException

        version_exc = duckdb.InvalidInputException(
            "DuckLake catalog version mismatch: catalog version is 0.3, but the extension requires version 0.4"
        )

        def attach_side_effect(conn, config, alias="ducklake"):
            if conn is mock_conn:
                raise version_exc

        with patch("posthog.ducklake.common.attach_catalog", side_effect=attach_side_effect):
            result = initialize_ducklake(TEST_CONFIG)

        assert result is True
        mock_reset.assert_called_once_with(TEST_CONFIG)
