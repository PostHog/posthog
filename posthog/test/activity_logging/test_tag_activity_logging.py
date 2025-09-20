from django.db.models.query import QuerySet

from posthog.constants import AvailableFeature
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.test.activity_log_utils import ActivityLogTestHelper


class TestTagActivityLogging(ActivityLogTestHelper):
    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [{"key": AvailableFeature.TAGGING, "name": "Tagging"}]
        self.organization.save()

    def test_tag_creation_via_insight_tagging(self):
        insight = self.create_insight(name="Test Insight")
        self.update_insight(insight["id"], {"tags": ["test-tag"]})

        log = ActivityLog.objects.filter(scope="Tag", activity="created").first()
        self.assertIsNotNone(log)
        assert log is not None
        self.assertEqual(log.detail["name"], "test-tag")

    def test_tag_creation_via_dashboard_tagging(self):
        dashboard = self.create_dashboard(name="Test Dashboard")
        self.update_dashboard(dashboard["id"], {"tags": ["test-tag"]})

        log = ActivityLog.objects.filter(scope="Tag", activity="created").first()
        self.assertIsNotNone(log)
        assert log is not None
        self.assertEqual(log.detail["name"], "test-tag")

    def test_tag_creation_via_action_tagging(self):
        action = self.create_action(name="Test Action")
        self.update_action(action["id"], {"name": "Test Action", "tags": ["test-tag"]})

        log = ActivityLog.objects.filter(scope="Tag", activity="created").first()
        self.assertIsNotNone(log)
        assert log is not None
        self.assertEqual(log.detail["name"], "test-tag")


