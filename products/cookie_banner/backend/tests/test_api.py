from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.constants import AvailableFeature

from products.cookie_banner.backend.models import CookieBannerConfig


class TestCookieBannerConfigAPI(APIBaseTest):
    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/cookie_banner/"

    def test_create_list_and_update(self) -> None:
        response = self.client.post(self._url(), {"enabled": True, "appearance": {"title": "Cookies!"}})
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        config_id = response.json()["id"]

        list_response = self.client.get(self._url())
        assert list_response.json()["count"] == 1
        assert list_response.json()["results"][0]["appearance"] == {"title": "Cookies!"}

        patch_response = self.client.patch(f"{self._url()}{config_id}/", {"enabled": False})
        assert patch_response.status_code == status.HTTP_200_OK
        assert patch_response.json()["enabled"] is False
        assert patch_response.json()["appearance"] == {"title": "Cookies!"}

    def test_second_create_is_rejected(self) -> None:
        assert self.client.post(self._url(), {"enabled": True}).status_code == status.HTTP_201_CREATED
        response = self.client.post(self._url(), {"enabled": True})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "already exists" in response.json()["detail"]

    def test_invalid_appearance_is_rejected(self) -> None:
        response = self.client.post(self._url(), {"appearance": {"artStyle": "dancing-hog"}})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "appearance__artStyle"

    def test_white_label_gated_on_entitlement(self) -> None:
        response = self.client.post(self._url(), {"appearance": {"whiteLabel": True}})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        self.organization.available_product_features = [
            {"key": AvailableFeature.WHITE_LABELLING, "name": AvailableFeature.WHITE_LABELLING}
        ]
        self.organization.save()

        response = self.client.post(self._url(), {"appearance": {"whiteLabel": True}})
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["appearance"] == {"whiteLabel": True}

    def test_cannot_access_other_teams_config(self) -> None:
        other_team = self.create_team_with_organization(organization=self.organization)
        response = self.client.post(self._url(), {"enabled": True})
        config_id = response.json()["id"]

        other_url = f"/api/projects/{other_team.id}/cookie_banner/"
        assert self.client.get(other_url).json()["count"] == 0
        assert self.client.get(f"{other_url}{config_id}/").status_code == status.HTTP_404_NOT_FOUND

    def test_destroy_removes_config(self) -> None:
        config_id = self.client.post(self._url(), {"enabled": True}).json()["id"]
        assert self.client.delete(f"{self._url()}{config_id}/").status_code == status.HTTP_204_NO_CONTENT
        assert not CookieBannerConfig.objects.for_team(self.team.id).exists()
