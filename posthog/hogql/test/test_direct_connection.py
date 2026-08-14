from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.hogql.direct_connection import (
    RAW_QUERY_TABLE_DENIED_ERROR,
    get_direct_connection_source,
    raw_query_denied_by_table_access,
)
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.query import HogQLQueryExecutor

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Team

from products.warehouse_sources.backend.facade.models import (
    MANAGED_WAREHOUSE_SOURCE_PREFIX,
    DataWarehouseTable,
    ExternalDataSource,
)
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
from products.warehouse_sources.backend.models.external_data_source import (
    get_direct_external_data_source_for_connection,
)

from ee.models import AccessControl


class TestGetDirectConnectionSource(APIBaseTest):
    def _create_source(self, *, access_method: str, direct_query_enabled: bool = True) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=access_method,
            direct_query_enabled=direct_query_enabled,
            job_inputs={"host": "h", "port": "5432", "database": "d", "user": "u", "password": "p", "schema": "public"},
        )

    def _create_managed_source(self, **overrides: object) -> ExternalDataSource:
        source_team = overrides.get("team")
        if not isinstance(source_team, Team):
            source_team = self.team
        fields: dict[str, object] = {
            "team": source_team,
            "source_type": ExternalDataSourceType.POSTGRES,
            "access_method": ExternalDataSource.AccessMethod.DIRECT,
            "direct_query_enabled": True,
            "prefix": MANAGED_WAREHOUSE_SOURCE_PREFIX,
            "connection_metadata": {
                "engine": "duckdb",
                "system_managed": True,
                "credential_kind": "project_reader",
                "reader_configured": True,
            },
            "job_inputs": {
                "host": "h",
                "port": "5432",
                "database": "d",
                "user": f"posthog_team_{source_team.id}",
                "password": "p",
                "schema": "public",
            },
        }
        fields.update(overrides)
        return ExternalDataSource.objects.create(**fields)

    def test_require_pure_direct_rejects_synced_warehouse_source(self):
        # A synced source only exposes its `should_sync` catalog through the HogQL-compiled path —
        # raw SQL has no such projection, so it must not resolve a connection for it.
        source = self._create_source(access_method=ExternalDataSource.AccessMethod.WAREHOUSE)

        resolved = get_direct_connection_source(self.team, str(source.id), require_pure_direct=True)

        self.assertIsNone(resolved)

    def test_require_pure_direct_allows_pure_direct_source(self):
        source = self._create_source(access_method=ExternalDataSource.AccessMethod.DIRECT)

        resolved = get_direct_connection_source(self.team, str(source.id), require_pure_direct=True)

        assert resolved is not None
        self.assertEqual(resolved.id, source.id)

    def test_default_allows_synced_warehouse_source(self):
        # The HogQL-compiled path (used by everything except sendRawQuery) is unaffected.
        source = self._create_source(access_method=ExternalDataSource.AccessMethod.WAREHOUSE)

        resolved = get_direct_connection_source(self.team, str(source.id))

        assert resolved is not None
        self.assertEqual(resolved.id, source.id)

    def test_managed_warehouse_ignores_external_source_access_control(self):
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save()

        external_source = self._create_source(access_method=ExternalDataSource.AccessMethod.DIRECT)
        managed_source = self._create_managed_source()
        AccessControl.objects.create(
            team=self.team,
            resource="external_data_source",
            access_level="none",
        )
        self.assertIsNone(get_direct_connection_source(self.team, str(external_source.id), user=self.user))
        resolved = get_direct_connection_source(self.team, str(managed_source.id), user=self.user)

        assert resolved is not None
        self.assertEqual(resolved.id, managed_source.id)

    def test_managed_warehouse_resolves_from_durable_project_reader_readiness(self):
        source = self._create_managed_source()

        self.assertEqual(get_direct_connection_source(self.team, str(source.id)), source)
        self.assertEqual(get_direct_external_data_source_for_connection(self.team.id, str(source.id)), source)

    @parameterized.expand(
        [
            ("direct_query_disabled", {"direct_query_enabled": False}),
            (
                "reader_pending",
                {
                    "connection_metadata": {
                        "engine": "duckdb",
                        "system_managed": True,
                        "credential_kind": "project_reader",
                        "reader_configured": False,
                    }
                },
            ),
            (
                "legacy_org_root",
                {
                    "connection_metadata": {
                        "engine": "duckdb",
                        "system_managed": True,
                        "credential_kind": "org_root",
                        "reader_configured": True,
                    }
                },
            ),
            (
                "stored_server_login",
                {
                    "connection_metadata": {
                        "engine": "duckdb",
                        "system_managed": True,
                        "credential_kind": "stored_server_login",
                        "reader_configured": True,
                    }
                },
            ),
            (
                "malformed_identity",
                {
                    "connection_metadata": {
                        "engine": "duckdb",
                        "credential_kind": "project_reader",
                        "reader_configured": True,
                    }
                },
            ),
            (
                "spoofed_root_username",
                {
                    "job_inputs": {
                        "host": "h",
                        "port": 5432,
                        "database": "d",
                        "user": "root",
                        "password": "p",
                    }
                },
            ),
            (
                "malformed_credentials",
                {
                    "job_inputs": {
                        "host": "",
                        "port": 70000,
                        "database": "d",
                        "user": "posthog_team_invalid",
                        "password": "",
                    }
                },
            ),
        ]
    )
    def test_managed_warehouse_fails_closed_until_project_reader_is_ready(
        self, _name: str, overrides: dict[str, object]
    ) -> None:
        source = self._create_managed_source(**overrides)

        self.assertIsNone(get_direct_connection_source(self.team, str(source.id)))
        self.assertIsNone(get_direct_external_data_source_for_connection(self.team.id, str(source.id)))

    def test_managed_warehouse_resolution_rejects_deleted_and_cross_team_sources(self) -> None:
        deleted_source = self._create_managed_source(deleted=True)
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        cross_team_source = self._create_managed_source(team=other_team)

        for source in (deleted_source, cross_team_source):
            self.assertIsNone(get_direct_connection_source(self.team, str(source.id)))
            self.assertIsNone(get_direct_external_data_source_for_connection(self.team.id, str(source.id)))


