from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models.file_system.user_product_list import UserProductList


class TestUserProductListAPI(APIBaseTest):
    def test_update_by_path_clears_reason_and_reason_text_when_enabling(self):
        product_list = UserProductList.objects.create(
            team=self.team,
            user=self.user,
            product_path="Product analytics",
            enabled=False,
            reason=UserProductList.Reason.USED_BY_COLLEAGUES,
            reason_text="Some reason text",
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/user_product_list/update_by_path/",
            {"product_path": "Product analytics", "enabled": True},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        product_list.refresh_from_db()
        self.assertEqual(product_list.enabled, True)
        self.assertEqual(product_list.reason, UserProductList.Reason.PRODUCT_INTENT)
        self.assertEqual(product_list.reason_text, "")

    def test_update_by_path_clears_reason_and_reason_text_when_already_enabled(self):
        product_list = UserProductList.objects.create(
            team=self.team,
            user=self.user,
            product_path="Product analytics",
            enabled=True,
            reason=UserProductList.Reason.USED_BY_COLLEAGUES,
            reason_text="Some reason text",
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/user_product_list/update_by_path/",
            {"product_path": "Product analytics", "enabled": True},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        product_list.refresh_from_db()
        self.assertEqual(product_list.enabled, True)
        self.assertEqual(product_list.reason, UserProductList.Reason.PRODUCT_INTENT)
        self.assertEqual(product_list.reason_text, "")

    def test_update_by_path_does_not_clear_reason_when_disabling(self):
        product_list = UserProductList.objects.create(
            team=self.team,
            user=self.user,
            product_path="Product analytics",
            enabled=True,
            reason=UserProductList.Reason.USED_BY_COLLEAGUES,
            reason_text="Some reason text",
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/user_product_list/update_by_path/",
            {"product_path": "Product analytics", "enabled": False},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        product_list.refresh_from_db()
        self.assertEqual(product_list.enabled, False)
        self.assertEqual(product_list.reason, UserProductList.Reason.USED_BY_COLLEAGUES)
        self.assertEqual(product_list.reason_text, "Some reason text")
