from typing import Any

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import ANY, PropertyMock, patch

from django.test import override_settings

from drf_spectacular.generators import SchemaGenerator
from parameterized import parameterized
from rest_framework import status

from posthog.api.test.dashboards import DashboardAPI
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.team import Team
from posthog.rbac.user_access_control import AccessControlLevel, UserAccessControl
from posthog.scopes import APIScopeObject

from products.dashboards.backend.api.dashboard import DashboardTileSerializer
from products.dashboards.backend.constants import DEFAULT_WIDGET_LIST_LIMIT
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_templates import DashboardTemplate
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.dashboards.backend.models.dashboard_widget import DashboardWidget
from products.dashboards.backend.widget_registry import EXPECTED_WIDGET_TYPES
from products.product_analytics.backend.models.insight import Insight


class TestDashboardWidgets(APIBaseTest):
    _WIDGETS_FLAG_PATCH_TARGETS = (
        "products.dashboards.backend.api.dashboard.dashboard_widgets_enabled",
        "products.dashboards.backend.widget_create.dashboard_widgets_enabled",
    )

    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)
        self._widgets_flag_patchers = [patch(target, return_value=True) for target in self._WIDGETS_FLAG_PATCH_TARGETS]
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
    def test_dashboard_patch_widget_update_without_config_preserves_config(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(
            dashboard_id, config={"limit": 5, "orderBy": "last_seen"}
        )

        tile = dashboard_json["tiles"][0]
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            {"tiles": [{"id": tile["id"], "widget": {"id": tile["widget"]["id"], "name": "Renamed"}}]},
        )
        assert response.status_code == status.HTTP_200_OK

        updated_tile = response.json()["tiles"][0]
        assert updated_tile["widget"]["name"] == "Renamed"
        assert updated_tile["widget"]["config"]["limit"] == 5
        assert updated_tile["widget"]["config"]["orderBy"] == "last_seen"

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
            user_access_control: UserAccessControl,
            resource: APIScopeObject,
            required_level: AccessControlLevel = "viewer",
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
        tile["widget"]["widget_type"] = "session_replay_list"

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

        self.dashboard_api.create_dashboard({"name": "copy", "use_dashboard": dashboard_id, "duplicate_tiles": True})

        duplicate_logs = ActivityLog.objects.filter(team_id=self.team.id, scope="DashboardWidget", activity="created")
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

    def _widget_template_payload(self, **overrides: Any) -> dict[str, Any]:
        tile: dict[str, Any] = {
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
            user_access_control: UserAccessControl,
            resource: APIScopeObject,
            required_level: AccessControlLevel = "viewer",
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
    def test_create_dashboard_use_template_widget_denies_without_product_access(self) -> None:
        template_name = "widget-et-use-template"
        DashboardTemplate.objects.create(
            team=self.team,
            template_name=template_name,
            dashboard_description="Errors",
            dashboard_filters={},
            tiles=[self._widget_template_payload()["tiles"][0]],
        )

        real_check = UserAccessControl.check_access_level_for_resource

        def deny_error_tracking_only(
            user_access_control: UserAccessControl,
            resource: APIScopeObject,
            required_level: AccessControlLevel = "viewer",
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
                f"/api/projects/{self.team.id}/dashboards/",
                {"name": "ET from template", "use_template": template_name},
            )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"] == "You do not have access to error tracking."
        assert not DashboardWidget.all_teams.filter(team_id=self.team.id).exists()

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
        create_log = create_logs.first()
        assert create_log is not None
        detail = create_log.detail
        assert detail is not None
        assert detail["name"] == "error_tracking_list"

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
            {"to_dashboard": dest_id, "tile": {"id": tile["id"]}},
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
        assert error_tracking_list["config_schema"]["properties"]["limit"]["default"] == DEFAULT_WIDGET_LIST_LIMIT
        assert error_tracking_list["availability_requirements"] == ["exception_autocapture"]

    @override_settings(IN_UNIT_TESTING=True)
    def test_add_widget_via_batch_endpoint(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/widgets/batch/",
            {
                "widgets": [
                    {"widget_type": "error_tracking_list", "config": {"limit": 8}, "name": "Errors"},
                ]
            },
        )
        assert response.status_code == status.HTTP_201_CREATED

        tile = response.json()["tiles"][0]
        assert tile["widget"]["widget_type"] == "error_tracking_list"
        assert tile["widget"]["config"]["limit"] == 8
        assert tile["widget"]["name"] == "Errors"
        assert tile["layouts"]["sm"]["w"] == 6

    @override_settings(IN_UNIT_TESTING=True)
    def test_widgets_batch_endpoint_rejects_legacy_error_tracking_widget_type(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/widgets/batch/",
            {"widgets": [{"widget_type": "error_tracking", "config": {"limit": 10}}]},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @override_settings(IN_UNIT_TESTING=True)
    def test_widgets_batch_endpoint_rejects_unknown_widget_type(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/widgets/batch/",
            {"widgets": [{"widget_type": "unknown", "config": {}}]},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @override_settings(IN_UNIT_TESTING=True)
    def test_widgets_batch_endpoint_requires_feature_flag(self) -> None:
        self._stop_widgets_flag_patchers()
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        try:
            with patch(
                "products.dashboards.backend.api.dashboard.dashboard_widgets_enabled",
                return_value=False,
            ):
                response = self.client.post(
                    f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/widgets/batch/",
                    {"widgets": [{"widget_type": "error_tracking_list", "config": {"limit": 5}}]},
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
        widget_added_calls = [
            call for call in mock_report_user_action.call_args_list if call[0][1] == "dashboard widget added"
        ]
        assert len(widget_added_calls) == 1
        assert widget_added_calls[0][0][2]["widget_type"] == "error_tracking_list"
        assert widget_added_calls[0][0][2]["dashboard_id"] == dashboard_id
        assert widget_added_calls[0][0][2]["dashboard_widget_count"] == 1
        assert "tile_id" in widget_added_calls[0][0][2]
        assert "widget_id" in widget_added_calls[0][0][2]

    @override_settings(IN_UNIT_TESTING=True)
    @patch("products.dashboards.backend.api.dashboard.report_user_action")
    def test_add_widget_tile_via_batch_endpoint_fires_tile_added_event(self, mock_report_user_action) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        mock_report_user_action.reset_mock()

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/widgets/batch/",
            {
                "widgets": [
                    {"widget_type": "error_tracking_list", "config": {"limit": 8}, "name": "Errors"},
                ]
            },
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
        widget_added_calls = [
            call for call in mock_report_user_action.call_args_list if call[0][1] == "dashboard widget added"
        ]
        assert len(widget_added_calls) == 1
        assert widget_added_calls[0][0][2]["widget_type"] == "error_tracking_list"
        assert widget_added_calls[0][0][2]["dashboard_id"] == dashboard_id
        assert widget_added_calls[0][0][2]["dashboard_widget_count"] == 1
        assert "tile_id" in widget_added_calls[0][0][2]
        assert "widget_id" in widget_added_calls[0][0][2]

    @override_settings(IN_UNIT_TESTING=True)
    @patch("products.dashboards.backend.api.dashboard.report_user_action")
    def test_add_session_replay_widget_fires_dashboard_widget_added_event(self, mock_report_user_action) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        mock_report_user_action.reset_mock()

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/widgets/batch/",
            {
                "widgets": [
                    {"widget_type": "session_replay_list", "config": {"limit": 5}, "name": "Recent replays"},
                ]
            },
        )
        assert response.status_code == status.HTTP_201_CREATED

        widget_added_calls = [
            call for call in mock_report_user_action.call_args_list if call[0][1] == "dashboard widget added"
        ]
        assert len(widget_added_calls) == 1
        assert widget_added_calls[0][0][2]["widget_type"] == "session_replay_list"

    @parameterized.expand(
        [
            ("session_replay_off", "session_replay_list", "session_recording_opt_in", False),
            ("session_replay_on", "session_replay_list", "session_recording_opt_in", True),
            ("error_tracking_off", "error_tracking_list", "autocapture_exceptions_opt_in", False),
            ("error_tracking_on", "error_tracking_list", "autocapture_exceptions_opt_in", True),
        ]
    )
    @override_settings(IN_UNIT_TESTING=True)
    @patch("products.dashboards.backend.api.dashboard.report_user_action")
    def test_dashboard_widget_added_records_feature_enabled(
        self, _name: str, widget_type: str, team_field: str, expected: bool, mock_report_user_action
    ) -> None:
        setattr(self.team, team_field, expected)
        self.team.save()
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        mock_report_user_action.reset_mock()

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/widgets/batch/",
            {"widgets": [{"widget_type": widget_type, "config": {"limit": 5}}]},
        )
        assert response.status_code == status.HTTP_201_CREATED

        widget_added_calls = [
            call for call in mock_report_user_action.call_args_list if call[0][1] == "dashboard widget added"
        ]
        assert len(widget_added_calls) == 1
        assert widget_added_calls[0][0][2]["widget_type"] == widget_type
        assert widget_added_calls[0][0][2]["feature_enabled"] is expected

    @override_settings(IN_UNIT_TESTING=True)
    @patch("products.dashboards.backend.api.dashboard.report_user_action")
    def test_delete_widget_tile_fires_tile_removed_and_widget_removed_events(self, mock_report_user_action) -> None:
        dashboard_id, dashboard_json = self.dashboard_api.create_widget_tile(
            dashboard_id=self.dashboard_api.create_dashboard({"name": "dashboard"})[0],
            widget_type="error_tracking_list",
            config={"limit": 10},
        )
        tile_id = dashboard_json["tiles"][0]["id"]
        mock_report_user_action.reset_mock()

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/delete_tile",
            {"tile_id": tile_id},
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

        mock_report_user_action.assert_any_call(
            self.user,
            "dashboard tile removed",
            {
                "tile_type": "widget",
                "insight_type": None,
                "dashboard_id": dashboard_id,
                "widget_type": "error_tracking_list",
            },
            team=ANY,
            request=ANY,
        )
        widget_removed_calls = [
            call for call in mock_report_user_action.call_args_list if call[0][1] == "dashboard widget removed"
        ]
        assert len(widget_removed_calls) == 1
        assert widget_removed_calls[0][0][2]["widget_type"] == "error_tracking_list"
        assert widget_removed_calls[0][0][2]["dashboard_id"] == dashboard_id
        assert widget_removed_calls[0][0][2]["tile_id"] == tile_id
        assert "widget_id" in widget_removed_calls[0][0][2]

    @override_settings(IN_UNIT_TESTING=True)
    @patch("products.dashboards.backend.api.dashboard.report_user_action")
    def test_soft_delete_widget_tile_via_dashboard_patch_fires_removed_events(self, mock_report_user_action) -> None:
        dashboard_id, dashboard_json = self.dashboard_api.create_widget_tile(
            dashboard_id=self.dashboard_api.create_dashboard({"name": "dashboard"})[0],
            widget_type="error_tracking_list",
            config={"limit": 10},
        )
        tile_id = dashboard_json["tiles"][0]["id"]
        mock_report_user_action.reset_mock()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            {"tiles": [{"id": tile_id, "deleted": True}]},
        )
        assert response.status_code == status.HTTP_200_OK

        removed_events = [call[0][1] for call in mock_report_user_action.call_args_list]
        assert "dashboard tile removed" in removed_events
        widget_removed_calls = [
            call for call in mock_report_user_action.call_args_list if call[0][1] == "dashboard widget removed"
        ]
        assert len(widget_removed_calls) == 1
        assert widget_removed_calls[0][0][2]["widget_type"] == "error_tracking_list"
        assert widget_removed_calls[0][0][2]["dashboard_id"] == dashboard_id
        assert widget_removed_calls[0][0][2]["tile_id"] == tile_id

        # Re-sending the same soft-delete payload must not double-report the removal
        mock_report_user_action.reset_mock()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            {"tiles": [{"id": tile_id, "deleted": True}]},
        )
        assert response.status_code == status.HTTP_200_OK
        for call in mock_report_user_action.call_args_list:
            assert call[0][1] not in ("dashboard tile removed", "dashboard widget removed")

    @override_settings(IN_UNIT_TESTING=True)
    @patch("products.dashboards.backend.api.dashboard.report_user_action")
    def test_update_widget_filters_via_dashboard_patch_fires_filters_updated_event(
        self, mock_report_user_action
    ) -> None:
        dashboard_id, dashboard_json = self.dashboard_api.create_widget_tile(
            dashboard_id=self.dashboard_api.create_dashboard({"name": "dashboard"})[0],
            widget_type="error_tracking_list",
            config={"limit": 10},
        )
        tile = dashboard_json["tiles"][0]
        tile["widget"]["config"] = {
            "limit": 10,
            "widgetFilters": {
                "qf-1": {
                    "filterId": "qf-1",
                    "propertyName": "$environment",
                    "optionId": "opt-1",
                    "operator": "exact",
                    "value": "production",
                }
            },
        }
        mock_report_user_action.reset_mock()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            {"tiles": [tile]},
        )
        assert response.status_code == status.HTTP_200_OK

        filters_updated_calls = [
            call for call in mock_report_user_action.call_args_list if call[0][1] == "dashboard widget filters updated"
        ]
        assert len(filters_updated_calls) == 1
        assert filters_updated_calls[0][0][2]["widget_type"] == "error_tracking_list"
        assert filters_updated_calls[0][0][2]["dashboard_id"] == dashboard_id
        assert filters_updated_calls[0][0][2]["widget_id"] == tile["widget"]["id"]
        assert filters_updated_calls[0][0][2]["filters_count"] == 1

    @parameterized.expand(
        [
            ("experiments_list", {"limit": 10, "status": "all"}, {"limit": 10, "status": "running"}, 1),
            ("experiments_list", {"limit": 10}, {"limit": 10, "createdBy": 7}, 1),
            ("experiment_results", {}, {"experimentId": 123}, 1),
        ]
    )
    @override_settings(IN_UNIT_TESTING=True)
    @patch("products.dashboards.backend.api.dashboard.report_user_action")
    def test_experiments_widget_top_level_filter_change_fires_filters_updated_event(
        self, widget_type, initial_config, changed_config, expected_count, mock_report_user_action
    ) -> None:
        dashboard_id, dashboard_json = self.dashboard_api.create_widget_tile(
            dashboard_id=self.dashboard_api.create_dashboard({"name": "dashboard"})[0],
            widget_type=widget_type,
            config=initial_config,
        )
        tile = dashboard_json["tiles"][0]
        tile["widget"]["config"] = changed_config
        mock_report_user_action.reset_mock()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            {"tiles": [tile]},
        )
        assert response.status_code == status.HTTP_200_OK

        filters_updated_calls = [
            call for call in mock_report_user_action.call_args_list if call[0][1] == "dashboard widget filters updated"
        ]
        assert len(filters_updated_calls) == 1
        assert filters_updated_calls[0][0][2]["widget_type"] == widget_type
        assert filters_updated_calls[0][0][2]["filters_count"] == expected_count

    @override_settings(IN_UNIT_TESTING=True)
    @patch("products.dashboards.backend.api.dashboard.report_user_action")
    def test_update_widget_config_without_filters_change_does_not_fire_filters_updated_event(
        self, mock_report_user_action
    ) -> None:
        dashboard_id, dashboard_json = self.dashboard_api.create_widget_tile(
            dashboard_id=self.dashboard_api.create_dashboard({"name": "dashboard"})[0],
            widget_type="error_tracking_list",
            config={"limit": 10},
        )
        tile = dashboard_json["tiles"][0]
        tile["widget"]["config"] = {"limit": 15}
        mock_report_user_action.reset_mock()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            {"tiles": [tile]},
        )
        assert response.status_code == status.HTTP_200_OK

        for call in mock_report_user_action.call_args_list:
            assert call[0][1] != "dashboard widget filters updated"

    @override_settings(IN_UNIT_TESTING=True)
    def test_can_batch_create_widget_tiles(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/widgets/batch/",
            {
                "widgets": [
                    {"widget_type": "error_tracking_list", "config": {"limit": 5}, "name": "Errors A"},
                    {"widget_type": "error_tracking_list", "config": {"limit": 3}, "name": "Errors B"},
                ]
            },
        )
        assert response.status_code == status.HTTP_201_CREATED

        tiles = response.json()["tiles"]
        assert len(tiles) == 2
        assert tiles[0]["widget"]["widget_type"] == "error_tracking_list"
        assert tiles[1]["widget"]["widget_type"] == "error_tracking_list"
        # Batch adds stack downward so vertical compaction keeps each tile at the bottom.
        assert tiles[0]["layouts"]["sm"]["y"] == 0
        assert tiles[0]["layouts"]["sm"]["x"] == 0
        assert tiles[1]["layouts"]["sm"]["y"] == 5
        assert tiles[1]["layouts"]["sm"]["x"] == 0

    @parameterized.expand(
        [
            # (persisted_sm_layouts, layoutless_count, expected_y)
            # Insights added to a dashboard get `layouts = {}` until a layout save; the backend
            # must still count them so a new widget lands below, not in a mid-page gap.
            # Layout-less tiles pack two-per-row at 6×5 (y boundaries every 2 tiles).
            ("one_layoutless", [], 1, 5),
            ("two_layoutless", [], 2, 5),
            ("three_layoutless", [], 3, 10),
            ("five_layoutless", [], 5, 15),
            # Persisted full-width header (h=2) + one layout-less tile packed below it (y=2,h=5 → 7).
            ("mixed_persisted_and_layoutless", [{"x": 0, "y": 0, "w": 12, "h": 2}], 1, 7),
        ]
    )
    @override_settings(IN_UNIT_TESTING=True)
    def test_widget_lands_below_tiles_with_no_persisted_layout(
        self, _name: str, persisted_sm_layouts: list[dict], layoutless_count: int, expected_y: int
    ) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        dashboard = Dashboard.objects.get(id=dashboard_id)
        for sm in persisted_sm_layouts:
            insight = Insight.objects.create(team=self.team, name="persisted")
            DashboardTile.objects.create(dashboard=dashboard, team_id=self.team.id, insight=insight, layouts={"sm": sm})
        for _ in range(layoutless_count):
            insight = Insight.objects.create(team=self.team, name="layoutless")
            DashboardTile.objects.create(dashboard=dashboard, team_id=self.team.id, insight=insight, layouts={})

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/widgets/batch/",
            {"widgets": [{"widget_type": "error_tracking_list", "config": {"limit": 5}}]},
        )
        assert response.status_code == status.HTTP_201_CREATED

        # The widget must land below the tallest column, not in a mid-page gap.
        sm = response.json()["tiles"][0]["layouts"]["sm"]
        assert sm["y"] == expected_y
        assert sm["x"] == 0

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
    def test_dashboard_widget_count_increments_with_each_add(self, mock_report_user_action) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        mock_report_user_action.reset_mock()

        # First widget
        self.dashboard_api.create_widget_tile(dashboard_id, widget_type="error_tracking_list", config={"limit": 5})
        first_add = next(
            call for call in mock_report_user_action.call_args_list if call[0][1] == "dashboard widget added"
        )
        assert first_add[0][2]["dashboard_widget_count"] == 1

        mock_report_user_action.reset_mock()

        # Second widget on the same dashboard
        self.dashboard_api.create_widget_tile(dashboard_id, widget_type="session_replay_list")
        second_add = next(
            call for call in mock_report_user_action.call_args_list if call[0][1] == "dashboard widget added"
        )
        assert second_add[0][2]["dashboard_widget_count"] == 2

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
            assert call[0][1] != "dashboard widget added"

    @override_settings(IN_UNIT_TESTING=True)
    @patch("posthog.resource_limits.evaluator.report_user_action")
    def test_widget_tile_creation_does_not_emit_limit_hit_below_threshold(self, mock_report_user_action) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/widgets/batch/",
            {"widgets": [{"widget_type": "error_tracking_list", "config": {"limit": 8}}]},
        )
        assert response.status_code == status.HTTP_201_CREATED

        limit_calls = [call for call in mock_report_user_action.call_args_list if call[0][1] == "resource limit hit"]
        assert limit_calls == []

    @override_settings(IN_UNIT_TESTING=True)
    @patch("posthog.resource_limits.evaluator.report_user_action")
    def test_widget_tile_creation_emits_resource_limit_hit_at_threshold(self, mock_report_user_action) -> None:
        from posthog.resource_limits import LimitKey

        from products.dashboards.backend.models.dashboard_tile import DashboardTile
        from products.dashboards.backend.models.dashboard_widget import DashboardWidget

        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        dashboard = Dashboard.objects.get(id=dashboard_id)

        for index in range(19):
            widget = DashboardWidget.all_teams.create(
                team_id=self.team.id,
                widget_type="error_tracking_list",
                name=f"Widget {index}",
                config={"limit": 10},
                created_by=self.user,
                last_modified_by=self.user,
            )
            DashboardTile.objects.create(
                dashboard=dashboard,
                team_id=self.team.id,
                widget=widget,
                layouts={"sm": {"x": 0, "y": index, "w": 6, "h": 5}},
            )

        mock_report_user_action.reset_mock()

        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/widgets/batch/",
            {
                "widgets": [
                    {"widget_type": "error_tracking_list", "config": {"limit": 8}, "name": "Widget 20"},
                ]
            },
        )
        assert response.status_code == status.HTTP_201_CREATED

        limit_calls = [call for call in mock_report_user_action.call_args_list if call[0][1] == "resource limit hit"]
        assert len(limit_calls) == 1
        properties = limit_calls[0][0][2]
        assert properties["limit_key"] == LimitKey.MAX_WIDGETS_PER_DASHBOARD
        assert properties["limit"] == 20
        assert properties["current_count"] == 19
        assert properties["crossing_threshold"] is True

    @override_settings(IN_UNIT_TESTING=True)
    def test_shared_dashboard_tile_serializer_omits_widget_payload(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id, config={"limit": 10})
        tile = DashboardTile.objects.get(id=dashboard_json["tiles"][0]["id"])

        class ViewShim:
            action = "retrieve"

        context = {"view": ViewShim(), "order": 0}
        full_widget = DashboardTileSerializer(tile, context=context).data["widget"]
        assert full_widget is not None
        assert full_widget["created_by"] is not None

        shared_context = {**context, "is_shared": True}
        shared_widget = DashboardTileSerializer(tile, context=shared_context).data["widget"]
        assert shared_widget is not None
        assert set(shared_widget.keys()) == {"id", "widget_type", "name", "description", "config"}
        assert shared_widget["widget_type"] == "error_tracking_list"
        assert shared_widget["config"]["limit"] == 10