class TestRawQueryTableAccess(APIBaseTest):
    def _create_source(self) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            direct_query_enabled=True,
            job_inputs={"host": "h", "port": "5432", "database": "d", "user": "u", "password": "p", "schema": "public"},
        )

    def _create_table(self, source: ExternalDataSource, name: str = "orders") -> DataWarehouseTable:
        return DataWarehouseTable.objects.create(
            name=name,
            format="Parquet",
            team=self.team,
            external_data_source=source,
            url_pattern="",
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True}},
        )

    def _enable_access_control(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save()

    def _deny_table(self, table: DataWarehouseTable) -> None:
        AccessControl.objects.create(
            team=self.team, resource="warehouse_table", resource_id=str(table.id), access_level="none"
        )

    def test_denies_raw_query_when_user_cannot_read_a_table(self):
        # The security gap this guards: raw SQL is opaque, so a member denied one table could otherwise
        # read it with sendRawQuery, bypassing the per-table check the HogQL path enforces.
        self._enable_access_control()
        source = self._create_source()
        table = self._create_table(source)
        self._deny_table(table)

        with patch("posthog.hogql.direct_connection.feature_enabled_or_false", return_value=True):
            assert raw_query_denied_by_table_access(self.team, source, user=self.user) is True

    @patch("posthog.hogql.direct_sql.postgres_adapter.psycopg.connect")
    def test_denies_external_raw_query_before_connecting(self, connect: MagicMock) -> None:
        self._enable_access_control()
        source = self._create_source()
        table = self._create_table(source)
        self._deny_table(table)

        with (
            patch("posthog.hogql.direct_connection.feature_enabled_or_false", return_value=True),
            self.assertRaisesMessage(ExposedHogQLError, RAW_QUERY_TABLE_DENIED_ERROR),
        ):
            HogQLQueryExecutor(
                query="SELECT * FROM orders",
                team=self.team,
                user=self.user,
                connection_id=str(source.id),
                send_raw_query=True,
            ).execute()

        connect.assert_not_called()

    def test_allows_raw_query_when_user_can_read_all_tables(self):
        self._enable_access_control()
        source = self._create_source()
        self._create_table(source)

        with patch("posthog.hogql.direct_connection.feature_enabled_or_false", return_value=True):
            assert raw_query_denied_by_table_access(self.team, source, user=self.user) is False

    def test_allows_raw_query_when_access_control_feature_disabled(self):
        # Gating mirrors the HogQL build: with the flag off, no per-table control applies, so a denial
        # must not spill over into refusing raw mode.
        self._enable_access_control()
        source = self._create_source()
        table = self._create_table(source)
        self._deny_table(table)

        with patch("posthog.hogql.direct_connection.feature_enabled_or_false", return_value=False):
            assert raw_query_denied_by_table_access(self.team, source, user=self.user) is False

    def test_fails_closed_without_a_user(self):
        source = self._create_source()
        self._create_table(source)

        with patch("posthog.hogql.direct_connection.feature_enabled_or_false", return_value=True):
            assert raw_query_denied_by_table_access(self.team, source, user=None) is True
