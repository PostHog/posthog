from freezegun import freeze_time
from posthog.test.base import APIBaseTest

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.api.test.dashboards import DashboardAPI


class TestDashboardButtonTiles(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

    @freeze_time("2022-04-01 12:45")
    @override_settings(IN_UNIT_TESTING=True)
    def test_can_create_button_tile(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        _, dashboard_json = self.dashboard_api.create_button_tile(
            dashboard_id, url="https://example.com", text="Visit site"
        )

        assert len(dashboard_json["tiles"]) == 1
        tile = dashboard_json["tiles"][0]
        assert tile["button_tile"]["url"] == "https://example.com"
        assert tile["button_tile"]["text"] == "Visit site"
        assert tile["button_tile"]["placement"] == "left"
        assert tile["button_tile"]["style"] == "primary"
        assert tile["button_tile"]["created_by"]["id"] == self.user.id

    @freeze_time("2022-04-01 12:45")
    @override_settings(IN_UNIT_TESTING=True)
    def test_can_create_button_tile_with_pathname(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        _, dashboard_json = self.dashboard_api.create_button_tile(
            dashboard_id, url="/dashboards", text="Go to dashboards"
        )

        assert len(dashboard_json["tiles"]) == 1
        assert dashboard_json["tiles"][0]["button_tile"]["url"] == "/dashboards"

    @freeze_time("2022-04-01 12:45")
    @override_settings(IN_UNIT_TESTING=True)
    def test_can_create_button_tile_with_custom_placement_and_style(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        _, dashboard_json = self.dashboard_api.create_button_tile(
            dashboard_id,
            url="https://example.com",
            text="Click",
            placement="right",
            style="secondary",
        )

        tile = dashboard_json["tiles"][0]
        assert tile["button_tile"]["placement"] == "right"
        assert tile["button_tile"]["style"] == "secondary"

    @override_settings(IN_UNIT_TESTING=True)
    def test_can_update_button_tile(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_button_tile(
            dashboard_id, url="https://example.com", text="Original"
        )

        tile = dashboard_json["tiles"][0]
        tile["button_tile"]["text"] = "Updated"
        tile["button_tile"]["url"] = "https://new-url.com"

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            {"tiles": [tile]},
        )
        assert response.status_code == status.HTTP_200_OK

        updated_tile = response.json()["tiles"][0]
        assert updated_tile["button_tile"]["text"] == "Updated"
        assert updated_tile["button_tile"]["url"] == "https://new-url.com"

    def test_can_remove_button_tile(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_button_tile(
            dashboard_id, url="https://example.com", text="Click me"
        )

        tile = dashboard_json["tiles"][0]
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            {"tiles": [{"id": tile["id"], "deleted": True}]},
        )
        assert response.status_code == status.HTTP_200_OK

        dashboard_json = self.dashboard_api.get_dashboard(dashboard_id)
        assert len(dashboard_json["tiles"]) == 0

    @parameterized.expand(
        [
            ("valid_full_url", "https://example.com/path?q=1", status.HTTP_200_OK),
            ("valid_pathname", "/dashboard/123", status.HTTP_200_OK),
            ("valid_pathname_with_query", "/insights?filter=active", status.HTTP_200_OK),
            ("invalid_no_slash_prefix", "dashboard/123", status.HTTP_400_BAD_REQUEST),
            ("invalid_empty_string", "", status.HTTP_400_BAD_REQUEST),
            ("invalid_random_text", "not a url", status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_url_validation(self, _name: str, url: str, expected_status: int) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        self.dashboard_api.create_button_tile(dashboard_id, url=url, text="Click", expected_status=expected_status)

    def test_text_is_required(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            {"tiles": [{"button_tile": {"url": "https://example.com", "text": ""}}]},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_can_mix_button_and_text_tiles(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        self.dashboard_api.create_text_tile(dashboard_id, text="Some text")
        _, dashboard_json = self.dashboard_api.create_button_tile(dashboard_id, url="https://example.com", text="Click")

        assert len(dashboard_json["tiles"]) == 2
        tile_types = set()
        for tile in dashboard_json["tiles"]:
            if tile["text"]:
                tile_types.add("text")
            if tile["button_tile"]:
                tile_types.add("button_tile")
        assert tile_types == {"text", "button_tile"}

    def test_can_create_button_tile_with_transparent_background(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        _, dashboard_json = self.dashboard_api.create_button_tile(
            dashboard_id,
            url="https://example.com",
            text="Click",
            extra_data={"transparent_background": True},
        )

        tile = dashboard_json["tiles"][0]
        assert tile["transparent_background"] is True

    def test_transparent_background_preserved_on_dashboard_duplication(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        self.dashboard_api.create_button_tile(
            dashboard_id,
            url="https://example.com",
            text="Click",
            extra_data={"transparent_background": True},
        )

        _, new_dashboard_json = self.dashboard_api.create_dashboard(
            {"name": "duplicated", "use_dashboard": dashboard_id}
        )

        assert new_dashboard_json["tiles"][0]["transparent_background"] is True

    @override_settings(IN_UNIT_TESTING=True)
    def test_can_duplicate_button_tile_via_dashboard_duplication(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        self.dashboard_api.create_button_tile(dashboard_id, url="https://example.com", text="Click")

        new_dashboard_id, new_dashboard_json = self.dashboard_api.create_dashboard(
            {"name": "duplicated", "use_dashboard": dashboard_id}
        )

        assert len(new_dashboard_json["tiles"]) == 1
        assert new_dashboard_json["tiles"][0]["button_tile"]["url"] == "https://example.com"
        assert new_dashboard_json["tiles"][0]["button_tile"]["text"] == "Click"
        assert new_dashboard_json["tiles"][0]["id"] != dashboard_id