class TestDashboardWidgetsBatchUpdate(APIBaseTest):
    _WIDGETS_FLAG_PATCH_TARGETS = TestDashboardWidgets._WIDGETS_FLAG_PATCH_TARGETS

    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)
        self._widgets_flag_patchers = [patch(target, return_value=True) for target in self._WIDGETS_FLAG_PATCH_TARGETS]
        for patcher in self._widgets_flag_patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in self._widgets_flag_patchers:
            patcher.stop()
        super().tearDown()

    def _batch_update(self, dashboard_id: int, widgets: list[dict[str, Any]], team_id: int | None = None) -> Any:
        team_id = team_id or self.team.id
        return self.client.patch(
            f"/api/projects/{team_id}/dashboards/{dashboard_id}/widgets/batch_update/",
            {"widgets": widgets},
        )

    @override_settings(IN_UNIT_TESTING=True)
    def test_updates_widget_config_in_place(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(
            dashboard_id, config={"limit": 5, "orderBy": "last_seen"}
        )
        tile = dashboard_json["tiles"][0]

        response = self._batch_update(
            dashboard_id,
            [{"tile_id": tile["id"], "config": {"limit": 15, "orderBy": "occurrences"}}],
        )
        assert response.status_code == status.HTTP_200_OK

        updated_tile = response.json()["tiles"][0]
        assert updated_tile["widget"]["config"]["limit"] == 15
        assert updated_tile["widget"]["config"]["orderBy"] == "occurrences"
        # The widget row is edited in place, not recreated.
        assert updated_tile["widget"]["id"] == tile["widget"]["id"]
        assert updated_tile["id"] == tile["id"]

    @override_settings(IN_UNIT_TESTING=True)
    def test_updates_widget_name_and_description(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id)
        tile = dashboard_json["tiles"][0]

        response = self._batch_update(
            dashboard_id,
            [{"tile_id": tile["id"], "name": "My top errors", "description": "Worst issues this week"}],
        )
        assert response.status_code == status.HTTP_200_OK

        updated_tile = response.json()["tiles"][0]
        assert updated_tile["widget"]["name"] == "My top errors"
        assert updated_tile["widget"]["description"] == "Worst issues this week"

    @override_settings(IN_UNIT_TESTING=True)
    def test_partial_update_preserves_other_settings(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(
            dashboard_id, config={"limit": 5, "orderBy": "last_seen"}
        )
        tile = dashboard_json["tiles"][0]

        response = self._batch_update(dashboard_id, [{"tile_id": tile["id"], "name": "Renamed"}])
        assert response.status_code == status.HTTP_200_OK

        updated_tile = response.json()["tiles"][0]
        assert updated_tile["widget"]["name"] == "Renamed"
        assert updated_tile["widget"]["config"]["limit"] == 5
        assert updated_tile["widget"]["config"]["orderBy"] == "last_seen"

    @override_settings(IN_UNIT_TESTING=True)
    def test_sets_session_replay_saved_filter_id(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(
            dashboard_id, widget_type="session_replay_list", config={"limit": 5}
        )
        tile = dashboard_json["tiles"][0]

        response = self._batch_update(
            dashboard_id,
            [{"tile_id": tile["id"], "config": {"limit": 5, "savedFilterId": "abc123"}}],
        )
        assert response.status_code == status.HTTP_200_OK

        updated_tile = response.json()["tiles"][0]
        assert updated_tile["widget"]["config"]["savedFilterId"] == "abc123"

    @override_settings(IN_UNIT_TESTING=True)
    def test_updates_multiple_widgets_atomically(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        self.dashboard_api.create_widget_tile(dashboard_id, config={"limit": 5})
        self.dashboard_api.create_widget_tile(dashboard_id, config={"limit": 5})
        tiles = self.dashboard_api.get_dashboard(dashboard_id)["tiles"]
        assert len(tiles) == 2

        response = self._batch_update(
            dashboard_id,
            [
                {"tile_id": tiles[0]["id"], "config": {"limit": 11}},
                {"tile_id": tiles[1]["id"], "config": {"limit": 22}},
            ],
        )
        assert response.status_code == status.HTTP_200_OK

        limits = sorted(t["widget"]["config"]["limit"] for t in response.json()["tiles"])
        assert limits == [11, 22]

    @override_settings(IN_UNIT_TESTING=True)
    def test_batch_update_is_atomic(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        self.dashboard_api.create_widget_tile(dashboard_id, config={"limit": 5})
        self.dashboard_api.create_widget_tile(dashboard_id, config={"limit": 5})
        tiles = self.dashboard_api.get_dashboard(dashboard_id)["tiles"]

        # Second entry has an out-of-range limit; the whole batch must roll back.
        response = self._batch_update(
            dashboard_id,
            [
                {"tile_id": tiles[0]["id"], "config": {"limit": 15}},
                {"tile_id": tiles[1]["id"], "config": {"limit": 999}},
            ],
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        after = self.dashboard_api.get_dashboard(dashboard_id)["tiles"]
        assert all(t["widget"]["config"]["limit"] == 5 for t in after)

    @override_settings(IN_UNIT_TESTING=True)
    def test_cannot_change_widget_type(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id, config={"limit": 10})
        tile = dashboard_json["tiles"][0]

        response = self._batch_update(
            dashboard_id,
            [{"tile_id": tile["id"], "widget_type": "session_replay_list", "config": {"limit": 10}}],
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "widget_type cannot be changed" in response.json()["detail"]

    @override_settings(IN_UNIT_TESTING=True)
    def test_rejects_non_widget_tile(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        dashboard = Dashboard.objects.get(id=dashboard_id)
        insight = Insight.objects.create(team=self.team, name="an insight")
        insight_tile = DashboardTile.objects.create(
            dashboard=dashboard, team_id=self.team.id, insight=insight, layouts={}
        )

        response = self._batch_update(dashboard_id, [{"tile_id": insight_tile.id, "config": {"limit": 5}}])
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "not a widget tile" in response.json()["detail"]

    @override_settings(IN_UNIT_TESTING=True)
    def test_rejects_unknown_tile_id(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        response = self._batch_update(dashboard_id, [{"tile_id": 99999999, "config": {"limit": 5}}])
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @override_settings(IN_UNIT_TESTING=True)
    def test_cannot_update_tile_from_another_dashboard(self) -> None:
        dashboard_a, _ = self.dashboard_api.create_dashboard({"name": "a"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_a, config={"limit": 5})
        foreign_tile_id = dashboard_json["tiles"][0]["id"]
        dashboard_b, _ = self.dashboard_api.create_dashboard({"name": "b"})

        response = self._batch_update(dashboard_b, [{"tile_id": foreign_tile_id, "config": {"limit": 9}}])
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @override_settings(IN_UNIT_TESTING=True)
    def test_requires_feature_flag(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id, config={"limit": 5})
        tile = dashboard_json["tiles"][0]

        for patcher in self._widgets_flag_patchers:
            patcher.stop()
        try:
            with patch(
                "products.dashboards.backend.api.dashboard.dashboard_widgets_enabled",
                return_value=False,
            ):
                response = self._batch_update(dashboard_id, [{"tile_id": tile["id"], "config": {"limit": 9}}])
        finally:
            for patcher in self._widgets_flag_patchers:
                patcher.start()

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "not enabled" in response.json()["detail"].lower()

    @override_settings(IN_UNIT_TESTING=True)
    def test_rejects_empty_list(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})

        response = self._batch_update(dashboard_id, [])
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @override_settings(IN_UNIT_TESTING=True)
    def test_does_not_touch_tile_placement(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id, config={"limit": 5})
        tile = dashboard_json["tiles"][0]
        layout = {"sm": {"x": 0, "y": 3, "w": 6, "h": 4}}
        self.client.patch(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}",
            {"tiles": [{"id": tile["id"], "layouts": layout}]},
        )

        response = self._batch_update(dashboard_id, [{"tile_id": tile["id"], "config": {"limit": 12}}])
        assert response.status_code == status.HTTP_200_OK

        after = self.dashboard_api.get_dashboard(dashboard_id)["tiles"][0]
        assert after["widget"]["config"]["limit"] == 12
        assert after["layouts"] == layout

    @override_settings(IN_UNIT_TESTING=True)
    @patch("products.dashboards.backend.api.dashboard.report_user_action")
    def test_update_does_not_fire_tile_added_event(self, mock_report_user_action) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id, config={"limit": 5})
        tile = dashboard_json["tiles"][0]
        mock_report_user_action.reset_mock()

        response = self._batch_update(dashboard_id, [{"tile_id": tile["id"], "config": {"limit": 15}}])
        assert response.status_code == status.HTTP_200_OK

        for call in mock_report_user_action.call_args_list:
            assert call[0][1] != "dashboard tile added"
            assert call[0][1] != "dashboard widget added"

    @override_settings(IN_UNIT_TESTING=True)
    @patch("products.dashboards.backend.api.dashboard.report_user_action")
    def test_update_fires_widget_updated_event(self, mock_report_user_action) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id, config={"limit": 5})
        tile = dashboard_json["tiles"][0]
        mock_report_user_action.reset_mock()

        response = self._batch_update(dashboard_id, [{"tile_id": tile["id"], "name": "Renamed"}])
        assert response.status_code == status.HTTP_200_OK

        updated_events = [
            call for call in mock_report_user_action.call_args_list if call[0][1] == "dashboard widget updated"
        ]
        assert len(updated_events) == 1
        properties = updated_events[0][0][2]
        assert properties["tile_id"] == tile["id"]
        assert properties["fields_changed"] == ["name"]

    @override_settings(IN_UNIT_TESTING=True)
    def test_denies_without_edit_permission(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id, config={"limit": 5})
        tile = dashboard_json["tiles"][0]

        with patch(
            "posthog.user_permissions.UserDashboardPermissions.can_edit",
            new_callable=PropertyMock,
            return_value=False,
        ):
            response = self._batch_update(dashboard_id, [{"tile_id": tile["id"], "config": {"limit": 9}}])

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @override_settings(IN_UNIT_TESTING=True)
    def test_rejects_update_on_deleted_dashboard(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id, config={"limit": 5})
        tile = dashboard_json["tiles"][0]
        Dashboard.objects.filter(id=dashboard_id).update(deleted=True)

        response = self._batch_update(dashboard_id, [{"tile_id": tile["id"], "config": {"limit": 9}}])
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @override_settings(IN_UNIT_TESTING=True)
    def test_denies_without_product_access(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_widget_tile(dashboard_id, config={"limit": 10})
        tile = dashboard_json["tiles"][0]

        real_check = UserAccessControl.check_access_level_for_resource

        def deny_error_tracking_only(
            user_access_control: UserAccessControl,
            resource: APIScopeObject,
            required_level: AccessControlLevel = "viewer",
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
            response = self._batch_update(dashboard_id, [{"tile_id": tile["id"], "config": {"limit": 12}}])

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"] == "You do not have access to error tracking."


class TestDashboardWidgetOpenApiSchema(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)
        self._widgets_flag_patchers = [
            patch(target, return_value=True) for target in TestDashboardWidgets._WIDGETS_FLAG_PATCH_TARGETS
        ]
        for patcher in self._widgets_flag_patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in self._widgets_flag_patchers:
            patcher.stop()
        super().tearDown()

    def test_add_dashboard_widget_openapi_schema_uses_widget_type_discriminator(self) -> None:
        schema = SchemaGenerator().get_schema(request=None, public=True)
        component = schema["components"]["schemas"]["AddDashboardWidgetRequest"]

        assert component["discriminator"]["propertyName"] == "widget_type"
        assert set(component["discriminator"]["mapping"].keys()) == set(EXPECTED_WIDGET_TYPES)

    def test_update_dashboard_widget_openapi_schema_uses_widget_type_discriminator(self) -> None:
        schema = SchemaGenerator().get_schema(request=None, public=True)
        component = schema["components"]["schemas"]["UpdateDashboardWidgetRequest"]

        assert component["discriminator"]["propertyName"] == "widget_type"
        assert set(component["discriminator"]["mapping"].keys()) == set(EXPECTED_WIDGET_TYPES)

    def test_batch_add_rejects_unknown_widget_type(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash"})
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/widgets/batch/",
            {"widgets": [{"widget_type": "not_a_real_widget", "config": {"limit": 5}}]},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
