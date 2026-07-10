from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models.file_system.user_product_list import DEFAULT_PRODUCT_PATHS, UserProductList


class TestUserProductListAPI(APIBaseTest):
    def test_seed_adds_default_products_and_returns_all_enabled(self):
        UserProductList.objects.create(
            user=self.user,
            team=self.team,
            product_path="Feature flags",
            enabled=True,
            reason=UserProductList.Reason.PRODUCT_INTENT,
        )
        UserProductList.objects.create(
            user=self.user,
            team=self.team,
            product_path="Session replay",
            enabled=False,
            reason=UserProductList.Reason.PRODUCT_INTENT,
        )

        response = self.client.post(f"/api/environments/{self.team.id}/user_product_list/seed/")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        data_by_path = {item["product_path"]: item for item in data}

        # The default products get seeded (minus the intentionally disabled one),
        # and the previously enabled row is returned too
        expected_paths = {path for path in DEFAULT_PRODUCT_PATHS if path != "Session replay"} | {"Feature flags"}
        self.assertEqual(set(data_by_path), expected_paths)
        for path in expected_paths - {"Feature flags"}:
            self.assertEqual(data_by_path[path]["reason"], UserProductList.Reason.DEFAULT)
        self.assertEqual(data_by_path["Feature flags"]["reason"], UserProductList.Reason.PRODUCT_INTENT)

        # The intentionally disabled row is not re-enabled
        session_replay = UserProductList.objects.get(user=self.user, team=self.team, product_path="Session replay")
        self.assertFalse(session_replay.enabled)
