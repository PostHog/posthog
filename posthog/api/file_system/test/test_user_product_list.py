from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import Team, User
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

        assert response.status_code == status.HTTP_200_OK
        product_list.refresh_from_db()
        assert product_list.enabled
        assert product_list.reason == UserProductList.Reason.PRODUCT_INTENT
        assert product_list.reason_text == ""

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

        assert response.status_code == status.HTTP_200_OK
        product_list.refresh_from_db()
        assert product_list.enabled
        assert product_list.reason == UserProductList.Reason.PRODUCT_INTENT
        assert product_list.reason_text == ""

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

        assert response.status_code == status.HTTP_200_OK
        product_list.refresh_from_db()
        assert not product_list.enabled
        assert product_list.reason == UserProductList.Reason.USED_BY_COLLEAGUES
        assert product_list.reason_text == "Some reason text"

    def test_seed_creates_products_from_colleagues_and_other_teams(self):
        UserProductList.objects.create(
            user=self.user,
            team=self.team,
            product_path="Product analytics",
            enabled=True,
            reason=UserProductList.Reason.PRODUCT_INTENT,
        )

        colleague = User.objects.create_user(
            email="colleague@posthog.com", password="password", first_name="Colleague", allow_sidebar_suggestions=True
        )
        colleague.join(organization=self.organization)

        UserProductList.objects.create(user=colleague, team=self.team, product_path="Session replay", enabled=True)
        UserProductList.objects.create(user=colleague, team=self.team, product_path="Feature flags", enabled=True)

        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        UserProductList.objects.create(user=self.user, team=other_team, product_path="Surveys", enabled=True)

        response = self.client.post(f"/api/environments/{self.team.id}/user_product_list/seed/")

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert isinstance(data, list)

        product_paths = {item["product_path"] for item in data}
        assert "Product analytics" in product_paths
        assert "Session replay" in product_paths
        assert "Feature flags" in product_paths
        assert "Surveys" in product_paths

        data_by_path = {item["product_path"]: item for item in data}
        assert data_by_path["Product analytics"]["reason"] == UserProductList.Reason.PRODUCT_INTENT
        assert data_by_path["Session replay"]["reason"] == UserProductList.Reason.USED_BY_COLLEAGUES
        assert data_by_path["Feature flags"]["reason"] == UserProductList.Reason.USED_BY_COLLEAGUES
        assert data_by_path["Surveys"]["reason"] == UserProductList.Reason.USED_ON_SEPARATE_TEAM

        for item in data:
            assert item["enabled"]

    def test_seed_only_returns_enabled_products(self):
        UserProductList.objects.create(
            user=self.user,
            team=self.team,
            product_path="Product analytics",
            enabled=True,
            reason=UserProductList.Reason.PRODUCT_INTENT,
        )
        UserProductList.objects.create(
            user=self.user,
            team=self.team,
            product_path="Feature flags",
            enabled=False,
            reason=UserProductList.Reason.USED_BY_COLLEAGUES,
        )

        response = self.client.post(f"/api/environments/{self.team.id}/user_product_list/seed/")

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        product_paths = {item["product_path"] for item in data}

        assert "Product analytics" in product_paths
        assert "Feature flags" not in product_paths

        data_by_path = {item["product_path"]: item for item in data}
        assert data_by_path["Product analytics"]["reason"] == UserProductList.Reason.PRODUCT_INTENT
