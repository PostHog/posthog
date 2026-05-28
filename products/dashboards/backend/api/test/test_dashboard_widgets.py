from unittest.mock import ANY, patch

from freezegun import freeze_time
from posthog.test.base import APIBaseTest

from django.test import override_settings

from rest_framework import status

from posthog.api.test.dashboards import DashboardAPI
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.team import Team

from products.dashboards.backend.models.dashboard import Dashboard
from posthog.rbac.user_access_control import UserAccessControl


class TestDashboardWidgets(APIBaseTest):
    _WIDGETS_FLAG_PATCH_TARGETS = (
        "products.dashboards.backend.api.dashboard.dashboard_widgets_enabled",
        "products.dashboards.backend.widget_create.dashboard_widgets_enabled",
    )

    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)
        self._widgets_flag_patchers = [
            patch(target, return_value=True) for target in self._WIDGETS_FLAG_PATCH_TARGETS
        ]
        for patcher in self._widgets_flag_patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in self._widgets_flag_patchers:
            patcher.stop()
        super().tearDown()

    def _stop_widgets_flag_patchers(self) -> None:
        for patcher in self._widgets_flag_patchers:
            patcher.stop()

    def _start_widgets_flag_patchers(self) -> None:
        for patcher in self._widgets_flag_patchers:
            patcher.start()

    @freeze_time("2022-04-01 12:45")
    @override_settings(IN_UNIT_TESTING=True)
    def test_can_create_widget_tile(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        _, dashboard_json = self.dashboard_api.create_widget_tile(
            dashboard_id,
            widget_type="error_tracking_list",
            config={"limit": 10},
        )

        assert len(dashboard_json["tiles"]) == 1
        tile = dashboard_json["tiles"][0]
        assert tile["widget"]["widget_type"] == "error_tracking_list"
        assert tile["widget"]["config"]["limit"] == 10
        assert tile["widget"]["created_by"]["id"] == self.user.id
        assert tile["insight"] is None
        assert tile["text"] is None
        assert tile["button_tile"] is None

    @override_settings(IN_UNIT_TESTING=True)
    def test_can_create_widget_tile_with_catalog_default_config(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        _, dashboard_json = self.dashboard_api.create_widget_tile(
            dashboard_id,
            config={"limit": 10, "dateRange": {"date_from": "-7d"}},
        )

        tile = dashboard_json["tiles"][0]
        assert tile["widget"]["config"]["dateRange"] == {"date_from": "-7d"}

    @override_settings(IN_UNIT_TESTING=True)
    def test_can_update_widget_tile_config(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(
            dashboard_id, config={"limit": 5, "orderBy": "last_seen"}
        )

        tile = dashboard_json["tiles"][0]
        tile["widget"]["config"] = {"limit": 15, "orderBy": "occurrences"}

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            {"tiles": [tile]},
        )
        assert response.status_code == status.HTTP_200_OK

        updated_tile = response.json()["tiles"][0]
        assert updated_tile["widget"]["config"]["limit"] == 15
        assert updated_tile["widget"]["config"]["orderBy"] == "occurrences"
        assert updated_tile["widget"]["id"] == tile["widget"]["id"]

    @override_settings(IN_UNIT_TESTING=True)
    def test_can_update_widget_tile_name_and_description(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id)

        tile = dashboard_json["tiles"][0]
        tile["widget"]["name"] = "My top errors"
        tile["widget"]["description"] = "Worst issues this week"
        tile["show_description"] = True

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            {"tiles": [tile]},
        )
        assert response.status_code == status.HTTP_200_OK

        updated_tile = response.json()["tiles"][0]
        assert updated_tile["widget"]["name"] == "My top errors"
        assert updated_tile["widget"]["description"] == "Worst issues this week"
        assert updated_tile["show_description"] is True

    @override_settings(IN_UNIT_TESTING=True)
    def test_duplicate_dashboard_copies_widget_name_with_suffix(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "source"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id)
        tile = dashboard_json["tiles"][0]
        tile["widget"]["name"] = "Custom widget title"
        self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            {"tiles": [tile]},
        )

        _, duplicated = self.dashboard_api.create_dashboard(
            {"name": "copy", "use_dashboard": dashboard_id, "duplicate_tiles": True}
        )

        assert duplicated["tiles"][0]["widget"]["name"] == "Custom widget title (Copy)"

    @override_settings(IN_UNIT_TESTING=True)
    def test_cannot_patch_widget_from_another_team(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id)

        other_team = Team.objects.create(
            organization=self.organization,
            name="other team",
            api_token="other-token",
        )
        other_dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "other"}, team_id=other_team.id)

        foreign_widget_id = dashboard_json["tiles"][0]["widget"]["id"]
        response = self.client.patch(
            f"/api/projects/{other_team.id}/dashboards/{other_dashboard_id}",
            {
                "tiles": [
                    {
                        "widget": {
                            "id": foreign_widget_id,
                            "widget_type": "error_tracking_list",
                            "config": {"limit": 10},
                        }
                    }
                ]
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "widget"

    @override_settings(IN_UNIT_TESTING=True)
    def test_patch_widget_denies_without_product_access(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id, config={"limit": 10})
        tile = dashboard_json["tiles"][0]
        tile["widget"]["config"] = {"limit": 12}

        real_check = UserAccessControl.check_access_level_for_resource

        def deny_error_tracking_only(
            user_access_control: UserAccessControl, resource: str, required_level: str = "viewer"
        ) -> bool:
            if resource == "error_tracking":
                return False
            return real_check(user_access_control, resource, required_level)

        with patch.object(
            UserAccessControl,
            "check_access_level_for_resource",
            autospec=True,
            side_effect=deny_error_tracking_only,
        ):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
                {"tiles": [tile]},
            )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"] == "You do not have access to error tracking."

    @override_settings(IN_UNIT_TESTING=True)
    def test_cannot_change_widget_type_via_dashboard_patch(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id, config={"limit": 10})
        tile = dashboard_json["tiles"][0]
        tile["widget"]["widget_type"] = "not_a_real_widget_type"

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            {"tiles": [tile]},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "widget"
        assert "widget_type cannot be changed" in response.json()["detail"]

    @override_settings(IN_UNIT_TESTING=True)
    def test_rejects_widget_update_via_dashboard_patch_when_feature_flag_disabled(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id, config={"limit": 10})
        tile = dashboard_json["tiles"][0]
        tile["widget"]["config"] = {"limit": 12}

        self._stop_widgets_flag_patchers()
        try:
            with patch(
                "products.dashboards.backend.api.dashboard.dashboard_widgets_enabled",
                return_value=False,
            ):
                response = self.client.patch(
                    f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
                    {"tiles": [tile]},
                )
        finally:
            self._start_widgets_flag_patchers()

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "widget"
        assert "not enabled" in response.json()["detail"].lower()

    @override_settings(IN_UNIT_TESTING=True)
    def test_duplicate_dashboard_without_deep_clone_still_clones_widgets(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "source"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id, config={"limit": 7})
        original_widget = dashboard_json["tiles"][0]["widget"]

        _, duplicated = self.dashboard_api.create_dashboard(
            {"name": "copy", "use_dashboard": dashboard_id, "duplicate_tiles": False}
        )

        assert len(duplicated["tiles"]) == 1
        assert duplicated["tiles"][0]["widget"]["config"] == original_widget["config"]
        assert duplicated["tiles"][0]["widget"]["id"] != original_widget["id"]

    @override_settings(IN_UNIT_TESTING=True)
    def test_duplicate_dashboard_preserves_widget_layout(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "source"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id)
        tile = dashboard_json["tiles"][0]
        tile_layout = {"sm": {"x": 0, "y": 2, "w": 6, "h": 4}}
        tile["layouts"] = tile_layout
        self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            {"tiles": [tile]},
        )

        _, duplicated = self.dashboard_api.create_dashboard(
            {"name": "copy", "use_dashboard": dashboard_id, "duplicate_tiles": True}
        )

        assert duplicated["tiles"][0]["layouts"] == tile_layout

    @override_settings(IN_UNIT_TESTING=True)
    def test_duplicate_dashboard_skips_soft_deleted_widget_tiles(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "source"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id)
        tile = dashboard_json["tiles"][0]
        self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            {"tiles": [{"id": tile["id"], "deleted": True}]},
        )

        _, duplicated = self.dashboard_api.create_dashboard(
            {"name": "copy", "use_dashboard": dashboard_id, "duplicate_tiles": True}
        )

        assert duplicated["tiles"] == []

    @override_settings(IN_UNIT_TESTING=True)
    def test_duplicate_dashboard_writes_widget_activity_log(self) -> None:
        ActivityLog.objects.filter(team_id=self.team.id, scope="DashboardWidget").delete()

        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "source"})
        self.dashboard_api.create_widget_tile(dashboard_id)
        create_count = ActivityLog.objects.filter(
            team_id=self.team.id, scope="DashboardWidget", activity="created"
        ).count()

        self.dashboard_api.create_dashboard(
            {"name": "copy", "use_dashboard": dashboard_id, "duplicate_tiles": True}
        )

        duplicate_logs = ActivityLog.objects.filter(
            team_id=self.team.id, scope="DashboardWidget", activity="created"
        )
        assert duplicate_logs.count() == create_count + 1

    @override_settings(IN_UNIT_TESTING=True)
    def test_duplicate_dashboard_deep_clones_widget(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "source"})
        self.dashboard_api.create_widget_tile(dashboard_id, config={"limit": 7})

        _, duplicated = self.dashboard_api.create_dashboard(
            {"name": "copy", "use_dashboard": dashboard_id, "duplicate_tiles": True}
        )

        assert len(duplicated["tiles"]) == 1
        original = self.dashboard_api.get_dashboard(dashboard_id)
        assert duplicated["tiles"][0]["widget"]["config"] == original["tiles"][0]["widget"]["config"]
        assert duplicated["tiles"][0]["widget"]["id"] != original["tiles"][0]["widget"]["id"]

    @override_settings(IN_UNIT_TESTING=True)
    def test_create_from_template_json_widget_tile(self) -> None:
        template = {
            "template_name": "ET dashboard",
            "dashboard_description": "Errors",
            "dashboard_filters": {},
            "tiles": [
                {
                    "type": "WIDGET",
                    "widget_type": "error_tracking_list",
                    "config": {"limit": 12},
                    "layouts": {"sm": {"h": 4, "w": 6, "x": 0, "y": 0}},
                }
            ],
        }
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/create_from_template_json",
            {"template": template},
        )
        assert response.status_code == status.HTTP_200_OK
        dashboard_json = response.json()
        assert len(dashboard_json["tiles"]) == 1
        assert dashboard_json["tiles"][0]["widget"]["widget_type"] == "error_tracking_list"
        assert dashboard_json["tiles"][0]["widget"]["config"]["limit"] == 12

    def _widget_template_payload(self, **overrides: object) -> dict:
        tile = {
            "type": "WIDGET",
            "widget_type": "error_tracking_list",
            "config": {"limit": 12},
            "layouts": {"sm": {"h": 4, "w": 6, "x": 0, "y": 0}},
        }
        tile.update(overrides)
        return {
            "template_name": "ET dashboard",
            "dashboard_description": "Errors",
            "dashboard_filters": {},
            "tiles": [tile],
        }

    @override_settings(IN_UNIT_TESTING=True)
    def test_create_from_template_json_widget_denies_without_product_access(self) -> None:
        real_check = UserAccessControl.check_access_level_for_resource

        def deny_error_tracking_only(
            user_access_control: UserAccessControl, resource: str, required_level: str = "viewer"
        ) -> bool:
            if resource == "error_tracking":
                return False
            return real_check(user_access_control, resource, required_level)

        with patch.object(
            UserAccessControl,
            "check_access_level_for_resource",
            autospec=True,
            side_effect=deny_error_tracking_only,
        ):
            response = self.client.post(
                f"/api/projects/{self.team.id}/dashboards/create_from_template_json",
                {"template": self._widget_template_payload()},
            )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"] == "You do not have access to error tracking."
        assert Dashboard.objects.filter(team_id=self.team.id, deleted=False).count() == 0

    @override_settings(IN_UNIT_TESTING=True)
    def test_create_from_template_json_widget_rejects_when_flag_disabled(self) -> None:
        self._stop_widgets_flag_patchers()
        try:
            with patch(
                "products.dashboards.backend.widget_create.dashboard_widgets_enabled",
                return_value=False,
            ):
                response = self.client.post(
                    f"/api/projects/{self.team.id}/dashboards/create_from_template_json",
                    {"template": self._widget_template_payload()},
                )
        finally:
            self._start_widgets_flag_patchers()

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Dashboard.objects.filter(team_id=self.team.id, deleted=False).count() == 0

    @override_settings(IN_UNIT_TESTING=True)
    def test_create_from_template_json_widget_rejects_unknown_widget_type(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/create_from_template_json",
            {"template": self._widget_template_payload(widget_type="not_a_real_widget_type")},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Dashboard.objects.filter(team_id=self.team.id, deleted=False).count() == 0

    @override_settings(IN_UNIT_TESTING=True)
    def test_create_from_template_json_widget_rejects_invalid_config(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/create_from_template_json",
            {"template": self._widget_template_payload(config={"limit": 999})},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Dashboard.objects.filter(team_id=self.team.id, deleted=False).count() == 0

    @freeze_time("2022-04-01 12:45")
    @override_settings(IN_UNIT_TESTING=True)
    def test_widget_create_and_update_writes_activity_log(self) -> None:
        ActivityLog.objects.filter(team_id=self.team.id, scope="DashboardWidget").delete()

        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id)

        create_logs = ActivityLog.objects.filter(team_id=self.team.id, scope="DashboardWidget", activity="created")
        assert create_logs.count() == 1
        assert create_logs.first().detail["name"] == "error_tracking_list"

        tile = dashboard_json["tiles"][0]
        tile["widget"]["config"] = {"limit": 20}
        self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            {"tiles": [tile]},
        )

        update_logs = ActivityLog.objects.filter(team_id=self.team.id, scope="DashboardWidget", activity="updated")
        assert update_logs.count() == 1

    @override_settings(IN_UNIT_TESTING=True)
    def test_copy_tile_copies_widget_tile(self) -> None:
        source_id, _ = self.dashboard_api.create_dashboard({"name": "source"})
        dest_id, _ = self.dashboard_api.create_dashboard({"name": "dest"})
        _, source_json = self.dashboard_api.create_widget_tile(source_id, config={"limit": 7})
        tile = source_json["tiles"][0]
        tile["widget"]["name"] = "Top errors"
        tile["widget"]["description"] = "Weekly summary"
        self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{source_id}",
            {"tiles": [tile]},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dest_id}/copy_tile",
            {"fromDashboardId": source_id, "tileId": tile["id"]},
        )
        assert response.status_code == status.HTTP_200_OK

        source_dashboard = self.dashboard_api.get_dashboard(source_id)
        dest_dashboard = self.dashboard_api.get_dashboard(dest_id)
        assert len(source_dashboard["tiles"]) == 1
        assert len(dest_dashboard["tiles"]) == 1

        source_widget = source_dashboard["tiles"][0]["widget"]
        dest_widget = dest_dashboard["tiles"][0]["widget"]
        assert dest_widget["id"] != source_widget["id"]
        assert dest_widget["name"] == "Top errors (Copy)"
        assert dest_widget["description"] == "Weekly summary"
        assert dest_widget["config"]["limit"] == 7
        assert dest_dashboard["tiles"][0]["layouts"] == source_dashboard["tiles"][0]["layouts"]

    @override_settings(IN_UNIT_TESTING=True)
    def test_move_tile_moves_widget_tile(self) -> None:
        source_id, _ = self.dashboard_api.create_dashboard({"name": "source"})
        dest_id, _ = self.dashboard_api.create_dashboard({"name": "dest"})
        _, source_json = self.dashboard_api.create_widget_tile(source_id, config={"limit": 9})
        tile = source_json["tiles"][0]
        widget_id = tile["widget"]["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{source_id}/move_tile",
            {"toDashboard": dest_id, "tile": {"id": tile["id"]}},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["tiles"] == []

        source_dashboard = self.dashboard_api.get_dashboard(source_id)
        dest_dashboard = self.dashboard_api.get_dashboard(dest_id)
        assert len(source_dashboard["tiles"]) == 0
        assert len(dest_dashboard["tiles"]) == 1
        assert dest_dashboard["tiles"][0]["widget"]["id"] == widget_id
        assert dest_dashboard["tiles"][0]["widget"]["config"]["limit"] == 9

    @override_settings(IN_UNIT_TESTING=True)
    def test_widget_catalog_lists_registered_types(self) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/widget_catalog/")
        assert response.status_code == status.HTTP_200_OK

        results = response.json()["results"]
        assert any(entry["widget_type"] == "error_tracking_list" for entry in results)
        error_tracking_list = next(entry for entry in results if entry["widget_type"] == "error_tracking_list")
        assert error_tracking_list["config_schema_hints"]["limit"]["max"] == 25
        assert error_tracking_list["availability_requirements"] == ["exception_autocapture"]

    @override_settings(IN_UNIT_TESTING=True)
    def test_add_widget_via_widgets_endpoint(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/widgets/",
            {"widget_type": "error_tracking_list", "config": {"limit": 8}, "name": "Errors"},
        )
        assert response.status_code == status.HTTP_201_CREATED

        tile = response.json()
        assert tile["widget"]["widget_type"] == "error_tracking_list"
        assert tile["widget"]["config"]["limit"] == 8
        assert tile["widget"]["name"] == "Errors"
        assert tile["layouts"]["sm"]["w"] == 6

    @override_settings(IN_UNIT_TESTING=True)
    def test_update_widget_via_dedicated_endpoint(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id, config={"limit": 5})
        tile_id = dashboard_json["tiles"][0]["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/widgets/{tile_id}/",
            {"config": {"limit": 11}, "show_description": True},
        )
        assert response.status_code == status.HTTP_200_OK

        updated = response.json()
        assert updated["widget"]["config"]["limit"] == 11
        assert updated["show_description"] is True

    @override_settings(IN_UNIT_TESTING=True)
    def test_error_tracking_widget_type_alias(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        _, dashboard_json = self.dashboard_api.create_widget_tile(
            dashboard_id,
            widget_type="error_tracking",
            config={"limit": 10},
        )

        tile = dashboard_json["tiles"][0]
        assert tile["widget"]["widget_type"] == "error_tracking"
        assert tile["widget"]["config"]["limit"] == 10

    @override_settings(IN_UNIT_TESTING=True)
    def test_widgets_endpoint_rejects_unknown_widget_type(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/widgets/",
            {"widget_type": "unknown", "config": {}},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @override_settings(IN_UNIT_TESTING=True)
    def test_widgets_endpoint_requires_feature_flag(self) -> None:
        self._stop_widgets_flag_patchers()
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        try:
            with patch(
                "products.dashboards.backend.api.dashboard.dashboard_widgets_enabled",
                return_value=False,
            ):
                response = self.client.post(
                    f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/widgets/",
                    {"widget_type": "error_tracking_list", "config": {"limit": 5}},
                )
        finally:
            self._start_widgets_flag_patchers()

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @override_settings(IN_UNIT_TESTING=True)
    @patch("products.dashboards.backend.api.dashboard.report_user_action")
    def test_add_widget_tile_via_patch_fires_tile_added_event(self, mock_report_user_action) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        mock_report_user_action.reset_mock()

        self.dashboard_api.create_widget_tile(
            dashboard_id,
            widget_type="error_tracking_list",
            config={"limit": 10},
        )

        mock_report_user_action.assert_any_call(
            self.user,
            "dashboard tile added",
            {
                "tile_type": "widget",
                "insight_type": None,
                "dashboard_id": dashboard_id,
                "widget_type": "error_tracking_list",
            },
            team=ANY,
            request=ANY,
        )

    @override_settings(IN_UNIT_TESTING=True)
    @patch("products.dashboards.backend.api.dashboard.report_user_action")
    def test_add_widget_tile_via_widgets_endpoint_fires_tile_added_event(self, mock_report_user_action) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        mock_report_user_action.reset_mock()

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/widgets/",
            {"widget_type": "error_tracking_list", "config": {"limit": 8}, "name": "Errors"},
        )
        assert response.status_code == status.HTTP_201_CREATED

        mock_report_user_action.assert_any_call(
            self.user,
            "dashboard tile added",
            {
                "tile_type": "widget",
                "insight_type": None,
                "dashboard_id": dashboard_id,
                "widget_type": "error_tracking_list",
            },
            team=ANY,
            request=ANY,
        )

    @override_settings(IN_UNIT_TESTING=True)
    def test_can_batch_create_widget_tiles(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/widgets/batch/",
            {
                "widgets": [
                    {"widget_type": "error_tracking_list", "config": {"limit": 5}},
                    {"widget_type": "session_replay_list", "config": {"limit": 3}},
                ]
            },
        )
        assert response.status_code == status.HTTP_201_CREATED

        tiles = response.json()["tiles"]
        assert len(tiles) == 2
        assert tiles[0]["widget"]["widget_type"] == "error_tracking_list"
        assert tiles[1]["widget"]["widget_type"] == "session_replay_list"
        assert tiles[0]["layouts"]["sm"]["y"] == 0
        assert tiles[1]["layouts"]["sm"]["y"] == tiles[0]["layouts"]["sm"]["h"]

    @override_settings(IN_UNIT_TESTING=True)
    def test_batch_create_widget_tiles_rejects_empty_list(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/widgets/batch/",
            {"widgets": []},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @override_settings(IN_UNIT_TESTING=True)
    def test_batch_create_widget_tiles_is_atomic(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/widgets/batch/",
            {
                "widgets": [
                    {"widget_type": "error_tracking_list", "config": {"limit": 5}},
                    {"widget_type": "unknown_widget", "config": {}},
                ]
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        dashboard = Dashboard.objects.get(id=dashboard_id)
        assert dashboard.tiles.filter(widget__isnull=False).count() == 0

    @override_settings(IN_UNIT_TESTING=True)
    @patch("products.dashboards.backend.api.dashboard.report_user_action")
    def test_update_widget_tile_does_not_fire_tile_added_event(self, mock_report_user_action) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id, config={"limit": 5})
        mock_report_user_action.reset_mock()

        tile = dashboard_json["tiles"][0]
        tile["widget"]["config"] = {"limit": 15}

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            {"tiles": [tile]},
        )
        assert response.status_code == status.HTTP_200_OK

        for call in mock_report_user_action.call_args_list:
            assert call[0][1] != "dashboard tile added"
