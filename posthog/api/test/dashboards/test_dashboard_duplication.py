import pytest
from posthog.test.base import APIBaseTest, QueryMatchingTest

from parameterized import parameterized
from rest_framework import status

from posthog.api.test.dashboards import DashboardAPI
from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


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

    def test_deep_duplicate_copies_filters_overrides_and_show_description(self) -> None:
        dashboard_id, _ = self.dashboard_api.create_dashboard({})
        self.dashboard_api.create_insight({"dashboards": [dashboard_id]})

        dashboard_json = self.dashboard_api.get_dashboard(dashboard_id)
        insight_tile = next(t for t in dashboard_json["tiles"] if t["insight"] is not None)

        # Set filters_overrides and show_description on the tile
        filters_overrides = {"date_from": "-7d"}
        insight_tile["filters_overrides"] = filters_overrides
        insight_tile["show_description"] = True
        self.dashboard_api.update_dashboard(dashboard_id, {"tiles": [insight_tile]})

        duplicated = self.client.post(
            f"/api/projects/{self.team.id}/dashboards/",
            {"duplicate_tiles": True, "use_dashboard": dashboard_id, "name": "dup"},
        ).json()

        original_tile_ids = {t["id"] for t in dashboard_json["tiles"]}
        new_tiles = [t for t in duplicated["tiles"] if t["id"] not in original_tile_ids]
        new_insight_tile = next(t for t in new_tiles if t["insight"] is not None)

        assert new_insight_tile["filters_overrides"] == filters_overrides
        assert new_insight_tile["show_description"] is True

    @staticmethod
    def _tile_child_ids_from(dashboard_json: dict) -> list[int]:
        child_ids: list[int] = []
        for tile in dashboard_json["tiles"]:
            child_id = (tile.get("insight", None) or {}).get("id", None) or (tile.get("text", None) or {}).get(
                "id", None
            )
            if child_id is not None:
                child_ids.append(child_id)
        return child_ids


@pytest.mark.ee
class TestDashboardDuplicationAccessControl(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()

        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)
        self.dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "secret"})
        self.insight_id, _ = self.dashboard_api.create_insight(
            {"dashboards": [self.dashboard_id], "name": "confidential"}
        )

        self.member = User.objects.create_and_join(self.organization, "member@posthog.com", "testtest")
        self.membership = OrganizationMembership.objects.get(user=self.member, organization=self.organization)

    def _set_access(self, resource: str, resource_id: int, access_level: str) -> None:
        AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=str(resource_id),
            access_level=access_level,
            organization_member=self.membership,
        )

    def _duplicate(self) -> int:
        return self.client.post(
            f"/api/projects/{self.team.id}/dashboards/",
            {"name": "copy", "use_dashboard": self.dashboard_id, "duplicate_tiles": True},
        ).status_code

    @parameterized.expand(
        [
            ("none", status.HTTP_403_FORBIDDEN),
            ("viewer", status.HTTP_201_CREATED),
        ]
    )
    def test_duplication_requires_viewer_access_to_source_dashboard(
        self, access_level: str, expected_status: int
    ) -> None:
        self._set_access("dashboard", self.dashboard_id, access_level)
        self.client.force_login(self.member)

        assert self._duplicate() == expected_status

    def test_denied_source_dashboard_also_blocks_direct_retrieve(self) -> None:
        # Baseline: the duplication block is a back door around this denied retrieve.
        self._set_access("dashboard", self.dashboard_id, "none")
        self.client.force_login(self.member)

        retrieve_status = self.client.get(f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/").status_code
        assert retrieve_status == status.HTTP_403_FORBIDDEN

    def test_duplication_requires_viewer_access_to_each_insight(self) -> None:
        # Dashboard is viewable, but an individual insight is explicitly restricted.
        self._set_access("dashboard", self.dashboard_id, "viewer")
        self._set_access("insight", self.insight_id, "none")
        self.client.force_login(self.member)

        assert self._duplicate() == status.HTTP_403_FORBIDDEN
