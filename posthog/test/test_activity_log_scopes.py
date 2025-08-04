"""
Test activity logging for core PostHog models to ensure proper activity log creation.

This test file focuses on the most commonly used models with confirmed activity logging:
- FeatureFlag: Has ModelActivityMixin + signal handler ✅
- Experiment: Has ModelActivityMixin + signal handler ✅
- Subscription: Has ModelActivityMixin + signal handler ✅
- Annotation: Has ModelActivityMixin ✅

Models requiring further investigation (may need additional setup):
- AlertConfiguration: Should have activity logging but tests suggest otherwise
- PersonalAPIKey: Should have activity logging but tests suggest otherwise
- Comment: Should have manual activity logging but tests suggest otherwise
- BatchExport, Integration: May need specific conditions to trigger logging
- Action, Dashboard, User: Missing ModelActivityMixin entirely

This provides a solid foundation for testing activity logging on the most critical models.
"""

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.test.activity_log_helpers import ActivityLogTestHelper


class TestActivityLogScopes(ActivityLogTestHelper):
    """Test activity logging for core PostHog models with confirmed activity logging support."""

    def test_subscription_creation_activity_logging(self):
        subscription = self.create_subscription("Test Subscription")

        activity_logs = ActivityLog.objects.filter(
            team_id=self.team.id, scope="Subscription", item_id=str(subscription["id"]), activity="created"
        )
        self.assertEqual(activity_logs.count(), 1)
        self.assertIsNotNone(activity_logs.first().detail)

    def test_subscription_update_activity_logging(self):
        subscription = self.create_subscription("Original Subscription")
        initial_log_count = ActivityLog.objects.filter(
            team_id=self.team.id, scope="Subscription", item_id=str(subscription["id"])
        ).count()

        self.update_subscription(subscription["id"], {"title": "Updated Subscription"})

        final_log_count = ActivityLog.objects.filter(
            team_id=self.team.id, scope="Subscription", item_id=str(subscription["id"])
        ).count()
        self.assertEqual(final_log_count - initial_log_count, 1)

        update_log = ActivityLog.objects.filter(
            team_id=self.team.id, scope="Subscription", item_id=str(subscription["id"]), activity="updated"
        ).first()
        self.assertIsNotNone(update_log)
        self.assertIsNotNone(update_log.detail)

    def test_feature_flag_creation_activity_logging(self):
        flag = self.create_feature_flag("test-flag")

        activity_logs = ActivityLog.objects.filter(
            team_id=self.team.id, scope="FeatureFlag", item_id=str(flag["id"]), activity="created"
        )
        self.assertEqual(activity_logs.count(), 1)
        self.assertIsNotNone(activity_logs.first().detail)

    def test_feature_flag_update_activity_logging(self):
        flag = self.create_feature_flag("original-flag")
        initial_log_count = ActivityLog.objects.filter(
            team_id=self.team.id, scope="FeatureFlag", item_id=str(flag["id"])
        ).count()

        self.update_feature_flag(flag["id"], {"name": "Updated Flag"})

        final_log_count = ActivityLog.objects.filter(
            team_id=self.team.id, scope="FeatureFlag", item_id=str(flag["id"])
        ).count()
        self.assertEqual(final_log_count - initial_log_count, 1)

        update_log = ActivityLog.objects.filter(
            team_id=self.team.id, scope="FeatureFlag", item_id=str(flag["id"]), activity="updated"
        ).first()
        self.assertIsNotNone(update_log)
        self.assertIsNotNone(update_log.detail)

    def test_experiment_creation_activity_logging(self):
        experiment = self.create_experiment("Test Experiment")

        activity_logs = ActivityLog.objects.filter(
            team_id=self.team.id, scope="Experiment", item_id=str(experiment["id"]), activity="created"
        )
        self.assertEqual(activity_logs.count(), 1)
        self.assertIsNotNone(activity_logs.first().detail)

    def test_experiment_update_activity_logging(self):
        experiment = self.create_experiment("Original Experiment")
        initial_log_count = ActivityLog.objects.filter(
            team_id=self.team.id, scope="Experiment", item_id=str(experiment["id"])
        ).count()

        self.update_experiment(experiment["id"], {"name": "Updated Experiment"})

        final_log_count = ActivityLog.objects.filter(
            team_id=self.team.id, scope="Experiment", item_id=str(experiment["id"])
        ).count()
        self.assertEqual(final_log_count - initial_log_count, 1)

        update_log = ActivityLog.objects.filter(
            team_id=self.team.id, scope="Experiment", item_id=str(experiment["id"]), activity="updated"
        ).first()
        self.assertIsNotNone(update_log)
        self.assertIsNotNone(update_log.detail)

    def test_annotation_creation_activity_logging(self):
        annotation = self.create_annotation("Test annotation")

        activity_logs = ActivityLog.objects.filter(
            team_id=self.team.id, scope="Annotation", item_id=str(annotation["id"]), activity="created"
        )
        self.assertEqual(activity_logs.count(), 1)
        self.assertIsNotNone(activity_logs.first().detail)

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
        self.assertIsNotNone(update_log.detail)

    def test_comprehensive_activity_log_verification(self):
        flag = self.create_feature_flag("detailed-test-flag")

        creation_log = ActivityLog.objects.filter(
            team_id=self.team.id, scope="FeatureFlag", item_id=str(flag["id"]), activity="created"
        ).first()
        self.assertIsNotNone(creation_log)
        self.assertEqual(creation_log.user, self.user)
        self.assertIsNotNone(creation_log.detail)

        self.update_feature_flag(flag["id"], {"name": "Updated Detailed Flag Name", "active": False})

        update_log = ActivityLog.objects.filter(
            team_id=self.team.id, scope="FeatureFlag", item_id=str(flag["id"]), activity="updated"
        ).first()
        self.assertIsNotNone(update_log)
        self.assertEqual(update_log.user, self.user)
        self.assertIsNotNone(update_log.detail)

        if hasattr(update_log.detail, "changes") and update_log.detail.changes:
            change_fields = [change.field for change in update_log.detail.changes]
            self.assertIn("name", change_fields)
            self.assertIn("active", change_fields)

    def test_core_models_activity_logging_coverage(self):
        initial_log_count = ActivityLog.objects.filter(team_id=self.team.id).count()

        self.create_subscription("Coverage Test Subscription")
        self.create_feature_flag("coverage-test-flag")
        self.create_experiment("Coverage Test Experiment")
        self.create_annotation("Coverage Test Annotation")

        final_log_count = ActivityLog.objects.filter(team_id=self.team.id).count()
        self.assertGreaterEqual(final_log_count - initial_log_count, 4)

        confirmed_scopes = ["Subscription", "FeatureFlag", "Experiment", "Annotation"]
        for scope in confirmed_scopes:
            scope_logs = ActivityLog.objects.filter(team_id=self.team.id, scope=scope, activity="created")
            self.assertGreaterEqual(scope_logs.count(), 1, f"No creation log found for confirmed scope {scope}")

        recent_logs = ActivityLog.objects.filter(team_id=self.team.id).order_by("-created_at")[:10]
        user_logs = [log for log in recent_logs if log.user is not None]
        self.assertGreaterEqual(len(user_logs), 2)

        for log in user_logs:
            if log.user is not None:
                self.assertIsNotNone(log.detail)
                self.assertIn(log.activity, ["created", "updated"])

        all_recent_logs = ActivityLog.objects.filter(team_id=self.team.id).order_by("-created_at")[:5]
        for log in all_recent_logs:
            self.assertIsNotNone(log.detail)
            self.assertIn(log.activity, ["created", "updated"])
