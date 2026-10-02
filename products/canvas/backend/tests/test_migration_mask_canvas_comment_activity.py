from typing import Any

from posthog.test.base import TestMigrations


class TestMaskCanvasCommentActivity(TestMigrations):
    migrate_from = "0020_alter_canvas_channel"
    migrate_to = "0021_mask_canvas_comment_activity"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Comment = apps.get_model("posthog", "Comment")
        ActivityLog = apps.get_model("posthog", "ActivityLog")
        canvas_root = Comment.objects.create(team_id=self.team.id, scope="desktop_canvas", item_id="canvas-1")
        insight_root = Comment.objects.create(team_id=self.team.id, scope="Insight", item_id="insight-1")

        def log(scope: str, item_id: str, content: str) -> None:
            ActivityLog.objects.create(
                team_id=self.team.id,
                scope=scope,
                activity="commented",
                item_id=item_id,
                detail={"changes": [{"type": "Comment", "field": "content", "action": "created", "after": content}]},
            )

        log("desktop_canvas", "canvas-1", "canvas root text")
        log("Comment", str(canvas_root.id), "canvas reply text")
        log("Insight", "insight-1", "insight root text")
        log("Comment", str(insight_root.id), "insight reply text")

    def test_masks_only_canvas_comment_text(self) -> None:
        assert self.apps is not None
        ActivityLog = self.apps.get_model("posthog", "ActivityLog")

        contents = sorted(
            row.detail["changes"][0]["after"]
            for row in ActivityLog.objects.filter(team_id=self.team.id, activity="commented")
        )

        assert contents == ["insight reply text", "insight root text", "masked", "masked"]
