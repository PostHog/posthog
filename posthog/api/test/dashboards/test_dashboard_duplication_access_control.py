import pytest
from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.api.test.dashboards import DashboardAPI
from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


@pytest.mark.ee
class TestDashboardDuplicationAccessControl(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()

        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)
        self.dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "secret"})
        self.dashboard_api.create_insight({"dashboards": [self.dashboard_id], "name": "confidential"})

        self.member = User.objects.create_and_join(self.organization, "member@posthog.com", "testtest")

    def _set_member_access(self, access_level: str) -> None:
        membership = OrganizationMembership.objects.get(user=self.member, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id=str(self.dashboard_id),
            access_level=access_level,
            organization_member=membership,
        )

    def _duplicate(self) -> int:
        return self.client.post(
            f"/api/projects/{self.team.id}/dashboards/",
            {"name": "copy", "use_dashboard": self.dashboard_id, "duplicate_tiles": True},
        ).status_code

    def test_member_denied_source_dashboard_cannot_duplicate_it(self) -> None:
        self._set_member_access("none")
        self.client.force_login(self.member)

        retrieve_status = self.client.get(f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/").status_code
        assert retrieve_status == status.HTTP_403_FORBIDDEN

        # Duplication must not become a back door around the denied retrieve.
        assert self._duplicate() == status.HTTP_403_FORBIDDEN

    def test_member_with_viewer_access_can_duplicate(self) -> None:
        self._set_member_access("viewer")
        self.client.force_login(self.member)

        assert self._duplicate() == status.HTTP_201_CREATED
