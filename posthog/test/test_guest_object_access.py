from collections.abc import Sequence

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership

from products.authz.backend.facade.contracts import CheckRequest, Context, ResourceIds
from products.authz.backend.facade.enums import Action, ResourceType
from products.dashboards.backend.facade import testing as dashboard_testing
from products.notebooks.backend.models import Notebook


class TestGuestObjectAccess(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": "Advanced permissions"}
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.GUEST
        self.organization_membership.save()
        self.granted = Notebook.objects.create(team=self.team, title="Granted")
        self.hidden = Notebook.objects.create(team=self.team, title="Hidden")
        self.dashboard_id = dashboard_testing.create_dashboard(team_id=self.team.id)
        for target, kwargs in (
            ("products.authz.backend.logic.rollout.get_feature_flag_or_none", {"return_value": "v2"}),
            ("products.authz.backend.logic.authorization.check", {"side_effect": self._openfga_check}),
            (
                "products.authz.backend.logic.authorization.list_resources",
                {"return_value": ResourceIds(ids=frozenset({str(self.granted.id)}), complete=True)},
            ),
        ):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _openfga_check(self, requests: Sequence[CheckRequest], _context: Context | None) -> list[bool]:
        granted = {(ResourceType.NOTEBOOK, str(self.granted.id)), (ResourceType.DASHBOARD, str(self.dashboard_id))}
        return [
            request.resource.type in (ResourceType.PROJECT, ResourceType.ORGANIZATION)
            or (request.action == Action.VIEW and (request.resource.type, request.resource.id) in granted)
            for request in requests
        ]

    def test_guest_lists_only_granted_notebooks(self) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/notebooks/")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [item["short_id"] for item in response.json()["results"]] == [self.granted.short_id]

    def test_guest_reads_a_granted_notebook_and_not_another(self) -> None:
        granted = self.client.get(f"/api/projects/{self.team.id}/notebooks/{self.granted.short_id}/")
        hidden = self.client.get(f"/api/projects/{self.team.id}/notebooks/{self.hidden.short_id}/")
        assert granted.status_code == status.HTTP_200_OK, granted.json()
        assert hidden.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND), hidden.json()

    def test_guest_cannot_edit_a_granted_dashboard(self) -> None:
        url = f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/"
        assert self.client.get(url).status_code == status.HTTP_200_OK
        assert self.client.patch(url, {"name": "Changed"}).status_code == status.HTTP_403_FORBIDDEN
