from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models import OrganizationMembership, Team, User
from posthog.models.organization import AvailableFeature
from posthog.models.scoping import team_scope

from products.customer_analytics.backend.models import FeatureRequest, FeatureRequestHistory, FeatureRequestProductArea
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
        history = self.client.get(f"{self.requests_url}{created['id']}/history/")
        response = self.client.post(self.requests_url, payload, format="json")

        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertEqual(listed.json()["count"], 0)
        self.assertEqual(retrieved.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(history.status_code, status.HTTP_404_NOT_FOUND)
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
        update_attempt = self.client.patch(
            f"{self.requests_url}{created['id']}/",
            {"expected_version": created["version"], "request_status": "planned"},
            format="json",
        )
        archive_attempt = self.client.post(
            f"{self.requests_url}{created['id']}/archive/",
            {"expected_version": created["version"]},
            format="json",
        )

        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertEqual(retrieved.status_code, status.HTTP_200_OK)
        self.assertEqual(create_attempt.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(update_attempt.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(archive_attempt.status_code, status.HTTP_403_FORBIDDEN)

    def test_editor_groups_tracked_changes_once_and_stale_writes_fail(self) -> None:
        created = self.client.post(self.requests_url, self._payload(), format="json").json()
        request_url = f"{self.requests_url}{created['id']}/"
        other_account = create_account(team_id=self.team.id, name="Globex")
        area_three = FeatureRequestProductArea.objects.for_team(self.team.id).create(
            team=self.team,
            name="Data warehouse",
            display_order=3,
        )

        updated = self.client.patch(
            request_url,
            {
                "expected_version": created["version"],
                "title": "Export account retention data",
                "request_status": "planned",
                "request_priority": "high",
                "account_id": str(other_account.id),
                "product_area_ids": [str(self.area_two.id), str(area_three.id)],
            },
            format="json",
        )
        unchanged = self.client.patch(
            request_url,
            {"expected_version": updated.json()["version"], "request_status": "planned"},
            format="json",
        )
        invalid = self.client.patch(
            request_url,
            {"expected_version": updated.json()["version"], "product_area_ids": []},
            format="json",
        )
        stale = self.client.patch(
            request_url,
            {"expected_version": created["version"], "request_status": "completed"},
            format="json",
        )
        history = self.client.get(f"{request_url}history/")
        status_history = self.client.get(f"{request_url}status_history/")

        self.assertEqual(updated.status_code, status.HTTP_200_OK)
        self.assertEqual(updated.json()["request_status"], "planned")
        self.assertEqual(updated.json()["request_priority"], "high")
        self.assertEqual(updated.json()["version"], 2)
        self.assertEqual(unchanged.status_code, status.HTTP_200_OK)
        self.assertEqual(unchanged.json()["version"], 2)
        self.assertEqual(invalid.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(stale.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(history.status_code, status.HTTP_200_OK)
        self.assertEqual(len(history.json()), 2)
        self.assertEqual(
            [change["field"] for change in history.json()[0]["changes"]],
            [
                "status",
                "priority",
                "account",
                "product_areas",
            ],
        )
        self.assertEqual(
            history.json()[0]["changes"],
            [
                {"field": "status", "before": "requested", "after": "planned"},
                {"field": "priority", "before": None, "after": "high"},
                {
                    "field": "account",
                    "before": {"id": str(self.account.id), "name": "Acme"},
                    "after": {"id": str(other_account.id), "name": "Globex"},
                },
                {
                    "field": "product_areas",
                    "before": [
                        {"id": str(self.area_one.id), "name": "Product analytics"},
                        {"id": str(self.area_two.id), "name": "Session replay"},
                    ],
                    "after": [
                        {"id": str(self.area_two.id), "name": "Session replay"},
                        {"id": str(area_three.id), "name": "Data warehouse"},
                    ],
                },
            ],
        )
        self.assertTrue(history.json()[1]["is_initial"])
        self.assertEqual(
            [change["field"] for change in history.json()[1]["changes"]],
            ["status", "priority", "account", "product_areas"],
        )
        self.assertEqual(
            [(entry["previous_status"], entry["request_status"]) for entry in status_history.json()],
            [("requested", "planned"), (None, "requested")],
        )
        self.assertEqual(FeatureRequestHistory.objects.for_team(self.team.id).count(), 2)

    def test_history_keeps_account_and_product_area_name_snapshots_after_renames(self) -> None:
        created = self.client.post(self.requests_url, self._payload(), format="json").json()
        other_account = create_account(team_id=self.team.id, name="Globex")
        self.client.patch(
            f"{self.requests_url}{created['id']}/",
            {
                "expected_version": created["version"],
                "account_id": str(other_account.id),
                "product_area_ids": [str(self.area_two.id)],
            },
            format="json",
        )

        self.account.name = "Acme renamed"
        self.account.save(update_fields=["name"])
        other_account.name = "Globex renamed"
        other_account.save(update_fields=["name"])
        self.area_one.name = "Product analytics renamed"
        self.area_one.save(update_fields=["name"])
        history = self.client.get(f"{self.requests_url}{created['id']}/history/").json()

        changes = {change["field"]: change for change in history[0]["changes"]}
        self.assertEqual(changes["account"]["before"]["name"], "Acme")
        self.assertEqual(changes["account"]["after"]["name"], "Globex")
        self.assertEqual(changes["product_areas"]["before"][0]["name"], "Product analytics")
        initial_changes = {change["field"]: change for change in history[1]["changes"]}
        self.assertEqual(initial_changes["account"]["after"]["name"], "Acme")
        self.assertEqual(initial_changes["product_areas"]["after"][0]["name"], "Product analytics")

    def test_history_redacts_snapshots_for_accounts_the_viewer_cannot_access(self) -> None:
        created = self.client.post(self.requests_url, self._payload(), format="json").json()
        other_account = create_account(team_id=self.team.id, name="Globex")
        self.client.patch(
            f"{self.requests_url}{created['id']}/",
            {
                "expected_version": created["version"],
                "account_id": str(other_account.id),
            },
            format="json",
        )
        viewer = User.objects.create_and_join(
            self.organization,
            "restricted-feature-request-history-viewer@example.com",
            "testtest",
        )
        self._set_access_level(viewer, "viewer")
        membership = OrganizationMembership.objects.get(user=viewer, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="account",
            resource_id=str(self.account.id),
            access_level="none",
            organization_member=membership,
        )
        self.client.force_login(viewer)

        response = self.client.get(f"{self.requests_url}{created['id']}/history/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        updated_changes = {change["field"]: change for change in response.json()[0]["changes"]}
        self.assertEqual(updated_changes["account"]["before"], {"id": None, "name": "Restricted account"})
        self.assertEqual(
            updated_changes["account"]["after"],
            {"id": str(other_account.id), "name": "Globex"},
        )
        initial_changes = {change["field"]: change for change in response.json()[1]["changes"]}
        self.assertEqual(initial_changes["account"]["after"], {"id": None, "name": "Restricted account"})
        self.assertNotIn(str(self.account.id), str(response.json()))
        self.assertNotIn("Acme", str(response.json()))

    def test_list_combines_filters_orders_priorities_and_hides_archived_requests(self) -> None:
        first = self.client.post(self.requests_url, self._payload(), format="json").json()
        second_payload = self._payload()
        second_payload["title"] = "Session replay export"
        second = self.client.post(self.requests_url, second_payload, format="json").json()
        third_payload = self._payload()
        third_payload["title"] = "Unprioritized export"
        third = self.client.post(self.requests_url, third_payload, format="json").json()
        self.client.patch(
            f"{self.requests_url}{first['id']}/",
            {
                "expected_version": first["version"],
                "request_status": "planned",
                "request_priority": "low",
            },
            format="json",
        )
        second_updated = self.client.patch(
            f"{self.requests_url}{second['id']}/",
            {"expected_version": second["version"], "request_priority": "high"},
            format="json",
        ).json()
        self.client.post(
            f"{self.requests_url}{second['id']}/archive/",
            {"expected_version": second_updated["version"]},
            format="json",
        )

        active = self.client.get(
            self.requests_url,
            {
                "search": "retention",
                "statuses": "planned,completed",
                "priorities": "low,medium",
                "product_area_ids": str(self.area_one.id),
                "account_ids": str(self.account.id),
                "request_ordering": "-priority",
            },
        )
        archived = self.client.get(self.requests_url, {"archive_state": "archived"})
        ordered = self.client.get(
            self.requests_url,
            {"archive_state": "all", "request_ordering": "-priority"},
        )

        self.assertEqual(active.status_code, status.HTTP_200_OK)
        self.assertEqual([request["id"] for request in active.json()["results"]], [first["id"]])
        self.assertEqual([request["id"] for request in archived.json()["results"]], [second["id"]])
        self.assertEqual(
            [request["id"] for request in ordered.json()["results"]],
            [second["id"], first["id"], third["id"]],
        )

    def test_archive_and_restore_preserve_links_and_history(self) -> None:
        created = self.client.post(self.requests_url, self._payload(), format="json").json()
        request_url = f"{self.requests_url}{created['id']}/"
        updated = self.client.patch(
            request_url,
            {"expected_version": created["version"], "request_status": "completed"},
            format="json",
        ).json()

        archived = self.client.post(
            f"{request_url}archive/",
            {"expected_version": updated["version"]},
            format="json",
        )
        archived_update = self.client.patch(
            request_url,
            {"expected_version": archived.json()["version"], "title": "Cannot edit yet"},
            format="json",
        )
        restored = self.client.post(
            f"{request_url}restore/",
            {"expected_version": archived.json()["version"]},
            format="json",
        )
        history = self.client.get(f"{request_url}status_history/")

        self.assertTrue(archived.json()["is_archived"])
        self.assertEqual(archived_update.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(restored.json()["is_archived"])
        self.assertEqual(restored.json()["account"], created["account"])
        self.assertEqual(restored.json()["product_areas"], created["product_areas"])
        self.assertEqual(len(history.json()), 2)

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
