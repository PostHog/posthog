from datetime import timedelta

import pytest
from posthog.test.base import APIBaseTest

from django.utils import timezone

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.access_control.backend.models.access_control import AccessControl
from products.dashboards.backend.facade import api
from products.dashboards.backend.facade.contracts import DashboardSummary
from products.dashboards.backend.facade.enums import DashboardCreationMode
from products.dashboards.backend.facade.testing import (
    create_dashboard,
    create_insight_tile,
    create_text_tile,
    insight_tile_is_deleted,
)
from products.dashboards.backend.models.dashboard import Dashboard
from products.product_analytics.backend.facade.models import Insight


class TestDashboardReads(APIBaseTest):
    def test_get_dashboard_maps_every_field(self) -> None:
        opened = timezone.now() - timedelta(days=1)
        dashboard_id = create_dashboard(
            team_id=self.team.id,
            name="Growth",
            description="Weekly numbers",
            created_by_id=self.user.id,
            pinned=True,
            creation_mode=DashboardCreationMode.TEMPLATE,
            last_accessed_at=opened,
            filters={"date_from": "-7d"},
            variables={"v": {"code_name": "v"}},
        )
        created_at = Dashboard.objects.get(id=dashboard_id).created_at

        assert api.get_dashboard(team_id=self.team.id, dashboard_id=dashboard_id) == DashboardSummary(
            id=dashboard_id,
            team_id=self.team.id,
            name="Growth",
            description="Weekly numbers",
            created_at=created_at,
            created_by_id=self.user.id,
            deleted=False,
            pinned=True,
            creation_mode=DashboardCreationMode.TEMPLATE,
            last_accessed_at=opened,
            last_refresh=None,
            filters={"date_from": "-7d"},
            variables={"v": {"code_name": "v"}},
        )

    @parameterized.expand(
        [
            ("live", False, False, True),
            ("soft_deleted_hidden_by_default", True, False, False),
            ("soft_deleted_found_on_request", True, True, True),
        ]
    )
    def test_get_dashboard_counts_a_soft_deleted_dashboard_only_on_request(
        self, _name: str, deleted: bool, include_deleted: bool, found: bool
    ) -> None:
        dashboard_id = create_dashboard(team_id=self.team.id, deleted=deleted)

        summary = api.get_dashboard(team_id=self.team.id, dashboard_id=dashboard_id, include_deleted=include_deleted)
        many = api.get_dashboards(team_id=self.team.id, dashboard_ids=[dashboard_id], include_deleted=include_deleted)

        assert (summary is not None, dashboard_id in many) == (found, found)

    def test_reads_are_scoped_to_the_team_and_its_project(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        theirs = create_dashboard(team_id=other_team.id)
        environment = Team.objects.create(organization=self.organization, parent_team=self.team)
        ours = create_dashboard(team_id=self.team.id)

        assert api.get_dashboard(team_id=self.team.id, dashboard_id=theirs) is None
        assert api.live_dashboard_ids(team_id=self.team.id, dashboard_ids=[ours, theirs]) == {ours}
        # An environment reads its project's dashboards, which are stored on the project's root team.
        assert api.get_dashboard(team_id=environment.id, dashboard_id=ours) is not None

    def test_recently_accessed_dashboards_lists_opened_live_dashboards_newest_first(self) -> None:
        now = timezone.now()
        older = create_dashboard(team_id=self.team.id, last_accessed_at=now - timedelta(days=2))
        newer = create_dashboard(team_id=self.team.id, last_accessed_at=now - timedelta(hours=1))
        create_dashboard(team_id=self.team.id, last_accessed_at=now, deleted=True)
        create_dashboard(team_id=self.team.id)

        assert [d.id for d in api.recently_accessed_dashboards(team_id=self.team.id, limit=5)] == [newer, older]
        assert [d.id for d in api.recently_accessed_dashboards(team_id=self.team.id, limit=1)] == [newer]


@pytest.mark.ee
class TestDashboardReadsUnderAccessControl(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        now = timezone.now()
        self.visible = create_dashboard(team_id=self.team.id, last_accessed_at=now - timedelta(days=1))
        self.hidden = create_dashboard(team_id=self.team.id, last_accessed_at=now)
        AccessControl.objects.create(
            team=self.team, resource="dashboard", resource_id=str(self.hidden), access_level="none"
        )
        self.access = UserAccessControl(user=self.user, team=self.team)

    def test_listing_leaves_out_a_dashboard_the_user_may_not_view(self) -> None:
        assert api.viewable_dashboard_ids(
            team_id=self.team.id, dashboard_ids=[self.visible, self.hidden], user_access_control=self.access
        ) == {self.visible}
        # The hidden dashboard was opened last, so it would take the only slot if it were counted.
        recent = api.recently_accessed_dashboards(team_id=self.team.id, limit=1, user_access_control=self.access)
        assert [d.id for d in recent] == [self.visible]

    def test_access_ref_resolves_like_the_dashboard_row(self) -> None:
        for dashboard_id in (self.visible, self.hidden):
            ref = api.dashboard_access_ref(team_id=self.team.id, dashboard_id=dashboard_id)
            assert ref is not None
            row = Dashboard.objects.get(id=dashboard_id)
            assert self.access.check_access_level_for_ref(ref, "viewer") == self.access.check_access_level_for_object(
                row, "viewer"
            )

    def test_access_ref_is_none_for_a_soft_deleted_dashboard(self) -> None:
        gone = create_dashboard(team_id=self.team.id, deleted=True)

        assert api.dashboard_access_ref(team_id=self.team.id, dashboard_id=gone) is None


class TestInsightTileReads(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard = create_dashboard(team_id=self.team.id)
        self.first = Insight.objects.create(team=self.team, name="first")
        self.second = Insight.objects.create(team=self.team, name="second")
        self.removed = Insight.objects.create(team=self.team, name="removed tile")
        self.deleted = Insight.objects.create(team=self.team, name="deleted insight", deleted=True)
        self.first_tile = create_insight_tile(
            dashboard_id=self.dashboard, insight_id=self.first.id, filters_overrides={"date_from": "-30d"}
        )
        create_text_tile(dashboard_id=self.dashboard, body="notes")
        self.second_tile = create_insight_tile(
            dashboard_id=self.dashboard, insight_id=self.second.id, layouts={"sm": {"x": 0, "y": 0, "w": 6, "h": 5}}
        )
        create_insight_tile(dashboard_id=self.dashboard, insight_id=self.removed.id, deleted=True)
        create_insight_tile(dashboard_id=self.dashboard, insight_id=self.deleted.id)

    def test_insight_tiles_lists_live_tiles_of_live_insights_oldest_first(self) -> None:
        tiles = api.insight_tiles(dashboard_id=self.dashboard)

        assert [(t.id, t.insight_id, t.layouts, t.filters_overrides) for t in tiles] == [
            (self.first_tile, self.first.id, {}, {"date_from": "-30d"}),
            (self.second_tile, self.second.id, {"sm": {"x": 0, "y": 0, "w": 6, "h": 5}}, {}),
        ]

    def test_insight_tiles_is_empty_for_a_soft_deleted_dashboard(self) -> None:
        Dashboard.objects.filter(id=self.dashboard).update(deleted=True)

        assert api.insight_tiles(dashboard_id=self.dashboard) == []

    def test_insight_ids_ever_on_dashboards_matches_the_insight_dashboards_relation(self) -> None:
        relation = Insight.objects_including_soft_deleted.filter(dashboards__in=[self.dashboard])

        assert api.insight_ids_ever_on_dashboards([self.dashboard]) == set(relation.values_list("id", flat=True))
        assert api.insight_ids_ever_on_dashboards([self.dashboard]) == {
            self.first.id,
            self.second.id,
            self.removed.id,
            self.deleted.id,
        }

    @parameterized.expand([("live_tile", "first", {"date_from": "-30d"}), ("removed_tile", "removed", None)])
    def test_tile_filters_overrides_reads_only_a_live_tile(
        self, _name: str, insight_attr: str, expected: dict | None
    ) -> None:
        insight = getattr(self, insight_attr)

        assert api.tile_filters_overrides(dashboard_id=self.dashboard, insight_id=insight.id) == expected

    def test_restoring_without_access_check_skips_tiles_on_deleted_dashboards(self) -> None:
        deleted_dashboard = create_dashboard(team_id=self.team.id, deleted=True)
        create_insight_tile(dashboard_id=deleted_dashboard, insight_id=self.removed.id, deleted=True)

        api.restore_tiles_for_insights_without_access_check([self.removed.id])

        assert insight_tile_is_deleted(dashboard_id=self.dashboard, insight_id=self.removed.id) is False
        assert insight_tile_is_deleted(dashboard_id=deleted_dashboard, insight_id=self.removed.id) is True
