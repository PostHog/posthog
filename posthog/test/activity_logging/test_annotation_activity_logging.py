from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.test.activity_log_utils import ActivityLogTestHelper


class TestAnnotationActivityLogging(ActivityLogTestHelper):
    def test_annotation_creation_activity_logging(self):
        annotation = self.create_annotation("Test annotation")

        log = ActivityLog.objects.filter(
            team_id=self.team.id, scope="Annotation", item_id=str(annotation["id"]), activity="created"
        ).first()
        assert log is not None
        self.assertIsNotNone(log)
        self.assertIsNotNone(log.detail)

    def test_annotation_update_activity_logging(self):
        annotation = self.create_annotation("Original annotation")

        self.update_annotation(annotation["id"], {"content": "Updated annotation"})

        update_log = ActivityLog.objects.filter(
            team_id=self.team.id, scope="Annotation", item_id=str(annotation["id"]), activity="updated"
        ).first()

        assert update_log is not None
        self.assertIsNotNone(update_log)
        self.assertIsNotNone(update_log.detail)