class TestTaggedItemActivityLogging(ActivityLogTestHelper):
    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [{"key": AvailableFeature.TAGGING, "name": "Tagging"}]
        self.organization.save()

    def test_tagged_item_creation_via_dashboard_api(self):
        dashboard = self.create_dashboard(name="Test Dashboard")
        self.update_dashboard(dashboard["id"], {"tags": ["test-tag"]})

        log = ActivityLog.objects.filter(scope="TaggedItem", activity="created").first()
        self.assertIsNotNone(log)
        assert log is not None
        self.assertEqual(log.detail["name"], "test-tag")
        self.assertEqual(log.detail["context"]["related_object_type"], "dashboard")

    def test_tagged_item_creation_via_insight_api(self):
        insight = self.create_insight(name="Test Insight")
        self.update_insight(insight["id"], {"tags": ["test-tag"]})

        log = ActivityLog.objects.filter(scope="TaggedItem", activity="created").first()
        self.assertIsNotNone(log)
        assert log is not None
        self.assertEqual(log.detail["name"], "test-tag")
        self.assertEqual(log.detail["context"]["related_object_type"], "insight")

    def test_tagged_item_creation_via_action_api(self):
        action = self.create_action(name="Test Action")
        self.update_action(action["id"], {"name": "Test Action", "tags": ["test-tag"]})

        log = ActivityLog.objects.filter(scope="TaggedItem", activity="created").first()
        self.assertIsNotNone(log)
        assert log is not None
        self.assertEqual(log.detail["name"], "test-tag")
        self.assertEqual(log.detail["context"]["related_object_type"], "action")

    def test_tagged_item_update(self):
        dashboard = self.create_dashboard(name="Test Dashboard")
        self.update_dashboard(dashboard["id"], {"tags": ["original-tag"]})

        self.update_dashboard(dashboard["id"], {"tags": ["updated-tag"]})

        creation_logs = ActivityLog.objects.filter(scope="TaggedItem", activity="created")
        deletion_logs = ActivityLog.objects.filter(scope="TaggedItem", activity="deleted")
        self.assertGreater(creation_logs.count(), 0)
        self.assertGreater(deletion_logs.count(), 0)

    def test_tagged_item_deletion(self):
        dashboard = self.create_dashboard(name="Test Dashboard")
        self.update_dashboard(dashboard["id"], {"tags": ["tag-to-delete"]})
        ActivityLog.objects.filter(scope="TaggedItem", activity="created").delete()

        self.update_dashboard(dashboard["id"], {"tags": []})

        log = ActivityLog.objects.filter(scope="TaggedItem", activity="deleted").first()
        self.assertIsNotNone(log)
        assert log is not None
        self.assertEqual(log.detail["name"], "tag-to-delete")

    def test_bulk_tagging_and_untagging(self):
        dashboard = self.create_dashboard(name="Test Dashboard")
        self.update_dashboard(dashboard["id"], {"tags": ["tag1", "tag2", "tag3"]})

        creation_logs = ActivityLog.objects.filter(scope="TaggedItem", activity="created")
        self.assertEqual(creation_logs.count(), 3)
        ActivityLog.objects.filter(scope="TaggedItem", activity="created").delete()

        self.update_dashboard(dashboard["id"], {"tags": ["tag1"]})

        deletion_logs = ActivityLog.objects.filter(scope="TaggedItem", activity="deleted")
        self.assertEqual(deletion_logs.count(), 2)
        deleted_tags = {log.detail["name"] for log in deletion_logs}
        self.assertEqual(deleted_tags, {"tag2", "tag3"})

    def test_mixed_object_types_with_same_tag(self):
        dashboard = self.create_dashboard(name="Test Dashboard")
        insight = self.create_insight(name="Test Insight")
        action = self.create_action(name="Test Action")

        self.update_dashboard(dashboard["id"], {"tags": ["shared-tag"]})
        self.update_insight(insight["id"], {"tags": ["shared-tag"]})
        self.update_action(action["id"], {"name": "Test Action", "tags": ["shared-tag"]})

        logs = ActivityLog.objects.filter(scope="TaggedItem", activity="created")
        self.assertEqual(logs.count(), 3)

        tag_names = {log.detail["name"] for log in logs}
        self.assertEqual(tag_names, {"shared-tag"})

        object_types = {log.detail["context"]["related_object_type"] for log in logs}
        self.assertEqual(object_types, {"dashboard", "insight", "action"})

    def test_tagged_item_context_fields(self):
        dashboard = self.create_dashboard(name="Test Dashboard")
        self.update_dashboard(dashboard["id"], {"tags": ["context-test-tag"]})

        log = ActivityLog.objects.filter(scope="TaggedItem", activity="created").first()
        self.assertIsNotNone(log)
        assert log is not None

        context = log.detail["context"]
        self.assertEqual(context["tag_name"], "context-test-tag")
        self.assertEqual(context["team_id"], self.team.id)
        self.assertEqual(context["related_object_type"], "dashboard")
        self.assertEqual(context["related_object_name"], "Test Dashboard")
        self.assertEqual(context["related_object_id"], str(dashboard["id"]))

    def test_bulk_object_tagging(self):
        dashboard1 = self.create_dashboard(name="Dashboard 1")
        dashboard2 = self.create_dashboard(name="Dashboard 2")
        insight1 = self.create_insight(name="Insight 1")
        insight2 = self.create_insight(name="Insight 2")

        self.update_dashboard(dashboard1["id"], {"tags": ["bulk-tag", "shared-tag"]})
        self.update_dashboard(dashboard2["id"], {"tags": ["bulk-tag", "another-tag"]})
        self.update_insight(insight1["id"], {"tags": ["bulk-tag", "insight-tag"]})
        self.update_insight(insight2["id"], {"tags": ["shared-tag", "final-tag"]})

        logs = ActivityLog.objects.filter(scope="TaggedItem", activity="created")
        self.assertEqual(logs.count(), 8)

        bulk_tag_logs = [log for log in logs if log.detail["name"] == "bulk-tag"]
        self.assertEqual(len(bulk_tag_logs), 3)

        shared_tag_logs = [log for log in logs if log.detail["name"] == "shared-tag"]
        self.assertEqual(len(shared_tag_logs), 2)

    def test_bulk_tag_removal_and_replacement(self):
        dashboard = self.create_dashboard(name="Test Dashboard")
        insight = self.create_insight(name="Test Insight")

        self.update_dashboard(dashboard["id"], {"tags": ["old-tag", "keep-tag"]})
        self.update_insight(insight["id"], {"tags": ["old-tag", "insight-specific"]})
        ActivityLog.objects.all().delete()

        self.update_dashboard(dashboard["id"], {"tags": ["keep-tag", "new-tag"]})
        self.update_insight(insight["id"], {"tags": ["insight-specific", "another-new-tag"]})

        deletion_logs = ActivityLog.objects.filter(scope="TaggedItem", activity="deleted")
        deleted_tag_names = {log.detail["name"] for log in deletion_logs}
        self.assertIn("old-tag", deleted_tag_names)

        creation_logs = ActivityLog.objects.filter(scope="TaggedItem", activity="created")
        created_tag_names = {log.detail["name"] for log in creation_logs}
        self.assertIn("new-tag", created_tag_names)
        self.assertIn("another-new-tag", created_tag_names)

    def test_tag_replacement_via_api(self):
        insight = self.create_insight(name="Test Insight")
        self.update_insight(insight["id"], {"tags": ["original-tag"]})
        ActivityLog.objects.all().delete()

        self.update_insight(insight["id"], {"tags": ["updated-tag"]})

        # Should create new TaggedItem for "updated-tag"
        creation_logs = ActivityLog.objects.filter(scope="TaggedItem", activity="created")
        self.assertEqual(creation_logs.count(), 1)
        created_log = creation_logs.first()
        assert created_log is not None
        self.assertEqual(created_log.detail["name"], "updated-tag")

        # Should delete old TaggedItem for "original-tag"
        deletion_logs = ActivityLog.objects.filter(scope="TaggedItem", activity="deleted")
        self.assertEqual(deletion_logs.count(), 1)
        deleted_log = deletion_logs.first()
        assert deleted_log is not None
        self.assertEqual(deleted_log.detail["name"], "original-tag")

        # May also create new Tag if "updated-tag" didn't exist before
        tag_creation_logs: QuerySet[ActivityLog] = ActivityLog.objects.filter(scope="Tag", activity="created")
        if tag_creation_logs.exists():
            tag_log = tag_creation_logs.first()
            assert tag_log is not None
            self.assertEqual(tag_log.detail["name"], "updated-tag")
