import pytest
from unittest.mock import MagicMock, patch

import duckdb
from parameterized import parameterized

from posthog.ducklake.common import (
    DucklingBackfillEnableError,
    enable_team_backfill,
    get_team_backfill_state,
    initialize_ducklake,
    is_version_mismatch,
    reset_ducklake_catalog,
    upsert_duckgres_server_for_org,
)
from posthog.ducklake.models import DuckgresServer, DuckgresServerTeam
from posthog.models import Organization, Team


@pytest.mark.django_db
class TestUpsertDuckgresServerForOrg:
    def test_creates_then_updates_a_single_row(self):
        org = Organization.objects.create(name="Test Org")

        created = upsert_duckgres_server_for_org(
            org.id, host="wh.dw.us.postwh.com", port=5432, database="ducklake", username="root", password="pw1"
        )
        assert DuckgresServer.objects.filter(organization_id=org.id).count() == 1
        assert created.host == "wh.dw.us.postwh.com"
        assert created.password == "pw1"

        updated = upsert_duckgres_server_for_org(
            org.id, host="wh2.dw.us.postwh.com", port=6543, database="ducklake", username="root", password="pw2"
        )
        assert DuckgresServer.objects.filter(organization_id=org.id).count() == 1
        assert updated.pk == created.pk
        assert updated.host == "wh2.dw.us.postwh.com"
        assert updated.port == 6543
        assert updated.password == "pw2"


@pytest.mark.django_db
class TestEnableTeamBackfill:
    def _server(self, org: Organization) -> DuckgresServer:
        return DuckgresServer.objects.create(
            organization=org, host="h", port=5432, database="ducklake", username="root", password="x"
        )

    def test_creates_membership_and_suffixed_backfill(self):
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        server = self._server(org)

        suffix = enable_team_backfill(team_id=team.id, organization_id=org.id, table_name="my_prod_env")

        assert suffix == "my_prod_env"
        link = DuckgresServerTeam.objects.get(team_id=team.id)
        assert link.server_id == server.id
        assert link.backfill_enabled is True
        assert link.table_suffix == "my_prod_env"

    def test_rejects_an_invalid_table_name(self):
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        self._server(org)

        with pytest.raises(DucklingBackfillEnableError):
            enable_team_backfill(team_id=team.id, organization_id=org.id, table_name="Bad Name!")

    def test_rejects_duplicate_suffix_within_org(self):
        org = Organization.objects.create(name="Org")
        team_a = Team.objects.create(organization=org)
        team_b = Team.objects.create(organization=org)
        server = self._server(org)
        DuckgresServerTeam.objects.create(server=server, team=team_a, table_suffix="shared")

        with pytest.raises(DucklingBackfillEnableError):
            enable_team_backfill(team_id=team_b.id, organization_id=org.id, table_name="shared")

    def test_same_name_is_idempotent(self):
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        self._server(org)

        enable_team_backfill(team_id=team.id, organization_id=org.id, table_name="prod")
        suffix = enable_team_backfill(team_id=team.id, organization_id=org.id, table_name="prod")

        assert suffix == "prod"
        assert DuckgresServerTeam.objects.filter(team_id=team.id).count() == 1

    def test_refuses_to_change_a_set_suffix(self):
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        self._server(org)
        enable_team_backfill(team_id=team.id, organization_id=org.id, table_name="first")

        with pytest.raises(DucklingBackfillEnableError):
            enable_team_backfill(team_id=team.id, organization_id=org.id, table_name="second")
        assert DuckgresServerTeam.objects.get(team_id=team.id).table_suffix == "first"

    def test_refuses_to_set_a_suffix_on_a_legacy_shared_team(self):
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        server = self._server(org)
        DuckgresServerTeam.objects.create(server=server, team=team, backfill_enabled=True, table_suffix=None)

        with pytest.raises(DucklingBackfillEnableError):
            enable_team_backfill(team_id=team.id, organization_id=org.id, table_name="new_name")
        assert DuckgresServerTeam.objects.get(team_id=team.id).table_suffix is None

    def test_requires_a_provisioned_server(self):
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)

        with pytest.raises(DucklingBackfillEnableError):
            enable_team_backfill(team_id=team.id, organization_id=org.id, table_name="events")


