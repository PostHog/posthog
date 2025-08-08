from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.test.activity_log_utils import ActivityLogTestHelper


class TestAnnotationActivityLogging(ActivityLogTestHelper):
    def test_annotation_creation_activity_logging(self):
        annotation = self.create_annotation("Test annotation")

        activity_logs = ActivityLog.objects.filter(
            team_id=self.team.id, scope="Annotation", item_id=str(annotation["id"]), activity="created"
        )
        self.assertEqual(activity_logs.count(), 1)
        log = activity_logs.first()
        self.assertIsNotNone(log)
        self.assertIsNotNone(log.detail)

    def test_annotation_update_activity_logging(self):
        annotation = self.create_annotation("Original annotation")
        initial_log_count = ActivityLog.objects.filter(
            team_id=self.team.id, scope="Annotation", item_id=str(annotation["id"])
        ).count()

        self.update_annotation(annotation["id"], {"content": "Updated annotation"})

        final_log_count = ActivityLog.objects.filter(
            team_id=self.team.id, scope="Annotation", item_id=str(annotation["id"])
        ).count()
        self.assertEqual(final_log_count - initial_log_count, 1)

        update_log = ActivityLog.objects.filter(
            team_id=self.team.id, scope="Annotation", item_id=str(annotation["id"]), activity="updated"
        ).first()
        self.assertIsNotNone(update_log)
        if update_log:
            self.assertIsNotNone(update_log.detail)
