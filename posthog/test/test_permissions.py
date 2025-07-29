from unittest.mock import Mock
from rest_framework.test import APIRequestFactory

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.permissions import AccessControlPermission
from posthog.rbac.user_access_control import UserAccessControl
from posthog.test.base import BaseTest

try:
    from ee.models.rbac.access_control import AccessControl
    from ee.models.rbac.role import Role, RoleMembership
except ImportError:
    pass


class TestAccessControlPermission(BaseTest):
    """
    Test the AccessControlPermission class to ensure it properly handles
    specific object access when users have "none" resource access.
    """

    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ADVANCED_PERMISSIONS,
                "name": AvailableFeature.ADVANCED_PERMISSIONS,
            },
            {
                "key": AvailableFeature.ROLE_BASED_ACCESS,
                "name": AvailableFeature.ROLE_BASED_ACCESS,
            },
        ]
        self.organization.save()

        self.role = Role.objects.create(name="Test Role", organization=self.organization)
        RoleMembership.objects.create(user=self.user, role=self.role)

        self.factory = APIRequestFactory()
        self.permission = AccessControlPermission()

        self.other_user = self._create_user("other_user")

        # Create test notebooks
        from posthog.models.notebook.notebook import Notebook

        self.notebook_1 = Notebook.objects.create(team=self.team, created_by=self.other_user, title="Notebook 1")
        self.notebook_2 = Notebook.objects.create(team=self.team, created_by=self.other_user, title="Notebook 2")

    def _create_access_control(
        self, resource="notebook", resource_id=None, access_level="editor", organization_member=None, role=None
    ):
        """Helper to create access control entries"""
        ac, _ = AccessControl.objects.get_or_create(
            team=self.team,
            resource=resource,
            resource_id=resource_id,
            organization_member=organization_member,
            role=role,
        )
        ac.access_level = access_level
        ac.save()
        return ac

    def _create_real_view(self, action="list", pk=None):
        """Helper to create a real NotebookViewSet instance"""
        from posthog.api.notebook import NotebookViewSet

        view = NotebookViewSet()
        view.action = action
        view.kwargs = {"pk": pk} if pk else {}
        view.team = self.team
        view.user_access_control = UserAccessControl(self.user, self.team)
        view.request = Mock()
        view.request.user = self.user
        return view

    def _create_mock_request(self, method="GET", user=None):
        """Helper to create a mock request"""
        if user is None:
            user = self.user

        request = self.factory.get("/") if method == "GET" else self.factory.post("/")
        request.user = user
        request.successful_authenticator = Mock()
        request.successful_authenticator.__class__.__name__ = "SessionAuthentication"
        return request

    def test_has_permission_with_resource_access(self):
        """Test API permission when user has resource-level access"""
        # Give user resource-level access to notebooks
        self._create_access_control(
            resource="notebook",
            access_level="editor",
            organization_member=OrganizationMembership.objects.get(user=self.user, organization=self.organization),
        )

        request = self._create_mock_request()
        view = self._create_real_view(action="list")

        # Should have permission
        assert self.permission.has_permission(request, view) is True

    def test_has_permission_with_none_resource_but_specific_access(self):
        """Test API permission when user has 'none' resource access but specific object access"""
        # Set resource-level access to "none"
        self._create_access_control(resource="notebook", access_level="none")

        # Give specific access to notebook_1
        self._create_access_control(
            resource="notebook",
            resource_id=str(self.notebook_1.id),
            access_level="editor",
            organization_member=OrganizationMembership.objects.get(user=self.user, organization=self.organization),
        )

        request = self._create_mock_request()
        view = self._create_real_view(action="list")

        # Should have permission due to specific access fallback
        assert self.permission.has_permission(request, view) is True

    def test_has_permission_with_none_resource_and_no_specific_access(self):
        """Test API permission when user has 'none' resource access and no specific access"""
        # Set resource-level access to "none"
        self._create_access_control(resource="notebook", access_level="none")

        request = self._create_mock_request()
        view = self._create_real_view(action="list")

        # Should NOT have permission
        assert self.permission.has_permission(request, view) is False

    def test_has_object_permission_with_specific_access(self):
        """Test object-level permission when user has specific access to the object"""
        # Set resource-level access to "none"
        self._create_access_control(resource="notebook", access_level="none")

        # Give specific access to notebook_1
        self._create_access_control(
            resource="notebook",
            resource_id=str(self.notebook_1.id),
            access_level="editor",
            organization_member=OrganizationMembership.objects.get(user=self.user, organization=self.organization),
        )

        request = self._create_mock_request()
        view = self._create_real_view(action="retrieve", pk=str(self.notebook_1.id))

        # Should have object permission for notebook_1
        assert self.permission.has_object_permission(request, view, self.notebook_1) is True

    def test_has_object_permission_without_specific_access(self):
        """Test object-level permission when user lacks specific access to the object"""
        # Set resource-level access to "none"
        self._create_access_control(resource="notebook", access_level="none")

        request = self._create_mock_request()
        view = self._create_real_view(action="retrieve", pk=str(self.notebook_2.id))

        # Should NOT have object permission for notebook_2
        assert self.permission.has_object_permission(request, view, self.notebook_2) is False

    def test_has_permission_for_create_action_with_none_resource_access(self):
        """Test that create actions are blocked when user has 'none' resource access"""
        # Set resource-level access to "none"
        self._create_access_control(resource="notebook", access_level="none")

        # Give specific access to notebook_1 (shouldn't matter for creation)
        self._create_access_control(
            resource="notebook",
            resource_id=str(self.notebook_1.id),
            access_level="editor",
            organization_member=OrganizationMembership.objects.get(user=self.user, organization=self.organization),
        )

        request = self._create_mock_request(method="POST")
        view = self._create_real_view(action="create")

        # Should NOT have permission to create (resource-level check should fail)
        assert self.permission.has_permission(request, view) is False

    def test_has_permission_for_create_action_with_resource_access(self):
        """Test that create actions work when user has resource-level access"""
        # Give user resource-level access to notebooks
        self._create_access_control(
            resource="notebook",
            access_level="editor",
            organization_member=OrganizationMembership.objects.get(user=self.user, organization=self.organization),
        )

        request = self._create_mock_request(method="POST")
        view = self._create_real_view(action="create")

        # Should have permission to create
        assert self.permission.has_permission(request, view) is True
