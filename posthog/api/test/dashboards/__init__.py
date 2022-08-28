from typing import Any, Dict, Literal, Optional, Tuple

from rest_framework import status

from posthog.models.team import Team


class DashboardAPI:
    def __init__(self, client, team: Team, assertEqual):
        self.client = client
        self.team = team
        self.assertEqual = assertEqual

    def soft_delete(
        self,
        model_id: int,
        model_type: Literal["insights", "dashboards"],
        expected_get_status: int = status.HTTP_404_NOT_FOUND,
    ) -> None:
        api_response = self.client.patch(f"/api/projects/{self.team.id}/{model_type}/{model_id}", {"deleted": True})
        assert api_response.status_code == status.HTTP_200_OK
        self.assertEqual(
            self.client.get(f"/api/projects/{self.team.id}/{model_type}/{model_id}").status_code, expected_get_status,
        )

    def create_dashboard(
        self, data: Dict[str, Any], team_id: Optional[int] = None, expected_status: int = status.HTTP_201_CREATED,
    ) -> Tuple[int, Dict[str, Any]]:
        if team_id is None:
            team_id = self.team.id
        response = self.client.post(f"/api/projects/{team_id}/dashboards/", data)
        self.assertEqual(response.status_code, expected_status)

        response_json = response.json()
        dashboard_id = response_json["id"] if response.status_code == status.HTTP_201_CREATED else -1
        return dashboard_id, response_json

    def get_insight(
        self, insight_id: int, team_id: Optional[int] = None, expected_status: int = status.HTTP_200_OK
    ) -> Dict[str, Any]:
        if team_id is None:
            team_id = self.team.id

        response = self.client.get(f"/api/projects/{team_id}/insights/{insight_id}")
        self.assertEqual(response.status_code, expected_status)

        response_json = response.json()
        return response_json

    def create_insight(
        self, data: Dict[str, Any], team_id: Optional[int] = None, expected_status: int = status.HTTP_201_CREATED
    ) -> Tuple[int, Dict[str, Any]]:
        if team_id is None:
            team_id = self.team.id

        if "filters" not in data:
            data["filters"] = {"events": [{"id": "$pageview"}]}

        response = self.client.post(f"/api/projects/{team_id}/insights", data=data,)
        self.assertEqual(response.status_code, expected_status)

        response_json = response.json()
        return response_json.get("id", None), response_json
