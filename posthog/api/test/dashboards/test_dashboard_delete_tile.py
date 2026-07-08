from posthog.test.base import APIBaseTest
from unittest.mock import ANY, patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.api.test.dashboards import DashboardAPI

from products.dashboards.backend.models.dashboard_tile import DashboardTile


@override_settings(IN_UNIT_TESTING=True)
class TestDashboardDeleteTile(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

    def _delete_tile(self, dashboard_id: int, tile_id: int, expected_status: int = status.HTTP_204_NO_CONTENT):
        response = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/delete_tile",
            {"tile_id": tile_id},
        )
        self.assertEqual(response.status_code, expected_status, response.content)
        return response

    def test_can_delete_a_text_tile(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="hello world")
        _, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="second tile")

        tile_to_delete = dashboard_json["tiles"][0]
        self._delete_tile(dashboard_id, tile_to_delete["id"])

        remaining = self.dashboard_api.get_dashboard(dashboard_id)["tiles"]
        assert len(remaining) == 1
        assert remaining[0]["id"] != tile_to_delete["id"]

        tile = DashboardTile.objects_including_soft_deleted.get(id=tile_to_delete["id"])
        assert tile.deleted is True
        assert tile.text is not None

    def test_can_delete_an_insight_tile_without_deleting_the_insight(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        insight_id, _ = self.dashboard_api.create_insight({"name": "insight", "dashboards": [dashboard_id]})

        dashboard_json = self.dashboard_api.get_dashboard(dashboard_id)
        assert len(dashboard_json["tiles"]) == 1
        tile_id = dashboard_json["tiles"][0]["id"]

        self._delete_tile(dashboard_id, tile_id)

        assert self.dashboard_api.get_dashboard(dashboard_id)["tiles"] == []
        insight_response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight_id}")
        assert insight_response.status_code == status.HTTP_200_OK

    def _create_text_tile_for_removal(self, dashboard_id: int) -> int:
        _, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="hello world")
        return dashboard_json["tiles"][0]["id"]

    def _create_insight_tile_for_removal(self, dashboard_id: int) -> int:
        self.dashboard_api.create_insight({"name": "insight", "dashboards": [dashboard_id]})
        return self.dashboard_api.get_dashboard(dashboard_id)["tiles"][0]["id"]

    @parameterized.expand(
        [
            ("text", _create_text_tile_for_removal, {"tile_type": "text", "insight_type": None}),
            ("insight", _create_insight_tile_for_removal, {"tile_type": "insight", "insight_type": "trends"}),
        ]
    )
    @patch("products.dashboards.backend.api.dashboard.report_user_action")
    def test_delete_tile_fires_tile_removed_event(
        self, _name, create_tile, expected_properties, mock_report_user_action
    ) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        tile_id = create_tile(self, dashboard_id)
        mock_report_user_action.reset_mock()

        self._delete_tile(dashboard_id, tile_id)

        mock_report_user_action.assert_any_call(
            self.user,
            "dashboard tile removed",
            {**expected_properties, "dashboard_id": dashboard_id},
            team=ANY,
            request=ANY,
        )

    def _setup_unknown_tile_id(self) -> tuple[int, int]:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        return dashboard_id, 9_999_999

    def _setup_tile_from_other_dashboard(self) -> tuple[int, int]:
        dashboard_a, _ = self.dashboard_api.create_dashboard({"name": "a"})
        dashboard_b, _ = self.dashboard_api.create_dashboard({"name": "b"})
        _, dashboard_json = self.dashboard_api.create_text_tile(dashboard_a, text="on a")
        tile_id = dashboard_json["tiles"][0]["id"]
        return dashboard_b, tile_id

    def _setup_parent_dashboard_soft_deleted(self) -> tuple[int, int]:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="hi")
        tile_id = dashboard_json["tiles"][0]["id"]
        self.client.patch(f"/api/projects/{self.team.id}/dashboards/{dashboard_id}", {"deleted": True})
        return dashboard_id, tile_id

    def _setup_tile_already_soft_deleted(self) -> tuple[int, int]:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="hi")
        tile_id = dashboard_json["tiles"][0]["id"]
        self._delete_tile(dashboard_id, tile_id)
        return dashboard_id, tile_id

    @parameterized.expand(
        [
            ("unknown_tile_id", _setup_unknown_tile_id),
            ("tile_belongs_to_other_dashboard", _setup_tile_from_other_dashboard),
            ("parent_dashboard_soft_deleted", _setup_parent_dashboard_soft_deleted),
            ("tile_already_soft_deleted", _setup_tile_already_soft_deleted),
        ]
    )
    def test_delete_returns_404(self, _name, setup) -> None:
        dashboard_id, tile_id = setup(self)
        self._delete_tile(dashboard_id, tile_id, expected_status=status.HTTP_404_NOT_FOUND)

    def test_delete_tile_requires_tile_id(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        response = self.client.post(f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/delete_tile", {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_tile_compacts_remaining_layout(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="top")
        _, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="middle")
        _, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="bottom")

        tile_ids = [tile["id"] for tile in dashboard_json["tiles"]]
        for index, tile_id in enumerate(tile_ids):
            DashboardTile.objects.filter(id=tile_id).update(
                layouts={
                    "sm": {"x": 0, "y": index * 5, "w": 6, "h": 5},
                    "xs": {"x": 0, "y": index * 5, "w": 6, "h": 5},
                }
            )

        # Remove the middle tile (y=5); the bottom tile should slide up into the gap.
        self._delete_tile(dashboard_id, tile_ids[1])

        top = DashboardTile.objects.get(id=tile_ids[0])
        bottom = DashboardTile.objects.get(id=tile_ids[2])
        assert top.layouts["sm"] == {"x": 0, "y": 0, "w": 6, "h": 5}
        # Compaction preserves x/w/h and only pulls y up to close the gap (10 -> 5).
        assert bottom.layouts["sm"] == {"x": 0, "y": 5, "w": 6, "h": 5}
        assert bottom.layouts["xs"] == {"x": 0, "y": 5, "w": 6, "h": 5}

    def test_delete_tile_compacts_per_column_without_disturbing_other_columns(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="left top")
        _, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="right top")
        _, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="left middle")
        _, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="right gapped")

        tile_ids = [tile["id"] for tile in dashboard_json["tiles"]]
        layouts = [
            {"x": 0, "y": 0, "w": 6, "h": 5},  # left top
            {"x": 6, "y": 0, "w": 6, "h": 5},  # right top
            {"x": 0, "y": 5, "w": 6, "h": 5},  # left middle (to be deleted)
            {"x": 6, "y": 10, "w": 6, "h": 5},  # right column, with a gap at rows 5-9
        ]
        for tile_id, layout in zip(tile_ids, layouts):
            DashboardTile.objects.filter(id=tile_id).update(layouts={"sm": layout, "xs": {**layout, "x": 0, "w": 1}})

        self._delete_tile(dashboard_id, tile_ids[2])

        left_top = DashboardTile.objects.get(id=tile_ids[0])
        right_top = DashboardTile.objects.get(id=tile_ids[1])
        right_gapped = DashboardTile.objects.get(id=tile_ids[3])
        # Untouched tiles keep their exact positions; the right column's gap closes (10 -> 5),
        # which is only correct if the overlap check keeps it in its own column (x stays 6).
        assert left_top.layouts["sm"] == {"x": 0, "y": 0, "w": 6, "h": 5}
        assert right_top.layouts["sm"] == {"x": 6, "y": 0, "w": 6, "h": 5}
        assert right_gapped.layouts["sm"] == {"x": 6, "y": 5, "w": 6, "h": 5}

    def test_delete_tile_leaves_tiles_without_layouts_alone(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dashboard"})
        _, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="positioned")
        _, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="unpositioned")
        _, dashboard_json = self.dashboard_api.create_text_tile(dashboard_id, text="to delete")

        tile_ids = [tile["id"] for tile in dashboard_json["tiles"]]
        DashboardTile.objects.filter(id=tile_ids[0]).update(layouts={"sm": {"x": 0, "y": 10, "w": 6, "h": 5}})
        DashboardTile.objects.filter(id=tile_ids[1]).update(layouts={})

        self._delete_tile(dashboard_id, tile_ids[2])

        positioned = DashboardTile.objects.get(id=tile_ids[0])
        unpositioned = DashboardTile.objects.get(id=tile_ids[1])
        assert positioned.layouts["sm"] == {"x": 0, "y": 0, "w": 6, "h": 5}
        assert unpositioned.layouts == {}
