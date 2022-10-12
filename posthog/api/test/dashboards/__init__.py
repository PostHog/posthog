from typing import Any, Dict, List, Literal, Optional, Tuple

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
            self.client.get(f"/api/projects/{self.team.id}/{model_type}/{model_id}").status_code,
            expected_get_status,
        )

    def create_dashboard(
        self,
        data: Dict[str, Any],
        team_id: Optional[int] = None,
        expected_status: int = status.HTTP_201_CREATED,
    ) -> Tuple[int, Dict[str, Any]]:
        if team_id is None:
            team_id = self.team.id
        response = self.client.post(f"/api/projects/{team_id}/dashboards/", data)
        self.assertEqual(response.status_code, expected_status)

        response_json = response.json()
        dashboard_id = response_json["id"] if response.status_code == status.HTTP_201_CREATED else -1
        return dashboard_id, response_json

    def get_dashboard(
        self, dashboard_id: int, team_id: Optional[int] = None, expected_status: int = status.HTTP_200_OK
    ) -> Dict[str, Any]:
        if team_id is None:
            team_id = self.team.id

        response = self.client.get(f"/api/projects/{team_id}/dashboards/{dashboard_id}")
        self.assertEqual(response.status_code, expected_status)

        response_json = response.json()
        return response_json

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

        response = self.client.post(
            f"/api/projects/{team_id}/insights",
            data=data,
        )
        self.assertEqual(response.status_code, expected_status)

        response_json = response.json()
        return response_json.get("id", None), response_json

    def create_text_tile(
        self,
        dashboard_id: int,
        text: str = "I AM TEXT!",
        team_id: Optional[int] = None,
        expected_status: int = status.HTTP_200_OK,
    ) -> Tuple[int, Dict[str, Any]]:
        if team_id is None:
            team_id = self.team.id

        response = self.client.patch(
            f"/api/projects/{team_id}/dashboards/{dashboard_id}", {"tiles": [{"text": {"body": text}}]}
        )

        self.assertEqual(response.status_code, expected_status, response.json())

        response_json = response.json()
        return response_json.get("id", None), response_json

    def update_text_tile(
        self,
        dashboard_id: int,
        tile: Dict,
        team_id: Optional[int] = None,
        expected_status: int = status.HTTP_200_OK,
    ) -> Tuple[int, Dict[str, Any]]:
        if team_id is None:
            team_id = self.team.id

        response = self.client.patch(f"/api/projects/{team_id}/dashboards/{dashboard_id}", {"tiles": [tile]})

        self.assertEqual(response.status_code, expected_status, response.json())

        response_json = response.json()
        return response_json.get("id", None), response_json

    def update_tile_layouts(self, dashboard_id: int, layouts: List[Dict]) -> List[Dict]:
        add_layouts_response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/tiles/layouts",
            layouts,
        )
        self.assertEqual(add_layouts_response.status_code, status.HTTP_200_OK)
        dashboard_json = self.get_dashboard(dashboard_id)
        return [t["layouts"] for t in dashboard_json["tiles"]]
