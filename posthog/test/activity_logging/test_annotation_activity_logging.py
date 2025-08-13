from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.annotation import Annotation
from posthog.models.dashboard import Dashboard
from posthog.models.insight import Insight
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

    def test_annotation_project_scope_context(self):
        """Test annotation with project scope includes correct context."""
        annotation = self.create_annotation(content="Project annotation", scope=Annotation.Scope.PROJECT.value)

        log = ActivityLog.objects.filter(
            team_id=self.team.id, scope="Annotation", item_id=str(annotation["id"]), activity="created"
        ).first()

        self.assertIsNotNone(log)
        assert log is not None
        self.assertIsNotNone(log.detail)
        self.assertIsNotNone(log.detail.get("context"))

        context = log.detail["context"]
        self.assertEqual(context["scope"], Annotation.Scope.PROJECT.value)
        self.assertIsNone(context.get("dashboard_id"))
        self.assertIsNone(context.get("dashboard_item_id"))

    def test_annotation_organization_scope_context(self):
        """Test annotation with organization scope includes correct context."""
        annotation = self.create_annotation(
            content="Organization annotation", scope=Annotation.Scope.ORGANIZATION.value
        )

        log = ActivityLog.objects.filter(
            team_id=self.team.id, scope="Annotation", item_id=str(annotation["id"]), activity="created"
        ).first()

        self.assertIsNotNone(log)
        assert log is not None
        self.assertIsNotNone(log.detail)
        self.assertIsNotNone(log.detail.get("context"))

        context = log.detail["context"]
        self.assertEqual(context["scope"], Annotation.Scope.ORGANIZATION.value)
        self.assertIsNone(context.get("dashboard_id"))
        self.assertIsNone(context.get("dashboard_item_id"))

    def test_annotation_dashboard_scope_context(self):
        """Test annotation with dashboard scope includes correct context."""
        # Create a dashboard first
        dashboard = Dashboard.objects.create(team=self.team, name="Test Dashboard", created_by=self.user)

        annotation = self.create_annotation(
            content="Dashboard annotation", scope=Annotation.Scope.DASHBOARD.value, dashboard_id=dashboard.id
        )

        log = ActivityLog.objects.filter(
            team_id=self.team.id, scope="Annotation", item_id=str(annotation["id"]), activity="created"
        ).first()

        self.assertIsNotNone(log)
        assert log is not None
        self.assertIsNotNone(log.detail)
        self.assertIsNotNone(log.detail.get("context"))

        context = log.detail["context"]
        self.assertEqual(context["scope"], Annotation.Scope.DASHBOARD.value)
        self.assertEqual(context["dashboard_id"], dashboard.id)
        self.assertEqual(context["dashboard_name"], dashboard.name)
        self.assertIsNone(context.get("dashboard_item_id"))

    def test_annotation_insight_scope_context(self):
        """Test annotation with insight scope includes correct context."""
        # Create an insight first
        insight = Insight.objects.create(
            team=self.team, name="Test Insight", created_by=self.user, filters={"events": [{"id": "$pageview"}]}
        )

        annotation = self.create_annotation(
            content="Insight annotation", scope=Annotation.Scope.INSIGHT.value, dashboard_item=insight.id
        )

        log = ActivityLog.objects.filter(
            team_id=self.team.id, scope="Annotation", item_id=str(annotation["id"]), activity="created"
        ).first()

        self.assertIsNotNone(log)
        assert log is not None
        self.assertIsNotNone(log.detail)
        self.assertIsNotNone(log.detail.get("context"))

        context = log.detail["context"]
        self.assertEqual(context["scope"], Annotation.Scope.INSIGHT.value)
        self.assertEqual(context["dashboard_item_id"], insight.id)
        self.assertEqual(context["dashboard_item_short_id"], insight.short_id)
        self.assertEqual(context["dashboard_item_name"], insight.name)
        self.assertIsNone(context.get("dashboard_id"))

    def test_annotation_activity_log_properties(self):
        """Test all expected activity log properties are set correctly."""
        annotation = self.create_annotation("Test annotation")

        log = ActivityLog.objects.filter(
            team_id=self.team.id, scope="Annotation", item_id=str(annotation["id"]), activity="created"
        ).first()

        self.assertIsNotNone(log)
        assert log is not None
        self.assertEqual(log.scope, "Annotation")
        self.assertEqual(log.activity, "created")
        self.assertEqual(log.item_id, str(annotation["id"]))
        self.assertEqual(log.team_id, self.team.id)
        self.assertEqual(log.organization_id, self.organization.id)
        self.assertEqual(log.user, self.user)
        self.assertFalse(log.was_impersonated or False)
        self.assertFalse(log.is_system or False)

        self.assertIsNotNone(log.detail)
        detail = log.detail
        self.assertEqual(detail["name"], annotation["content"])
        self.assertIsNotNone(detail.get("context"))
        self.assertIsNotNone(detail.get("changes"))
