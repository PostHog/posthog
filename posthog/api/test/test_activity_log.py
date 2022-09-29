from typing import Any, Dict, Optional, Tuple

from rest_framework import status

from posthog.models import User
from posthog.test.base import APIBaseTest, QueryMatchingTest


def _feature_flag_json_payload(key: str) -> Dict:
    return {
        "key": key,
        "name": "",
        "filters": {"groups": [{"properties": [], "rollout_percentage": None}], "multivariate": None},
        "deleted": False,
        "active": True,
        "created_by": None,
        "is_simple_flag": False,
        "rollout_percentage": None,
        "ensure_experience_continuity": False,
        "experiment_set": None,
    }


class TestActivityLog(APIBaseTest, QueryMatchingTest):
    def setUp(self) -> None:
        super().setUp()
        self.other_user = User.objects.create_and_join(
            organization=self.organization,
            email="other_user@posthog.com",
            password="",
        )

    def test_can_get_top_ten_important_changes(self) -> None:
        created_insights = []
        for i in range(0, 11):
            insight_id, _ = self._create_insight({})
            created_insights.append(insight_id)

        flag_one = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/", _feature_flag_json_payload("one")
        ).json()["id"]

        flag_two = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/", _feature_flag_json_payload("two")
        ).json()["id"]

        # other user now edits them
        self.client.force_login(self.other_user)
        for created_insight_id in created_insights:
            update_response = self.client.patch(
                f"/api/projects/{self.team.id}/insights/{created_insight_id}",
                {"name": f"{created_insight_id}-insight"},
            )
            self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        self.client.patch(f"/api/projects/{self.team.id}/feature_flags/{flag_one}", {"name": "one"})
        self.client.patch(f"/api/projects/{self.team.id}/feature_flags/{flag_two}", {"name": "two"})

        # user one has created 10 insights and 2 flags
        # user two has edited them all
        # user one is shown the most recent 10 of those changes
        self.client.force_login(self.user)
        changes = self.client.get(f"/api/projects/{self.team.id}/activity_log/important_changes")
        assert changes.status_code == status.HTTP_200_OK
        assert len(changes.json()) == 10
        assert [c["scope"] for c in changes.json()] == [
            "FeatureFlag",
            "FeatureFlag",
            "Insight",
            "Insight",
            "Insight",
            "Insight",
            "Insight",
            "Insight",
            "Insight",
            "Insight",
        ]

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
