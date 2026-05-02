"""Shared fixtures for warehouse access-control tests.

Saved-query, folder, and table test classes all need the same org-feature
enablement, the same test users at different access levels, and the same
helpers for creating `AccessControl` rows. Centralizing them here avoids
duplicating ~15 lines across three test files.
"""

from posthog.test.base import APIBaseTest

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


class WarehouseAccessControlTestMixin(APIBaseTest):
    """Base test case that enables RBAC features and creates standard test users.

    Subclasses should set `resource` to `"warehouse_view"` or `"warehouse_table"`.
    """

    resource: str = "warehouse_view"

    def setUp(self):
        super().setUp()

        self.organization.available_product_features = [
            {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": AvailableFeature.ADVANCED_PERMISSIONS},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

        self.viewer_user = User.objects.create_and_join(self.organization, "viewer@posthog.com", "testtest")
        self.editor_user = User.objects.create_and_join(self.organization, "editor@posthog.com", "testtest")
        self.no_access_user = User.objects.create_and_join(self.organization, "noaccess@posthog.com", "testtest")

    def _create_access_control(self, user, resource=None, resource_id=None, access_level="viewer"):
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        return AccessControl.objects.create(
            team=self.team,
            resource=resource or self.resource,
            resource_id=resource_id,
            access_level=access_level,
            organization_member=membership,
        )

    def _create_project_default(self, resource=None, access_level="none"):
        return AccessControl.objects.create(
            team=self.team,
            resource=resource or self.resource,
            resource_id=None,
            access_level=access_level,
            organization_member=None,
            role=None,
        )
