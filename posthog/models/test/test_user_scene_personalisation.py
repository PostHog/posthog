import pytest
from posthog.test.base import BaseTest

from django import db

from posthog.models import Dashboard, User, UserScenePersonalisation


class TestUserScenePersonalisation(BaseTest):
    def test_user_can_have_a_preference(self):
        dashboard = Dashboard.objects.create(
            team=self.team,
        )

        udp = UserScenePersonalisation.objects.create(
            scene="Persons",
            dashboard=dashboard,
            team=self.team,
            user=self.user,
        )

        assert list(self.user.scene_personalisation.all()) == [udp]

    def test_user_cannot_have_clashing_preference(self):
        dashboard = Dashboard.objects.create(
            team=self.team,
        )
        dashboard_two = Dashboard.objects.create(
            team=self.team,
        )

        UserScenePersonalisation.objects.create(
            scene="Persons",
            dashboard=dashboard,
            team=self.team,
            user=self.user,
        )
        with pytest.raises(db.utils.IntegrityError):
            UserScenePersonalisation.objects.create(
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

        UserScenePersonalisation.objects.create(
            scene="Persons",
            dashboard=dashboard,
            team=self.team,
            user=self.user,
        )

        UserScenePersonalisation.objects.create(
            scene="Groups",
            dashboard=dashboard_two,
            team=self.team,
            user=self.user,
        )

        assert self.user.scene_personalisation.count() == 2

    def test_deleting_user_deletes_preferences(self):
        another_user = User.objects.create_and_join(self.organization, "another@example.comn", "password")

        dashboard = Dashboard.objects.create(
            team=self.team,
        )

        UserScenePersonalisation.objects.create(
            scene="Persons",
            dashboard=dashboard,
            team=self.team,
            user=another_user,
        )

        assert UserScenePersonalisation.objects.count() == 1

        another_user.delete()

        assert UserScenePersonalisation.objects.count() == 0
