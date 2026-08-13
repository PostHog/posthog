from typing import Any

from posthog.test.base import TestMigrations


class MigrateDashboardGroupSectionsTest(TestMigrations):
    migrate_from = "0019_dashboardgroup_position_and_nullable_name"
    migrate_to = "0020_migrate_dashboard_group_sections"

    @property
    def app(self) -> str:
        return "dashboards"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Dashboard = apps.get_model("dashboards", "Dashboard")
        DashboardGroup = apps.get_model("dashboards", "DashboardGroup")
        DashboardTile = apps.get_model("dashboards", "DashboardTile")
        Text = apps.get_model("dashboards", "Text")

        grouped_dashboard = Dashboard.objects.create(team_id=self.team.id, name="Grouped")
        untouched_dashboard = Dashboard.objects.create(team_id=self.team.id, name="Untouched")
        first_group = DashboardGroup.all_teams.create(
            dashboard=grouped_dashboard,
            team_id=self.team.id,
            name="First",
        )
        second_group = DashboardGroup.all_teams.create(
            dashboard=grouped_dashboard,
            team_id=self.team.id,
            name="Second",
        )
        section_dashboard = Dashboard.objects.create(team_id=self.team.id, name="Already migrated")
        section_group = DashboardGroup.all_teams.create(
            dashboard=section_dashboard,
            team_id=self.team.id,
            name="Section",
            position=0,
        )
        section_text = Text.objects.create(team_id=self.team.id, body="Section tile")
        DashboardTile.objects.create(
            dashboard=section_dashboard,
            team_id=self.team.id,
            text=section_text,
            parent_group=section_group,
            layouts={"sm": {"x": 0, "y": 0, "w": 6, "h": 5}},
        )
        DashboardTile.objects.create(
            dashboard=grouped_dashboard,
            team_id=self.team.id,
            dashboard_group=first_group,
            layouts={"sm": {"x": 0, "y": 2, "w": 12, "h": 1}},
        )
        DashboardTile.objects.create(
            dashboard=grouped_dashboard,
            team_id=self.team.id,
            dashboard_group=second_group,
            layouts={"sm": {"x": 0, "y": 8, "w": 12, "h": 1}},
        )
        for body, y, dashboard in (
            ("Before", 0, grouped_dashboard),
            ("Between", 5, grouped_dashboard),
            ("After", 10, grouped_dashboard),
            ("Untouched", 0, untouched_dashboard),
        ):
            text = Text.objects.create(team_id=self.team.id, body=body)
            DashboardTile.objects.create(
                dashboard=dashboard,
                team_id=self.team.id,
                text=text,
                layouts={"sm": {"x": 0, "y": y, "w": 12, "h": 2}},
            )

        self.grouped_dashboard_id = grouped_dashboard.id
        self.untouched_dashboard_id = untouched_dashboard.id
        self.section_dashboard_id = section_dashboard.id

    def test_migration_builds_ordered_sections_and_leaves_group_less_dashboards_untouched(self) -> None:
        DashboardGroup = self.apps.get_model("dashboards", "DashboardGroup")  # type: ignore[union-attr]
        DashboardTile = self.apps.get_model("dashboards", "DashboardTile")  # type: ignore[union-attr]

        groups = list(DashboardGroup.all_teams.filter(dashboard_id=self.grouped_dashboard_id).order_by("position"))
        assert [(group.name, group.position) for group in groups] == [
            (None, 0),
            ("First", 1),
            (None, 2),
            ("Second", 3),
            (None, 4),
        ]
        assert (
            DashboardTile.objects.filter(
                dashboard_id=self.grouped_dashboard_id,
                dashboard_group_id__isnull=False,
            ).count()
            == 0
        )
        assert all(group.member_tiles.count() == 1 for group in groups if group.name is None)
        assert not DashboardGroup.all_teams.filter(dashboard_id=self.untouched_dashboard_id).exists()
        assert DashboardTile.objects.get(dashboard_id=self.untouched_dashboard_id).parent_group_id is None
        section_group = DashboardGroup.all_teams.get(dashboard_id=self.section_dashboard_id)
        assert section_group.position == 0
        assert section_group.member_tiles.count() == 1
