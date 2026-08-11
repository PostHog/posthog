from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.hogql.direct_connection import get_direct_connection_source, raw_query_denied_by_table_access

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership

from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

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