@pytest.mark.django_db
class TestGetTeamBackfillState:
    def _server_team(self, table_suffix: str | None) -> Team:
        org = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=org)
        server = DuckgresServer.objects.create(
            organization=org, host="h", port=5432, database="ducklake", username="root", password="x"
        )
        DuckgresServerTeam.objects.create(server=server, team=team, table_suffix=table_suffix)
        return team

    def test_no_backfill(self):
        team = Team.objects.create(organization=Organization.objects.create(name="Org"))

        assert get_team_backfill_state(team.id) == {"has_backfill": False, "table_suffix": None}

    def test_legacy_shared_backfill(self):
        team = self._server_team(table_suffix=None)

        assert get_team_backfill_state(team.id) == {"has_backfill": True, "table_suffix": None}

    def test_suffixed_backfill(self):
        team = self._server_team(table_suffix="prod")

        assert get_team_backfill_state(team.id) == {"has_backfill": True, "table_suffix": "prod"}


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


class TestValidateDuckgresIdentifier:
    @parameterized.expand(["prod", "us_prod", "team_42", "abc123"])
    def test_accepts_safe_identifiers(self, ident):
        from posthog.ducklake.common import validate_duckgres_identifier

        validate_duckgres_identifier(ident)  # no raise

    @parameterized.expand(["", "a-b", "a b", "a;drop", "a.b", "a$b", '"x"'])
    def test_rejects_unsafe_identifiers(self, ident):
        from posthog.ducklake.common import validate_duckgres_identifier

        with pytest.raises(ValueError):
            validate_duckgres_identifier(ident)


@pytest.mark.django_db
class TestDuckgresDataImportsSchema:
    def _team(self):
        from posthog.models import Organization, Team

        org = Organization.objects.create(name="o")
        return Team.objects.create(organization=org, name="t")

    def _server_team(self, team: Team, table_suffix: str | None) -> DuckgresServerTeam:
        server = DuckgresServer.objects.create(
            organization_id=team.organization_id,
            host="h",
            port=5432,
            database="ducklake",
            username="root",
            password="x",
        )
        return DuckgresServerTeam.objects.create(server=server, team=team, table_suffix=table_suffix)

    def test_falls_back_to_team_id_when_no_backfill_row(self):
        from posthog.ducklake.common import duckgres_data_imports_schema

        team = self._team()
        assert duckgres_data_imports_schema(team.id) == f"posthog_data_imports_team_{team.id}"

    def test_falls_back_to_team_id_when_suffix_null_or_empty(self):
        from posthog.ducklake.common import duckgres_data_imports_schema

        team = self._team()
        link = self._server_team(team, table_suffix=None)
        assert duckgres_data_imports_schema(team.id) == f"posthog_data_imports_team_{team.id}"
        DuckgresServerTeam.objects.filter(pk=link.pk).update(table_suffix="")
        assert duckgres_data_imports_schema(team.id) == f"posthog_data_imports_team_{team.id}"

    def test_uses_suffix_when_set(self):
        from posthog.ducklake.common import duckgres_data_imports_schema

        team = self._team()
        self._server_team(team, table_suffix="us_prod")
        assert duckgres_data_imports_schema(team.id) == "posthog_data_imports_us_prod"

    def test_rejects_unsafe_suffix(self):
        from posthog.ducklake.common import duckgres_data_imports_schema

        team = self._team()
        self._server_team(team, table_suffix="a;drop")
        with pytest.raises(ValueError):
            duckgres_data_imports_schema(team.id)
