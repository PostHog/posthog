from typing import Any

from posthog.test.base import TestMigrations

from django.db import connection
from django.db.migrations.executor import MigrationExecutor


class TestRenameDesktopCanvasCommentScope(TestMigrations):
    migrate_from = "1385_add_data_deletion_submission_id_constraint"
    migrate_to = "1386_rename_desktop_canvas_comment_scope"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Comment = apps.get_model("posthog", "Comment")
        for scope in ["desktop_canvas", "desktop_canvas", "task", "Insight"]:
            Comment.objects.create(team_id=self.team.id, scope=scope, item_id="item-1", content="c")

    def _scopes(self) -> list[str]:
        assert self.apps is not None
        Comment = self.apps.get_model("posthog", "Comment")
        return sorted(Comment.objects.filter(team_id=self.team.id).values_list("scope", flat=True))

    def test_moves_only_desktop_canvas_comments_and_reverses(self) -> None:
        assert self._scopes() == ["Insight", "canvas", "canvas", "task"]

        executor = MigrationExecutor(connection)
        executor.migrate([("posthog", self.migrate_from)])

        assert self._scopes() == ["Insight", "desktop_canvas", "desktop_canvas", "task"]
