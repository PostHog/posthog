from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models import OrganizationMembership, Team, User
from posthog.models.organization import AvailableFeature
from posthog.models.scoping import team_scope

from products.customer_analytics.backend.models import FeatureRequest, FeatureRequestProductArea
from products.customer_analytics.backend.test.factories import create_account

from ee.models.rbac.access_control import AccessControl


class TestFeatureRequestsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self.flag_patcher = patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True)
        self.flag_patcher.start()
        self.addCleanup(self.flag_patcher.stop)
        self.account = create_account(team_id=self.team.id, name="Acme")
        self.area_one = FeatureRequestProductArea.objects.for_team(self.team.id).create(
            team=self.team,
            name="Product analytics",
            display_order=1,
            created_by_id=self.user.id,
            updated_by_id=self.user.id,
        )
        self.area_two = FeatureRequestProductArea.objects.for_team(self.team.id).create(
            team=self.team,
            name="Session replay",
            display_order=2,
            created_by_id=self.user.id,
            updated_by_id=self.user.id,
        )
        self.requests_url = f"/api/projects/{self.team.id}/feature_requests/"
        self.product_areas_url = f"/api/projects/{self.team.id}/feature_request_product_areas/"

    def _payload(self) -> dict[str, object]:
        return {
            "title": "Export account-level retention data",
            "description": "The customer needs this for their monthly reporting workflow.",
            "account_id": str(self.account.id),
            "product_area_ids": [str(self.area_one.id), str(self.area_two.id)],
            "idempotency_key": str(uuid4()),
        }

    def _set_access_level(self, user: User, access_level: str) -> None:
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="customer_analytics",
            resource_id=None,
            access_level=access_level,
            organization_member=membership,
        )

    def test_editor_can_create_and_view_a_request_with_multiple_product_areas_idempotently(self) -> None:
        payload = self._payload()

        created = self.client.post(self.requests_url, payload, format="json")
        repeated = self.client.post(self.requests_url, payload, format="json")
        listed = self.client.get(self.requests_url)
        retrieved = self.client.get(f"{self.requests_url}{created.json()['id']}/")

        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(repeated.status_code, status.HTTP_200_OK)
        self.assertEqual(repeated.json()["id"], created.json()["id"])
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertEqual(listed.json()["count"], 1)
        self.assertEqual(retrieved.status_code, status.HTTP_200_OK)
        self.assertEqual(retrieved.json()["account"]["name"], "Acme")
        self.assertEqual(
            {area["name"] for area in retrieved.json()["product_areas"]},
            {"Product analytics", "Session replay"},
        )
        self.assertEqual(retrieved.json()["request_status"], "requested")
        self.assertEqual(FeatureRequest.objects.for_team(self.team.id).count(), 1)

    def test_create_rejects_relations_from_another_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        with team_scope(other_team.id):
            other_account = create_account(team_id=other_team.id, name="Other account")
            other_area = FeatureRequestProductArea.objects.for_team(other_team.id).create(
                team=other_team,
                name="Other area",
            )
        payload = self._payload()
        payload["account_id"] = str(other_account.id)
        payload["product_area_ids"] = [str(other_area.id)]

        response = self.client.post(self.requests_url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(FeatureRequest.objects.for_team(self.team.id).count(), 0)

    def test_idempotency_retry_does_not_expose_a_request_for_an_inaccessible_account(self) -> None:
        payload = self._payload()
        created = self.client.post(self.requests_url, payload, format="json").json()
        restricted_editor = User.objects.create_and_join(
            self.organization,
            "restricted-feature-request-editor@example.com",
            "testtest",
        )
        self._set_access_level(restricted_editor, "editor")
        membership = OrganizationMembership.objects.get(user=restricted_editor, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="account",
            resource_id=str(self.account.id),
            access_level="none",
            organization_member=membership,
        )
        self.client.force_login(restricted_editor)

        listed = self.client.get(self.requests_url)
        retrieved = self.client.get(f"{self.requests_url}{created['id']}/")
        response = self.client.post(self.requests_url, payload, format="json")

        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertEqual(listed.json()["count"], 0)
        self.assertEqual(retrieved.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn("Export account-level retention data", str(response.json()))

    def test_viewer_can_read_but_cannot_create(self) -> None:
        payload = self._payload()
        created = self.client.post(self.requests_url, payload, format="json").json()
        viewer = User.objects.create_and_join(self.organization, "feature-request-viewer@example.com", "testtest")
        self._set_access_level(viewer, "viewer")
        self.client.force_login(viewer)

        listed = self.client.get(self.requests_url)
        retrieved = self.client.get(f"{self.requests_url}{created['id']}/")
        create_attempt = self.client.post(self.requests_url, self._payload(), format="json")

        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertEqual(retrieved.status_code, status.HTTP_200_OK)
        self.assertEqual(create_attempt.status_code, status.HTTP_403_FORBIDDEN)

    def test_feature_flag_blocks_the_api_without_deleting_data(self) -> None:
        created = self.client.post(self.requests_url, self._payload(), format="json")

        with patch("posthog.permissions.posthog_feature_flag_enabled", return_value=False):
            blocked = self.client.get(self.requests_url)

        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(blocked.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(FeatureRequest.objects.for_team(self.team.id).count(), 1)

    def test_product_area_list_rejects_invalid_include_inactive(self) -> None:
        response = self.client.get(self.product_areas_url, {"include_inactive": "sometimes"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_only_manager_can_create_and_update_product_areas(self) -> None:
        editor = User.objects.create_and_join(self.organization, "feature-request-editor@example.com", "testtest")
        self._set_access_level(editor, "editor")
        self.client.force_login(editor)
        denied = self.client.post(self.product_areas_url, {"name": "Surveys"}, format="json")

        manager = User.objects.create_and_join(self.organization, "feature-request-manager@example.com", "testtest")
        self._set_access_level(manager, "manager")
        self.client.force_login(manager)
        created = self.client.post(self.product_areas_url, {"name": "Surveys", "display_order": 3}, format="json")
        updated = self.client.patch(
            f"{self.product_areas_url}{created.json()['id']}/",
            {"name": "User surveys", "is_active": False},
            format="json",
        )

        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(updated.status_code, status.HTTP_200_OK)
        self.assertEqual(updated.json()["name"], "User surveys")
        self.assertFalse(updated.json()["is_active"])
