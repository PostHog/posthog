from datetime import timedelta
from typing import Any, Dict, Optional, Tuple

from freezegun import freeze_time
from rest_framework import status

from posthog.models import User
from posthog.test.base import APIBaseTest, QueryMatchingTest


class TestActivityLog(APIBaseTest, QueryMatchingTest):
    def test_can_get_top_ten_important_changes_for_insights(self) -> None:
        with freeze_time("2022-04-01 12:00") as frozen_time:
            other_user = User.objects.create_and_join(
                organization=self.organization,
                email="other_user@posthog.com",
                password="",
            )

            created_insights = []
            for i in range(0, 11):
                frozen_time.tick(delta=timedelta(seconds=1))
                insight_id, _ = self._create_insight({})
                created_insights.append(insight_id)

            # other user now edits them
            self.client.force_login(other_user)
            for created_insight_id in created_insights:
                frozen_time.tick(delta=timedelta(seconds=1))
                update_response = self.client.patch(
                    f"/api/projects/{self.team.id}/insights/{created_insight_id}",
                    {"name": f"{created_insight_id}-insight"},
                )
                self.assertEqual(update_response.status_code, status.HTTP_200_OK)

            frozen_time.tick(delta=timedelta(seconds=1))
            self.client.force_login(self.user)
            changes = self.client.get(f"/api/projects/{self.team.id}/activity_log/important_changes")
            assert changes.status_code == status.HTTP_200_OK
            assert len(changes.json()) == 10

    def _create_insight(
        self, data: Dict[str, Any], team_id: Optional[int] = None, expected_status: int = status.HTTP_201_CREATED
    ) -> Tuple[int, Dict[str, Any]]:
        if team_id is None:
            team_id = self.team.id

        if "filters" not in data:
            data["filters"] = {"events": [{"id": "$pageview"}]}

        response = self.client.post(f"/api/projects/{team_id}/insights", data=data)
        self.assertEqual(response.status_code, expected_status)

        response_json = response.json()
        return response_json.get("id", None), response_json
