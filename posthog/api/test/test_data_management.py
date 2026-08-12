from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import Team
from posthog.models.activity_logging.activity_log import ActivityLog


class TestDataManagementActivity(APIBaseTest):
    def test_activity_is_scoped_to_the_project_in_the_url(self):
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        ActivityLog.objects.create(team_id=self.team.id, scope="EventDefinition", activity="created", item_id="current")
        ActivityLog.objects.create(team_id=other_team.id, scope="EventDefinition", activity="created", item_id="other")

        response = self.client.get(f"/api/projects/{other_team.id}/data_management/activity/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item_ids = [row["item_id"] for row in response.json()["results"]]
        self.assertEqual(item_ids, ["other"])
