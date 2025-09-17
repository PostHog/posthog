from typing import Any, Literal, Optional

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
        extra_data: Optional[dict] = None,
        expected_get_status: int = status.HTTP_404_NOT_FOUND,
    ) -> None:
        if extra_data is None:
            extra_data = {}

        api_response = self.client.patch(
            f"/api/projects/{self.team.id}/{model_type}/{model_id}",
            {"deleted": True, **extra_data},
        )
        assert api_response.status_code == status.HTTP_200_OK
        self.assertEqual(
            self.client.get(f"/api/projects/{self.team.id}/{model_type}/{model_id}").status_code,
            expected_get_status,
        )

    def create_dashboard(
        self,
        data: dict[str, Any],
        team_id: Optional[int] = None,
        expected_status: int = status.HTTP_201_CREATED,
    ) -> tuple[int, dict[str, Any]]:
        if team_id is None:
            team_id = self.team.id
        response = self.client.post(f"/api/projects/{team_id}/dashboards/", data)
        self.assertEqual(response.status_code, expected_status)

        response_json = response.json()
        dashboard_id = response_json["id"] if response.status_code == status.HTTP_201_CREATED else -1
        return dashboard_id, response_json

    def update_dashboard(
        self,
        dashboard_id: int,
        data: dict[str, Any],
        team_id: Optional[int] = None,
        expected_status: int = status.HTTP_200_OK,
    ) -> tuple[int, dict[str, Any]]:
        if team_id is None:
            team_id = self.team.id
        response = self.client.patch(f"/api/projects/{team_id}/dashboards/{dashboard_id}", data)
        self.assertEqual(response.status_code, expected_status)

        response_json = response.json()
        dashboard_id = response_json["id"] if response.status_code == status.HTTP_200_OK else -1
        return dashboard_id, response_json

    def get_dashboard(
        self,
        dashboard_id: int,
        team_id: Optional[int] = None,
        expected_status: int = status.HTTP_200_OK,
        query_params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        if team_id is None:
            team_id = self.team.id

        response = self.client.get(f"/api/projects/{team_id}/dashboards/{dashboard_id}", query_params)
        self.assertEqual(response.status_code, expected_status)

        response_json = response.json()
        return response_json

    def list_dashboards(
        self,
        team_id: Optional[int] = None,
        expected_status: int = status.HTTP_200_OK,
        query_params: Optional[dict] = None,
        *,
        parent: Literal["project", "environment"] = "project",
    ) -> dict:
        if team_id is None:
            team_id = self.team.id

        if query_params is None:
            query_params = {}

        response = self.client.get(f"/api/{parent}s/{team_id}/dashboards/", query_params)
        self.assertEqual(response.status_code, expected_status)

        response_json = response.json()
        return response_json

    def list_insights(
        self,
        team_id: Optional[int] = None,
        expected_status: int = status.HTTP_200_OK,
        query_params: Optional[dict] = None,
    ) -> dict:
        if team_id is None:
            team_id = self.team.id

        if query_params is None:
            query_params = {}

        response = self.client.get(
            f"/api/projects/{team_id}/insights/",
            {"basic": True, "limit": 30, **query_params},
        )
        self.assertEqual(response.status_code, expected_status)

        response_json = response.json()
        return response_json

    def get_insight(
        self,
        insight_id: int,
        team_id: Optional[int] = None,
        expected_status: int = status.HTTP_200_OK,
        query_params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        if team_id is None:
            team_id = self.team.id

        if query_params is None:
            query_params = {}

        response = self.client.get(f"/api/projects/{team_id}/insights/{insight_id}", query_params)
        self.assertEqual(response.status_code, expected_status)

        response_json = response.json()
        return response_json

    def create_insight(
        self,
        data: dict[str, Any],
        team_id: Optional[int] = None,
        expected_status: int = status.HTTP_201_CREATED,
    ) -> tuple[int, dict[str, Any]]:
        if team_id is None:
            team_id = self.team.id

        if "filters" not in data and "query" not in data:
            data["filters"] = {"events": [{"id": "$pageview"}]}

        response = self.client.post(
            f"/api/projects/{team_id}/insights",
            data=data,
        )
        self.assertEqual(response.status_code, expected_status, response.json())

        response_json = response.json()
        return response_json.get("id", None), response_json

    def update_insight(
        self,
        insight_id: int,
        data: dict[str, Any],
        team_id: Optional[int] = None,
        expected_status: int = status.HTTP_200_OK,
    ) -> tuple[int, dict[str, Any]]:
        if team_id is None:
            team_id = self.team.id

        response = self.client.patch(f"/api/projects/{team_id}/insights/{insight_id}", data=data)
        self.assertEqual(response.status_code, expected_status, response.json())

        response_json = response.json()
        return response_json.get("id", None), response_json

    def create_text_tile(
        self,
        dashboard_id: int,
        text: str = "I AM TEXT!",
        extra_data: Optional[dict] = None,
        team_id: Optional[int] = None,
        expected_status: int = status.HTTP_200_OK,
    ) -> tuple[int, dict[str, Any]]:
        if team_id is None:
            team_id = self.team.id

        if extra_data is None:
            extra_data = {}

        response = self.client.patch(
            f"/api/projects/{team_id}/dashboards/{dashboard_id}",
            {"tiles": [{"text": {"body": text}, **extra_data}]},
        )

        self.assertEqual(response.status_code, expected_status, response.json())

        response_json = response.json()
        return response_json.get("id", None), response_json

    def get_insight_activity(
        self,
        insight_id: Optional[int] = None,
        team_id: Optional[int] = None,
        expected_status: int = status.HTTP_200_OK,
    ):
        if team_id is None:
            team_id = self.team.id

        if insight_id is None:
            url = f"/api/projects/{team_id}/insights/activity"
        else:
            url = f"/api/projects/{team_id}/insights/{insight_id}/activity"

        activity = self.client.get(url)
        self.assertEqual(activity.status_code, expected_status)
        return activity.json()

    def update_text_tile(
        self,
        dashboard_id: int,
        tile: dict,
        team_id: Optional[int] = None,
        expected_status: int = status.HTTP_200_OK,
    ) -> tuple[int, dict[str, Any]]:
        if team_id is None:
            team_id = self.team.id

        response = self.client.patch(f"/api/projects/{team_id}/dashboards/{dashboard_id}", {"tiles": [tile]})

        self.assertEqual(response.status_code, expected_status, response.json())

        response_json = response.json()
        return response_json.get("id", None), response_json

    def set_tile_layout(self, dashboard_id: int, expected_tiles_to_update: int) -> None:
        dashboard_json = self.get_dashboard(dashboard_id)
        tiles = dashboard_json["tiles"]
        assert len(tiles) == expected_tiles_to_update

        x = 0
        y = 0
        for tile in tiles:
            x += 1
            y += 1

            tile_id = tile["id"]
            # layouts used to live on insights, but moved onto the relation from a dashboard to its insights
            response = self.client.patch(
                f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
                {
                    "tiles": [
                        {
                            "id": tile_id,
                            "layouts": {
                                "sm": {
                                    "w": "7",
                                    "h": "5",
                                    "x": str(x),
                                    "y": str(y),
                                    "moved": "False",
                                    "static": "False",
                                },
                                "xs": {"x": "0", "y": "0", "w": "6", "h": "5"},
                            },
                        }
                    ]
                },
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

    def add_insight_to_dashboard(
        self,
        dashboard_ids: list[int],
        insight_id: int,
        expected_status: int = status.HTTP_200_OK,
    ):
        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight_id}",
            {"dashboards": dashboard_ids},
        )
        self.assertEqual(response.status_code, expected_status)
