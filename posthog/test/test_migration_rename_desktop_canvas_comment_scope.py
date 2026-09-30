from typing import Any

from posthog.test.base import TestMigrations

from django.db import connection
from django.db.migrations.executor import MigrationExecutor


class TestRenameDesktopCanvasCommentScope(TestMigrations):
    migrate_from = "1389_teameventvolume"
    migrate_to = "1390_rename_desktop_canvas_comment_scope"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Comment = apps.get_model("posthog", "Comment")
        integration = apps.get_model("posthog", "Integration").objects.create(
            team_id=self.team.id, kind="slack", integration_id="T1"
        )
        for scope in ["desktop_canvas", "desktop_canvas", "task", "Insight"]:
            root = Comment.objects.create(team_id=self.team.id, scope=scope, item_id="item-1", content="c")
            apps.get_model("posthog", "CommentSlackThread").objects.create(
                team_id=self.team.id,
                scope=scope,
                item_id="item-1",
                source_comment=root,
                integration=integration,
                slack_channel_id="C1",
            )

    def _scopes(self, model_name: str) -> list[str]:
        assert self.apps is not None
        model = self.apps.get_model("posthog", model_name)
        return sorted(model.objects.filter(team_id=self.team.id).values_list("scope", flat=True))

    def test_moves_only_desktop_canvas_comments_and_mirrors_and_reverses(self) -> None:
        for model_name in ("Comment", "CommentSlackThread"):
            assert self._scopes(model_name) == ["Insight", "canvas", "canvas", "task"]

        executor = MigrationExecutor(connection)
        executor.migrate([("posthog", self.migrate_from)])

        for model_name in ("Comment", "CommentSlackThread"):
            assert self._scopes(model_name) == ["Insight", "desktop_canvas", "desktop_canvas", "task"]
