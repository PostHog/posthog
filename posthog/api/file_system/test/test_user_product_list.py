from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models.file_system.user_product_list import UserProductList


class TestUserProductListAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        # Project setup already seeded the default sidebar, which includes both Session replay
        # and its companion. Start from an empty list so the fan-out is what creates the rows.
        UserProductList.objects.filter(user=self.user, team=self.team).delete()

    def _bulk_update(self, items: list[dict]):
        return self.client.patch(
            f"/api/projects/{self.team.id}/user_product_list/bulk_update",
            {"items": items},
            format="json",
        )

    def test_enabling_session_replay_also_pins_its_companions(self):
        response = self._bulk_update([{"product_path": "Session replay", "enabled": True}])

        assert response.status_code == status.HTTP_200_OK, response.json()
        returned_paths = {item["product_path"] for item in response.json()["results"]}
        assert returned_paths == {"Session replay", "Replay vision"}

        row = UserProductList.objects.get(user=self.user, team=self.team, product_path="Replay vision")
        assert row.enabled is True

    def test_disabling_session_replay_does_not_pin_its_companions(self):
        response = self._bulk_update([{"product_path": "Session replay", "enabled": False}])

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert not UserProductList.objects.filter(user=self.user, team=self.team, product_path="Replay vision").exists()
