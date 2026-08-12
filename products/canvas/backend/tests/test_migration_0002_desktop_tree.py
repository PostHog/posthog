from typing import Any

from posthog.test.base import NonAtomicTestMigrations


class MigrateDesktopTreeHomeCanvasTest(NonAtomicTestMigrations):
    """0002 converts desktop file-system rows to first-class models. Two folder
    rows can resolve to the same channel and both carry meta.homeCanvasId (e.g.
    a path-renamed duplicate); is_home is unique per channel, so only the first
    may win or the second insert aborts the migration with an IntegrityError.
    """

    migrate_from = "0001_initial"
    migrate_to = "0003_migrate_desktop_tree"

    CLASS_DATA_LEVEL_SETUP = False

    @property
    def app(self) -> str:
        return "canvas"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")
        User = apps.get_model("posthog", "User")
        FileSystem = apps.get_model("posthog", "FileSystem")

        org = Organization.objects.create(name="Org")
        project = Project.objects.create(id=999_997, organization=org, name="Proj")
        team = Team.objects.create(organization=org, project=project, name="Team")
        user = User.objects.create(email="c@example.com", distinct_id="c-distinct")
        self.team_id = team.id

        # One top-level folder ("general") whose tree holds a home canvas, plus a
        # second same-named folder row (a duplicate) ALSO pointing at a home
        # canvas. Both resolve to the same "general" channel.
        folder_a = FileSystem.objects.create(
            team=team,
            path="general",
            depth=1,
            type="folder",
            surface="desktop",
            created_by=user,
            meta={"homeCanvasId": "11111111-1111-1111-1111-111111111111"},
        )
        folder_b = FileSystem.objects.create(
            team=team,
            path="general",
            depth=1,
            type="folder",
            surface="desktop",
            created_by=user,
            meta={"homeCanvasId": "22222222-2222-2222-2222-222222222222"},
        )
        self.folder_a_id = folder_a.id
        self.folder_b_id = folder_b.id

        for home_id, path in (
            ("11111111-1111-1111-1111-111111111111", "general/Home A"),
            ("22222222-2222-2222-2222-222222222222", "general/Home B"),
        ):
            FileSystem.objects.create(
                id=home_id,
                team=team,
                path=path,
                depth=2,
                type="dashboard",
                surface="desktop",
                created_by=user,
                meta={"channelId": str(folder_a.id)},
            )

    def test_two_home_canvas_pointers_in_one_channel_do_not_crash(self) -> None:
        Canvas = self.apps.get_model("canvas", "Canvas")  # type: ignore[union-attr]
        canvases = list(Canvas.objects.filter(team_id=self.team_id))
        # Both dashboards migrated; exactly one is_home (no unique-constraint crash).
        assert len(canvases) == 2
        assert sum(1 for c in canvases if c.is_home) == 1
