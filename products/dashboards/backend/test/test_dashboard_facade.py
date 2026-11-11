from datetime import timedelta
from enum import StrEnum
from typing import Any

import pytest
from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.team import Team

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.access_control.backend.models.access_control import AccessControl
from products.dashboards.backend.facade import api
from products.dashboards.backend.facade.access import record_dashboard_view
from products.dashboards.backend.facade.contracts import (
    AppliedDashboard,
    DashboardExtras,
    DashboardSummary,
    DashboardTemplateDefinition,
    InsightPlacement,
    TeamDashboardRef,
    TilePlacement,
)
from products.dashboards.backend.facade.enums import (
    DashboardAccessMethod,
    DashboardCreationMode,
    DashboardTemplateScope,
    DashboardUsageCount,
)
from products.dashboards.backend.facade.testing import (
    create_dashboard,
    create_dashboard_template,
    create_insight_tile,
    create_text_tile,
    create_widget_tile,
    dashboard_access_count,
    dashboard_extras,
    global_dashboard_template_exists,
    home_tab_config_exists,
    insight_tile_is_deleted,
    tile_ids,
    update_dashboard,
)
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_templates import DashboardTemplate
from products.product_analytics.backend.facade.models import Insight


def _applied(dashboard: AppliedDashboard) -> tuple[int, dict[str, Any], dict[str, Any] | None]:
    return dashboard.id, dashboard.filters, dashboard.variables


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
        row = Dashboard.objects.get(id=dashboard_id)
        created_at = row.created_at
        summary = api.get_dashboard(team_id=self.team.id, dashboard_id=dashboard_id)

        # The contract and the row both satisfy `AppliedDashboard`, so a caller can switch between them.
        assert summary is not None
        assert _applied(summary) == _applied(row) == (dashboard_id, {"date_from": "-7d"}, {"v": {"code_name": "v"}})
        assert summary == DashboardSummary(
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

    @parameterized.expand([("project_team", False), ("environment", True)])
    def test_listing_leaves_out_a_dashboard_the_user_may_not_view(self, _name: str, via_environment: bool) -> None:
        team = (
            Team.objects.create(organization=self.organization, parent_team=self.team) if via_environment else self.team
        )
        access = UserAccessControl(user=self.user, team=team)

        assert api.viewable_dashboard_ids(
            team_id=team.id, dashboard_ids=[self.visible, self.hidden], user_access_control=access
        ) == {self.visible}
        # The hidden dashboard was opened last, so it would take the only slot if it were counted.
        recent = api.recently_accessed_dashboards(team_id=team.id, limit=1, user_access_control=access)
        assert [d.id for d in recent] == [self.visible]

    def test_search_and_last_access_listing_leave_out_a_dashboard_the_user_may_not_view(self) -> None:
        by_last_access = api.dashboards_by_last_access(
            team_ids=[self.team.id], user_access_control=self.access, limit=1
        )
        found, count = api.search_dashboards(
            project_id=self.team.project_id, query=None, access_control=self.access, limit=10, with_access_levels=True
        )

        # The hidden dashboard was opened last, so it would take the only slot if it were counted.
        assert [d.id for d in by_last_access] == [self.visible]
        assert ([r["result_id"] for r in found], count) == ([str(self.visible)], 1)
        assert found[0]["user_access_level"] == self.access.get_user_access_level(
            Dashboard.objects.get(id=self.visible)
        )

    def test_access_checks_resolve_like_the_dashboard_row(self) -> None:
        environment = Team.objects.create(organization=self.organization, parent_team=self.team)
        environment_access = UserAccessControl(user=self.user, team=environment)
        for dashboard_id in (self.visible, self.hidden):
            row = Dashboard.objects.get(id=dashboard_id)
            expected = self.access.check_access_level_for_object(row, "viewer")
            ref = api.dashboard_access_ref(team_id=self.team.id, dashboard_id=dashboard_id)
            assert ref is not None
            assert self.access.check_access_level_for_ref(ref, "viewer") == expected
            # Bound to an environment, the check still reads the rules of the project's team.
            summary = api.get_dashboard(team_id=environment.id, dashboard_id=dashboard_id)
            assert summary is not None
            assert api.can_access_dashboard(summary, user_access_control=environment_access) == expected
            assert environment_access.check_access_level_for_object(row, "viewer") == expected

    @parameterized.expand([("soft_deleted", True, False), ("found_through_an_environment", False, True)])
    def test_access_ref_is_none_unless_the_dashboard_is_live_on_that_team(
        self, _name: str, deleted: bool, via_environment: bool
    ) -> None:
        dashboard_id = create_dashboard(team_id=self.team.id, deleted=deleted)
        team_id = (
            Team.objects.create(organization=self.organization, parent_team=self.team).id
            if via_environment
            else self.team.id
        )

        assert api.dashboard_access_ref(team_id=team_id, dashboard_id=dashboard_id) is None


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

    def test_insight_ids_on_dashboard_with_removed_tiles_matches_the_insight_dashboards_relation(self) -> None:
        relation = Insight.objects_including_soft_deleted.filter(dashboards__in=[self.dashboard])
        on_dashboard = Insight.objects_including_soft_deleted.filter(
            id__in=api.insight_ids_on_dashboard(self.dashboard, include_removed_tiles=True)
        )

        assert set(on_dashboard.values_list("id", flat=True)) == set(relation.values_list("id", flat=True))
        assert self.removed.id in set(on_dashboard.values_list("id", flat=True))

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


class TestDashboardSearch(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.access = UserAccessControl(user=self.user, team=self.team)
        self.revenue = create_dashboard(team_id=self.team.id, name="Revenue", description="Money in")
        self.unnamed = create_dashboard(team_id=self.team.id, name=None)
        self.churn = create_dashboard(team_id=self.team.id, name="Churn", description="Revenue lost")
        create_dashboard(team_id=self.team.id, name="Revenue copy", creation_mode=DashboardCreationMode.TEMPLATE)
        create_dashboard(team_id=self.team.id, name="Revenue old", deleted=True)
        create_dashboard(team_id=Team.objects.create(organization=self.organization).id, name="Revenue elsewhere")

    def test_without_a_query_lists_the_project_dashboards_in_name_order(self) -> None:
        results, count = api.search_dashboards(
            project_id=self.team.project_id, query=None, access_control=self.access, limit=10
        )

        assert count == 3
        assert results == [
            {"type": "dashboard", "result_id": str(self.unnamed), "extra_fields": {"name": None, "description": ""}},
            {
                "type": "dashboard",
                "result_id": str(self.churn),
                "extra_fields": {"name": "Churn", "description": "Revenue lost"},
            },
            {
                "type": "dashboard",
                "result_id": str(self.revenue),
                "extra_fields": {"name": "Revenue", "description": "Money in"},
            },
        ]

    def test_a_query_ranks_a_name_match_above_a_description_match(self) -> None:
        results, count = api.search_dashboards(
            project_id=self.team.project_id, query="revenue", access_control=self.access, limit=10, include_count=False
        )

        assert [r["result_id"] for r in results] == [str(self.revenue), str(self.churn)]
        assert results[0]["rank"] > results[1]["rank"]
        assert count == 0


class TestDashboardTeamSettings(APIBaseTest):
    @parameterized.expand(
        [("live", False, False, True), ("soft_deleted", True, False, False), ("other_team", False, True, False)]
    )
    def test_home_tab_dashboard_reads_like_the_team_property(
        self, _name: str, deleted: bool, other_team: bool, shown: bool
    ) -> None:
        team_id = Team.objects.create(organization=self.organization).id if other_team else self.team.id
        dashboard_id = create_dashboard(team_id=team_id, deleted=deleted)

        api.set_home_tab_dashboard(team_id=self.team.id, dashboard_id=dashboard_id)

        team = Team.objects.get(id=self.team.id)
        assert api.home_tab_dashboard_id(team_id=self.team.id) == (dashboard_id if shown else None)
        assert (team.home_tab_dashboard.id if team.home_tab_dashboard else None) == (dashboard_id if shown else None)

    def test_clearing_the_home_tab_dashboard_keeps_the_config_row(self) -> None:
        api.set_home_tab_dashboard(team_id=self.team.id, dashboard_id=create_dashboard(team_id=self.team.id))

        api.set_home_tab_dashboard(team_id=self.team.id, dashboard_id=None)

        assert api.home_tab_dashboard_id(team_id=self.team.id) is None
        assert home_tab_config_exists(team_id=self.team.id)

    def test_removing_a_quick_filter_rewrites_only_this_team_dashboards_that_hold_it(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        dashboards = [
            create_dashboard(team_id=self.team.id, quick_filter_ids=["a", "gone", "b"]),
            create_dashboard(team_id=self.team.id, quick_filter_ids=["gone"]),
            create_dashboard(team_id=self.team.id, quick_filter_ids=["a"]),
            create_dashboard(team_id=self.team.id, quick_filter_ids=None),
            create_dashboard(team_id=other_team.id, quick_filter_ids=["gone"]),
        ]

        changed = api.remove_quick_filter_from_dashboards(team_id=self.team.id, quick_filter_id="gone")

        assert changed == 2
        assert [dashboard_extras(dashboard_id=d).quick_filter_ids for d in dashboards] == [
            ["a", "b"],
            [],
            ["a"],
            None,
            ["gone"],
        ]


class TestDashboardLookupsForCore(APIBaseTest):
    @parameterized.expand([("live", False, True), ("soft_deleted", True, False)])
    def test_find_dashboard_team_id_finds_only_a_live_dashboard(self, _name: str, deleted: bool, found: bool) -> None:
        other_team = Team.objects.create(organization=self.organization)
        dashboard_id = create_dashboard(team_id=other_team.id, deleted=deleted)

        assert api.find_dashboard_team_id(dashboard_id=dashboard_id) == (other_team.id if found else None)

    def test_dashboards_by_last_access_puts_never_opened_dashboards_last_newest_first(self) -> None:
        now = timezone.now()
        never_opened_older = create_dashboard(team_id=self.team.id, created_at=now - timedelta(days=10))
        opened_earlier = create_dashboard(team_id=self.team.id, last_accessed_at=now - timedelta(days=3))
        never_opened_newer = create_dashboard(team_id=self.team.id)
        opened_later = create_dashboard(team_id=self.team.id, last_accessed_at=now - timedelta(hours=1))
        create_dashboard(team_id=self.team.id, last_accessed_at=now, deleted=True)
        access = UserAccessControl(user=self.user, team=self.team)

        listed = api.dashboards_by_last_access(team_ids=[self.team.id], user_access_control=access, limit=10)

        assert [d.id for d in listed] == [opened_later, opened_earlier, never_opened_newer, never_opened_older]
        assert api.dashboards_by_last_access(team_ids=[], user_access_control=access, limit=10) == []

    @parameterized.expand(
        [
            ("no_dashboard", None, False),
            ("created_by_the_system", "system", False),
            ("created_by_a_person", "person", True),
            ("created_by_a_person_then_deleted", "deleted", False),
        ]
    )
    def test_has_user_created_dashboard(self, _name: str, kind: str | None, expected: bool) -> None:
        if kind is not None:
            create_dashboard(
                team_id=self.team.id,
                created_by_id=None if kind == "system" else self.user.id,
                deleted=kind == "deleted",
            )

        assert api.has_user_created_dashboard(team_id=self.team.id) is expected

    def test_has_user_created_dashboard_does_not_count_the_project_dashboards_for_an_environment(self) -> None:
        environment = Team.objects.create(organization=self.organization, parent_team=self.team)
        create_dashboard(team_id=environment.id, created_by_id=self.user.id)

        assert api.has_user_created_dashboard(team_id=self.team.id) is True
        assert api.has_user_created_dashboard(team_id=environment.id) is False

    def test_record_dashboard_view_stamps_the_dashboard_and_counts_the_access(self) -> None:
        dashboard_id = create_dashboard(team_id=self.team.id)
        before = dashboard_access_count(DashboardAccessMethod.SHARED)

        record_dashboard_view(dashboard_id=dashboard_id, access_method=DashboardAccessMethod.SHARED)

        summary = api.get_dashboard(team_id=self.team.id, dashboard_id=dashboard_id)
        assert summary is not None and summary.last_accessed_at is not None
        assert dashboard_access_count(DashboardAccessMethod.SHARED) == before + 1


class TestTilePlacements(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        now = timezone.now()
        self.since = now - timedelta(days=1)
        self.opened = create_dashboard(team_id=self.team.id, last_accessed_at=now)
        self.stale = create_dashboard(team_id=self.team.id, last_accessed_at=now - timedelta(days=3))
        self.insight = Insight.objects.create(team=self.team, name="a")
        self.removed = Insight.objects.create(team=self.team, name="removed tile")
        self.on_opened = create_insight_tile(dashboard_id=self.opened, insight_id=self.insight.id)
        create_insight_tile(dashboard_id=self.stale, insight_id=self.insight.id)
        create_insight_tile(dashboard_id=self.opened, insight_id=self.removed.id, deleted=True)
        self.text = create_text_tile(dashboard_id=self.opened, body="notes")
        self.asked = [
            InsightPlacement(insight_id=self.insight.id, dashboard_id=self.opened),
            InsightPlacement(insight_id=self.insight.id, dashboard_id=self.stale),
            InsightPlacement(insight_id=self.removed.id, dashboard_id=self.opened),
        ]

    @parameterized.expand(
        [
            ("any_dashboard", None, False, True),
            ("shared_only_without_a_share", None, True, False),
            ("shared_only_with_a_disabled_share", False, True, False),
            ("shared_only_with_an_enabled_share", True, True, True),
        ]
    )
    def test_placements_on_dashboards_accessed_since(
        self, _name: str, share_enabled: bool | None, shared_only: bool, found: bool
    ) -> None:
        if share_enabled is not None:
            SharingConfiguration.objects.create(team=self.team, dashboard_id=self.opened, enabled=share_enabled)

        placements = api.placements_on_dashboards_accessed_since(
            placements=self.asked, since=self.since, shared_only=shared_only
        )

        # The stale dashboard was opened before `since`, and the removed tile does not count.
        assert placements == ([self.asked[0]] if found else [])

    def test_live_tile_placements_lists_live_tiles_of_any_kind(self) -> None:
        deleted_dashboard = create_dashboard(team_id=self.team.id, deleted=True)
        create_insight_tile(dashboard_id=deleted_dashboard, insight_id=self.insight.id)

        assert api.live_tile_placements(dashboard_ids=[self.opened]) == [
            TilePlacement(tile_id=self.on_opened, dashboard_id=self.opened, insight_id=self.insight.id),
            TilePlacement(tile_id=self.text, dashboard_id=self.opened, insight_id=None),
        ]
        assert [p.dashboard_id for p in api.live_tile_placements(insight_ids=[self.insight.id, self.removed.id])] == [
            self.opened,
            self.stale,
        ]
        with self.assertRaises(ValueError):
            api.live_tile_placements()

    def test_insight_ids_on_template_dashboards_needs_both_prefixes_on_a_template_dashboard(self) -> None:
        generated = create_dashboard(
            team_id=self.team.id,
            name="Usage of x",
            description="Generated for x",
            creation_mode=DashboardCreationMode.TEMPLATE,
        )
        hand_made = create_dashboard(team_id=self.team.id, name="Usage of y", description="Generated for y")
        wrong_description = create_dashboard(
            team_id=self.team.id, name="Usage of z", description="Mine", creation_mode=DashboardCreationMode.TEMPLATE
        )
        others = [Insight.objects.create(team=self.team, name=str(n)) for n in range(2)]
        create_insight_tile(dashboard_id=generated, insight_id=self.insight.id)
        create_insight_tile(dashboard_id=hand_made, insight_id=others[0].id)
        create_insight_tile(dashboard_id=wrong_description, insight_id=others[1].id)

        found = api.insight_ids_on_template_dashboards(
            insight_ids=[self.insight.id, *(o.id for o in others)],
            name_prefix="Usage of",
            description_prefix="Generated",
        )

        assert found == {self.insight.id}

    def test_deleting_widget_tiles_for_teams_spares_other_tiles_and_teams(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        theirs = create_widget_tile(dashboard_id=create_dashboard(team_id=other_team.id), widget_type="notebook")
        live = create_widget_tile(dashboard_id=self.opened, widget_type="notebook")
        removed = create_widget_tile(dashboard_id=self.opened, widget_type="notebook", deleted=True)

        api.delete_widget_tiles_for_teams([self.team.id])

        remaining = set(tile_ids(include_removed=True))
        assert {live.tile_id, removed.tile_id} & remaining == set()
        assert {theirs.tile_id, self.on_opened, self.text} <= remaining


class TestDashboardUsageReads(APIBaseTest):
    def test_counts_by_team_join_through_shares_and_tags(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        shared = create_dashboard(team_id=self.team.id, tags=["growth", "weekly"])
        create_dashboard(team_id=self.team.id, creation_mode=DashboardCreationMode.TEMPLATE)
        create_dashboard(team_id=self.team.id, deleted=True)
        create_dashboard(team_id=other_team.id)
        for enabled in (True, True, False):
            SharingConfiguration.objects.create(team=self.team, dashboard_id=shared, enabled=enabled)

        counts = {count: api.dashboard_counts_by_team(count) for count in DashboardUsageCount}

        assert counts == {
            DashboardUsageCount.ALL: {self.team.id: 2, other_team.id: 1},
            DashboardUsageCount.FROM_TEMPLATE: {self.team.id: 1},
            DashboardUsageCount.SHARED: {self.team.id: 2},
            DashboardUsageCount.TAGGED: {self.team.id: 2},
        }

    def test_dashboards_created_between_leaves_out_generated_and_out_of_range_rows(self) -> None:
        now = timezone.now()
        start, end = now - timedelta(days=7), now
        made_by_hand = create_dashboard(team_id=self.team.id, name="Made by hand", created_at=now - timedelta(days=1))
        create_dashboard(team_id=self.team.id, name="Generated Dashboard: x", created_at=now - timedelta(days=1))
        create_dashboard(team_id=self.team.id, name="Exactly at start", created_at=start)
        create_dashboard(team_id=self.team.id, name="After the end", created_at=now + timedelta(minutes=1))
        create_dashboard(team_id=self.team.id, name="Deleted", created_at=now - timedelta(days=1), deleted=True)

        listed = api.dashboards_created_between(
            period_start=start, period_end=end, team_ids=range(self.team.id, self.team.id + 1)
        )
        other_range = api.dashboards_created_between(
            period_start=start, period_end=end, team_ids=range(self.team.id + 1, self.team.id + 100)
        )

        assert (listed, other_range) == (
            [TeamDashboardRef(team_id=self.team.id, id=made_by_hand, name="Made by hand")],
            [],
        )


class TestDashboardTemplatesForCore(APIBaseTest):
    def test_create_global_template_if_missing_creates_once(self) -> None:
        # A team's template with the same name does not count as the global one.
        create_dashboard_template(template_name="Seeded", team_id=self.team.id)
        definition = DashboardTemplateDefinition(
            template_name="Seeded",
            dashboard_description="From a seed",
            tiles=[{"type": "TEXT", "body": "hi", "layouts": {}}],
            variables=[{"code_name": "v"}],
            scope=DashboardTemplateScope.GLOBAL,
        )

        assert api.create_global_template_if_missing(definition) is True
        assert api.create_global_template_if_missing(definition) is False
        assert global_dashboard_template_exists(template_name="Seeded")

    def test_create_starter_dashboard_applies_the_signup_template(self) -> None:
        template = DashboardTemplate.default_signup_template()

        created = api.create_starter_dashboard(team_id=self.team.id)

        summary = api.get_dashboard(team_id=self.team.id, dashboard_id=created.id)
        assert summary is not None
        assert (summary.name, summary.pinned, summary.description) == (
            "Your starter dashboard",
            True,
            template.dashboard_description,
        )
        assert len(tile_ids(dashboard_id=created.id)) == len(template.tiles or [])


class TestDashboardEnumsMirrorTheModels(SimpleTestCase):
    @parameterized.expand(
        [
            ("creation_mode", DashboardCreationMode, Dashboard.CreationMode),
            ("template_scope", DashboardTemplateScope, DashboardTemplate.Scope),
        ]
    )
    def test_facade_enum_has_the_model_choices(self, _name: str, facade_enum: type[StrEnum], choices: Any) -> None:
        assert {member.value for member in facade_enum} == set(choices.values)


class TestTestingHelpers(APIBaseTest):
    def test_update_dashboard_writes_only_the_passed_columns(self) -> None:
        dashboard_id = create_dashboard(
            team_id=self.team.id, name="Kept", share_token="token", is_shared=True, quick_filter_ids=["a"]
        )

        update_dashboard(dashboard_id=dashboard_id, share_token=None, quick_filter_ids=None)

        summary = api.get_dashboard(team_id=self.team.id, dashboard_id=dashboard_id)
        assert summary is not None and summary.name == "Kept"
        assert dashboard_extras(dashboard_id=dashboard_id) == DashboardExtras(
            share_token=None, is_shared=True, quick_filter_ids=None
        )
