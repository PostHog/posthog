from posthog.test.base import APIBaseTest

from posthog.models.file_system.user_product_list import UserProductList


class TestUserProductListAPI(APIBaseTest):
    def test_list_includes_disabled_rows(self):
        UserProductList.objects.filter(team=self.team, user=self.user).delete()
        UserProductList.objects.create(team=self.team, user=self.user, product_path="Session replay", enabled=True)
        UserProductList.objects.create(team=self.team, user=self.user, product_path="Replay vision", enabled=False)

        response = self.client.get(f"/api/projects/{self.team.id}/user_product_list/")

        assert response.status_code == 200
        assert {(row["product_path"], row["enabled"]) for row in response.json()["results"]} == {
            ("Session replay", True),
            ("Replay vision", False),
        }
