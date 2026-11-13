from typing import Any, cast

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.test.activity_log_utils import ActivityLogTestHelper

from products.annotations.backend.facade.enums import AnnotationScope
from products.dashboards.backend.facade.testing import create_dashboard
from products.product_analytics.backend.facade.models import Insight


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
        annotation = self.create_annotation(content="Project annotation", scope=AnnotationScope.PROJECT.value)

        log = ActivityLog.objects.filter(
            team_id=self.team.id, scope="Annotation", item_id=str(annotation["id"]), activity="created"
        ).first()

        self.assertIsNotNone(log)
        assert log is not None
        self.assertIsNotNone(log.detail)
        detail = cast(dict[str, Any], log.detail)
        self.assertIsNotNone(detail.get("context"))

        context = cast(dict[str, Any], detail["context"])
        self.assertEqual(context["scope"], AnnotationScope.PROJECT.value)
        self.assertIsNone(context.get("dashboard_id"))
        self.assertIsNone(context.get("dashboard_item_id"))

    def test_annotation_organization_scope_context(self):
        """Test annotation with organization scope includes correct context."""
        annotation = self.create_annotation(content="Organization annotation", scope=AnnotationScope.ORGANIZATION.value)

        log = ActivityLog.objects.filter(
            team_id=self.team.id, scope="Annotation", item_id=str(annotation["id"]), activity="created"
        ).first()

        self.assertIsNotNone(log)
        assert log is not None
        self.assertIsNotNone(log.detail)
        detail = cast(dict[str, Any], log.detail)
        self.assertIsNotNone(detail.get("context"))

        context = cast(dict[str, Any], detail["context"])
        self.assertEqual(context["scope"], AnnotationScope.ORGANIZATION.value)
        self.assertIsNone(context.get("dashboard_id"))
        self.assertIsNone(context.get("dashboard_item_id"))

    def test_annotation_dashboard_scope_context(self):
        """Test annotation with dashboard scope includes correct context."""
        # Create a dashboard first
        dashboard_id = create_dashboard(team_id=self.team.id, name="Test Dashboard", created_by_id=self.user.id)

        annotation = self.create_annotation(
            content="Dashboard annotation", scope=AnnotationScope.DASHBOARD.value, dashboard_id=dashboard_id
        )

        log = ActivityLog.objects.filter(
            team_id=self.team.id, scope="Annotation", item_id=str(annotation["id"]), activity="created"
        ).first()

        self.assertIsNotNone(log)
        assert log is not None
        self.assertIsNotNone(log.detail)
        detail = cast(dict[str, Any], log.detail)
        self.assertIsNotNone(detail.get("context"))

        context = cast(dict[str, Any], detail["context"])
        self.assertEqual(context["scope"], AnnotationScope.DASHBOARD.value)
        self.assertEqual(context["dashboard_id"], dashboard_id)
        self.assertEqual(context["dashboard_name"], "Test Dashboard")
        self.assertIsNone(context.get("dashboard_item_id"))

    def test_annotation_insight_scope_context(self):
        """Test annotation with insight scope includes correct context."""
        # Create an insight first
        insight = Insight.objects.create(
            team=self.team, name="Test Insight", created_by=self.user, filters={"events": [{"id": "$pageview"}]}
        )

        annotation = self.create_annotation(
            content="Insight annotation", scope=AnnotationScope.INSIGHT.value, dashboard_item=insight.id
        )

        log = ActivityLog.objects.filter(
            team_id=self.team.id, scope="Annotation", item_id=str(annotation["id"]), activity="created"
        ).first()

        self.assertIsNotNone(log)
        assert log is not None
        self.assertIsNotNone(log.detail)
        detail = cast(dict[str, Any], log.detail)
        self.assertIsNotNone(detail.get("context"))

        context = cast(dict[str, Any], detail["context"])
        self.assertEqual(context["scope"], AnnotationScope.INSIGHT.value)
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
        detail = cast(dict[str, Any], log.detail)
        self.assertEqual(detail["name"], annotation["content"])
        self.assertIsNotNone(detail.get("context"))
        self.assertIsNotNone(detail.get("changes"))
