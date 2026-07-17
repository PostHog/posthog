from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.hogql.direct_connection import get_direct_connection_source

from posthog.models.sharing_configuration import SharingConfiguration
from posthog.shared_link_user import SharedLinkUser
from posthog.synthetic_user import SyntheticUser

from products.warehouse_sources.backend.facade.models import ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType


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

    @parameterized.expand(
        [
            ("shared_link_user", lambda self: SharedLinkUser(self._enabled_sharing_configuration())),
            ("synthetic_user", lambda self: SyntheticUser(self.team, "svc-token")),
        ]
    )
    def test_non_user_principal_resolves_source_without_error(self, _name, make_user):
        # A non-user principal (shared-link viewer, service token) has no RBAC identity; filtering
        # AccessControl by its non-integer id used to raise TypeError and fail the query closed.
        # These principals bypass warehouse access control by design, so the source must resolve.
        source = self._create_source(access_method=ExternalDataSource.AccessMethod.DIRECT)

        resolved = get_direct_connection_source(self.team, str(source.id), user=make_user(self))

        assert resolved is not None
        self.assertEqual(resolved.id, source.id)

    def _enabled_sharing_configuration(self) -> SharingConfiguration:
        return SharingConfiguration.objects.create(team=self.team, enabled=True)
