from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.api.data_color_theme import DataColorTheme
from posthog.constants import AvailableFeature
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team


class TestDataColorTheme(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # The global "Default Theme" is seeded by migration 0537, but a
        # TransactionTestCase flush earlier on the same shard truncates migration
        # data and nothing restores it (ensure_migration_defaults is a manual
        # command, not a test hook). Recreate it idempotently so these tests don't
        # silently depend on what ran before them. The guard matches the migration
        # so a non-flushed run still sees exactly one global theme.
        if not DataColorTheme.objects.filter(team__isnull=True, name="Default Theme").exists():
            DataColorTheme.objects.create(
                name="Default Theme",
                # Mirror migration 0537 so the recreated theme is identical to the
                # seeded one — otherwise its `colors` would be order/shard-dependent
                # (real palette when not flushed, empty when recreated).
                colors=[
                    "#1d4aff",
                    "#621da6",
                    "#42827e",
                    "#ce0e74",
                    "#f14f58",
                    "#7c440e",
                    "#529a0a",
                    "#0476fb",
                    "#fe729e",
                    "#35416b",
                    "#41cbc4",
                    "#b64b02",
                    "#e4a604",
                    "#a56eff",
                    "#30d5c8",
                ],
                team=None,
            )

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
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
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
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        theme = DataColorTheme.objects.create(name="Original name", colors=[], team=self.team)

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/data_color_themes/{theme.pk}", {"name": "New name"}
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"] == "This feature is only available on paid plans."
        assert DataColorTheme.objects.get(pk=theme.pk).name == "Original name"

    def test_can_not_edit_public_themes(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        theme = DataColorTheme.objects.first()
        assert theme

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/data_color_themes/{theme.pk}", {"name": "New name"}
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"] == "Only staff users can edit global themes."
        assert DataColorTheme.objects.get(pk=theme.pk).name == "Default Theme"

    def test_member_can_not_edit_themes(self) -> None:
        theme = DataColorTheme.objects.create(name="Original name", colors=[], team=self.team)

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/data_color_themes/{theme.pk}", {"name": "New name"}
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert DataColorTheme.objects.get(pk=theme.pk).name == "Original name"

    def test_can_edit_public_themes_as_staff(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.user.is_staff = True
        self.user.save()
        theme = DataColorTheme.objects.first()
        assert theme

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/data_color_themes/{theme.pk}", {"name": "New name"}
        )

        assert response.status_code == status.HTTP_200_OK
        assert DataColorTheme.objects.get(pk=theme.pk).name == "New name"
