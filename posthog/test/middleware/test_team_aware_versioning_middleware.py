from reversion.models import Version

from posthog.models import FeatureFlag
from posthog.test.base import APIBaseTest


class TestTeamAwareVersioningMiddleware(APIBaseTest):
    def test_we_can_create_a_revision(self):
        response = self.client.post(
            f"/api/projects/{self.team.pk}/feature_flags", {"name": "Beta feature", "key": "red_button"}
        )
        self.assertEqual(response.status_code, 201)
        versions = Version.objects.all()
        self.assertEqual(len(versions), 1)

    def test_we_can_create_two_revisions(self):
        response = self.client.post(
            f"/api/projects/{self.team.pk}/feature_flags", {"name": "Beta feature", "key": "red_button"}
        )
        self.assertEqual(response.status_code, 201)

        ff_id = response.json()["id"]
        update_response = self.client.patch(
            f"/api/projects/{self.team.pk}/feature_flags/{ff_id}", {"name": "Beta feature", "key": "red_button"},
        )
        self.assertEqual(update_response.status_code, 200)
        versions = Version.objects.get_for_object(FeatureFlag.objects.get(pk=ff_id))
        self.assertEqual(len(versions), 2)
