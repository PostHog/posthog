import pytest
from django import db

from posthog.models import User, UserSceneDashboardChoice, Dashboard
from posthog.test.base import BaseTest


class TestUserSceneDashboardChoice(BaseTest):
    def test_user_can_have_a_preference(self):
        dashboard = Dashboard.objects.create(
            team=self.team,
        )

        udp = UserSceneDashboardChoice.objects.create(
            scene="Persons",
            dashboard=dashboard,
            team=self.team,
            user=self.user,
        )

        assert list(self.user.scene_dashboard_choices.all()) == [udp]

    def test_user_cannot_have_clashing_preference(self):
        dashboard = Dashboard.objects.create(
            team=self.team,
        )
        dashboard_two = Dashboard.objects.create(
            team=self.team,
        )

        UserSceneDashboardChoice.objects.create(
            scene="Persons",
            dashboard=dashboard,
            team=self.team,
            user=self.user,
        )
        with pytest.raises(db.utils.IntegrityError):
            UserSceneDashboardChoice.objects.create(
                scene="Persons",
                dashboard=dashboard_two,
                team=self.team,
                user=self.user,
            )

    def test_user_cannot_user_same_preference_for_multiple_scenes(self):
        dashboard = Dashboard.objects.create(
            team=self.team,
        )
        dashboard_two = Dashboard.objects.create(
            team=self.team,
        )

        UserSceneDashboardChoice.objects.create(
            scene="Persons",
            dashboard=dashboard,
            team=self.team,
            user=self.user,
        )

        UserSceneDashboardChoice.objects.create(
            scene="Groups",
            dashboard=dashboard_two,
            team=self.team,
            user=self.user,
        )

        assert self.user.scene_dashboard_choices.count() == 2

    def test_deleting_user_deletes_preferences(self):
        another_user = User.objects.create_and_join(self.organization, "another@example.comn", "password")

        dashboard = Dashboard.objects.create(
            team=self.team,
        )

        UserSceneDashboardChoice.objects.create(
            scene="Persons",
            dashboard=dashboard,
            team=self.team,
            user=another_user,
        )

        assert UserSceneDashboardChoice.objects.count() == 1

        another_user.delete()

        assert UserSceneDashboardChoice.objects.count() == 0
