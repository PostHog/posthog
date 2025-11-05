from posthog.test.base import APIBaseTest, QueryMatchingTest

from posthog.api.test.dashboards import DashboardAPI


class TestDashboardDuplication(APIBaseTest, QueryMatchingTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

        self.tile_layout = {"tile_layout": "here"}
        self.tile_color = "red"

        dashboard_id, _ = self.dashboard_api.create_dashboard({})

        self.dashboard_api.create_text_tile(
            dashboard_id,
            extra_data={"layouts": self.tile_layout, "color": self.tile_color},
        )

        self.dashboard_api.create_insight({"dashboards": [dashboard_id]})

        dashboard_json_to_update = self.dashboard_api.get_dashboard(dashboard_id)

        insight_tile = next(t for t in dashboard_json_to_update["tiles"] if t["insight"] is not None)
        insight_tile["layouts"] = self.tile_layout
        insight_tile["color"] = self.tile_color

        self.dashboard_api.update_dashboard(dashboard_id, {"tiles": [insight_tile]})

        self.starting_dashboard = self.dashboard_api.get_dashboard(dashboard_id)

        self.tile_ids = [tile["id"] for tile in self.starting_dashboard["tiles"]]
        self.original_child_ids = self._tile_child_ids_from(self.starting_dashboard)

    def test_duplicating_dashboard_while_duplicating_tiles(self) -> None:
        duplicated_dashboard = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/",
            {
                "duplicate_tiles": True,
                "use_dashboard": self.starting_dashboard["id"],
                "name": "new",
            },
        ).json()

        # Get only the tiles that match our original dashboard's tiles
        original_tile_ids = set(self.tile_ids)
        duplicated_tiles = [tile for tile in duplicated_dashboard["tiles"] if tile["id"] not in original_tile_ids]

        assert len(duplicated_tiles) == 2
        # always makes new tiles
        assert [tile["id"] for tile in duplicated_tiles] != self.tile_ids
        # makes new children
        assert sorted(self.original_child_ids) != sorted(self._tile_child_ids_from({"tiles": duplicated_tiles}))

        assert [tile["color"] for tile in duplicated_tiles] == [
            self.tile_color,
            self.tile_color,
        ]
        assert [tile["layouts"] for tile in duplicated_tiles] == [
            self.tile_layout,
            self.tile_layout,
        ]

    def test_duplicating_dashboard_without_duplicating_tiles(self) -> None:
        duplicated_dashboard = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/",
            {
                "duplicate_tiles": False,
                "use_dashboard": self.starting_dashboard["id"],
                "name": "new",
            },
        ).json()

        # Get only the tiles that match our original dashboard's tiles
        original_tile_ids = set(self.tile_ids)
        duplicated_tiles = [tile for tile in duplicated_dashboard["tiles"] if tile["id"] not in original_tile_ids]

        assert len(duplicated_tiles) == 2
        # always makes new tiles
        assert [tile["id"] for tile in duplicated_tiles] != self.tile_ids
        # uses existing children
        assert sorted(self.original_child_ids) == sorted(self._tile_child_ids_from({"tiles": duplicated_tiles}))

        assert [tile["color"] for tile in duplicated_tiles] == [
            self.tile_color,
            self.tile_color,
        ]
        assert [tile["layouts"] for tile in duplicated_tiles] == [
            self.tile_layout,
            self.tile_layout,
        ]

    @staticmethod
    def _tile_child_ids_from(dashboard_json: dict) -> list[int]:
        return [
            (tile.get("insight", None) or {}).get("id", None) or (tile.get("text", None) or {}).get("id", None)
            for tile in dashboard_json["tiles"]
        ]
