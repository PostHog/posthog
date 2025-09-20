from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.api.data_color_theme import DataColorTheme
from posthog.constants import AvailableFeature
from posthog.models.organization import Organization
from posthog.models.team.team import Team


class TestDataColorTheme(APIBaseTest):
    def test_can_fetch_public_themes(self) -> None:
        response = self.client.get(f"/api/environments/{self.team.pk}/data_color_themes")

        assert response.status_code == status.HTTP_200_OK
        assert response.data[0]["is_global"]

    def test_can_fetch_own_themes(self) -> None:
        other_org = Organization.objects.create(name="other org")
        other_team = Team.objects.create(organization=other_org, name="other project")
        DataColorTheme.objects.create(name="Custom theme 1", colors=[], team=self.team)
        DataColorTheme.objects.create(name="Custom theme 2", colors=[], team=other_team)

        response = self.client.get(f"/api/environments/{self.team.pk}/data_color_themes")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 2
        assert response.data[1]["name"] == "Custom theme 1"

    def test_can_edit_own_themes(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.DATA_COLOR_THEMES, "name": AvailableFeature.DATA_COLOR_THEMES}
        ]
        self.organization.save()

        theme = DataColorTheme.objects.create(name="Original name", colors=[], team=self.team)

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/data_color_themes/{theme.pk}", {"name": "New name"}
        )

        assert response.status_code == status.HTTP_200_OK
        assert DataColorTheme.objects.get(pk=theme.pk).name == "New name"

    def test_can_not_edit_own_themes_when_feature_disabled(self) -> None:
        theme = DataColorTheme.objects.create(name="Original name", colors=[], team=self.team)

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/data_color_themes/{theme.pk}", {"name": "New name"}
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"] == "This feature is only available on paid plans."
        assert DataColorTheme.objects.get(pk=theme.pk).name == "Original name"

    def test_can_not_edit_public_themes(self) -> None:
        theme = DataColorTheme.objects.first()
        assert theme

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/data_color_themes/{theme.pk}", {"name": "New name"}
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"] == "Only staff users can edit global themes."
        assert DataColorTheme.objects.get(pk=theme.pk).name == "Default Theme"

    def test_can_edit_public_themes_as_staff(self) -> None:
        self.user.is_staff = True
        self.user.save()
        theme = DataColorTheme.objects.first()
        assert theme

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/data_color_themes/{theme.pk}", {"name": "New name"}
        )

        assert response.status_code == status.HTTP_200_OK
        assert DataColorTheme.objects.get(pk=theme.pk).name == "New name"
