from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.test.activity_log_utils import ActivityLogTestHelper


class TestAlertActivityLogging(ActivityLogTestHelper):
    def test_alert_configuration_creation_activity_logging(self):
        alert = self.create_alert_configuration("Test alert")

        log = ActivityLog.objects.filter(
            team_id=self.team.id, scope="AlertConfiguration", item_id=str(alert["id"]), activity="created"
        ).first()
        assert log is not None
        self.assertIsNotNone(log)
        self.assertIsNotNone(log.detail)

    def test_alert_configuration_update_activity_logging(self):
        alert = self.create_alert_configuration("Original alert")

        self.update_alert_configuration(alert["id"], {"name": "Updated alert"})

        update_log = ActivityLog.objects.filter(
            team_id=self.team.id, scope="AlertConfiguration", item_id=str(alert["id"]), activity="updated"
        ).first()

        assert update_log is not None
        self.assertIsNotNone(update_log)
        self.assertIsNotNone(update_log.detail)

    def test_alert_configuration_basic_context(self):
        insight = self.create_insight("Test Insight for Alert")
        alert = self.create_alert_configuration(
            name="Alert with context",
            insight=insight["id"],
            config={"type": "TrendsAlertConfig", "series_index": 0},
        )

        log = ActivityLog.objects.filter(
            team_id=self.team.id, scope="AlertConfiguration", item_id=str(alert["id"]), activity="created"
        ).first()

        self.assertIsNotNone(log)
        assert log is not None
        self.assertIsNotNone(log.detail)
        self.assertIsNotNone(log.detail.get("context"))

        context = log.detail["context"]
        self.assertEqual(context["insight_id"], insight["id"])
        self.assertEqual(context["insight_short_id"], insight["short_id"])
        self.assertEqual(context["insight_name"], insight["name"])

    def test_alert_configuration_different_conditions(self):
        insight = self.create_insight("Insight for Different Conditions")
        alert1 = self.create_alert_configuration(
            name="Alert with relative threshold",
            insight=insight["id"],
            threshold={"configuration": {"type": "percentage", "bounds": {"lower": 10, "upper": 90}}},
            condition={"type": "relative_previous_period"},
        )

        log1 = ActivityLog.objects.filter(
            team_id=self.team.id, scope="AlertConfiguration", item_id=str(alert1["id"]), activity="created"
        ).first()

        self.assertIsNotNone(log1)
        assert log1 is not None

        alert2 = self.create_alert_configuration(
            name="Alert with series index",
            insight=insight["id"],
            config={"type": "TrendsAlertConfig", "series_index": 1},
        )

        log2 = ActivityLog.objects.filter(
            team_id=self.team.id, scope="AlertConfiguration", item_id=str(alert2["id"]), activity="created"
        ).first()

        self.assertIsNotNone(log2)
        assert log2 is not None
        context2 = log2.detail["context"]
        self.assertEqual(context2["insight_id"], insight["id"])

    def test_alert_configuration_field_change_tracking(self):
        alert = self.create_alert_configuration("Alert for field tracking", enabled=True, calculation_interval="daily")

        # Test enabled field changes
        self.update_alert_configuration(alert["id"], {"enabled": False})
        disable_log = (
            ActivityLog.objects.filter(
                team_id=self.team.id, scope="AlertConfiguration", item_id=str(alert["id"]), activity="updated"
            )
            .order_by("-created_at")
            .first()
        )

        self.assertIsNotNone(disable_log)
        assert disable_log is not None
        changes = disable_log.detail.get("changes", [])
        enabled_change = next((change for change in changes if change.get("field") == "enabled"), None)
        self.assertIsNotNone(enabled_change)
        assert enabled_change is not None
        self.assertEqual(enabled_change["action"], "changed")
        self.assertTrue(enabled_change["before"])
        self.assertFalse(enabled_change["after"])

        # Test name field changes
        self.update_alert_configuration(alert["id"], {"name": "Updated Alert Name"})
        name_log = (
            ActivityLog.objects.filter(
                team_id=self.team.id, scope="AlertConfiguration", item_id=str(alert["id"]), activity="updated"
            )
            .order_by("-created_at")
            .first()
        )

        self.assertIsNotNone(name_log)
        assert name_log is not None
        changes = name_log.detail.get("changes", [])
        name_change = next((change for change in changes if change.get("field") == "name"), None)
        self.assertIsNotNone(name_change)
        assert name_change is not None
        self.assertEqual(name_change["action"], "changed")
        self.assertEqual(name_change["before"], "Alert for field tracking")
        self.assertEqual(name_change["after"], "Updated Alert Name")

        # Test calculation_interval field changes
        self.update_alert_configuration(alert["id"], {"calculation_interval": "hourly"})
        interval_log = (
            ActivityLog.objects.filter(
                team_id=self.team.id, scope="AlertConfiguration", item_id=str(alert["id"]), activity="updated"
            )
            .order_by("-created_at")
            .first()
        )

        self.assertIsNotNone(interval_log)
        assert interval_log is not None
        changes = interval_log.detail.get("changes", [])
        interval_change = next((change for change in changes if change.get("field") == "calculation_interval"), None)
        self.assertIsNotNone(interval_change)
        assert interval_change is not None
        self.assertEqual(interval_change["action"], "changed")
        self.assertEqual(interval_change["before"], "daily")
        self.assertEqual(interval_change["after"], "hourly")

    def test_alert_configuration_threshold_update_logging(self):
        alert = self.create_alert_configuration(
            name="Alert for threshold update",
            threshold={"configuration": {"type": "absolute", "bounds": {"lower": 100, "upper": 1000}}},
        )

        self.update_alert_configuration(alert["id"], {"name": "Updated Alert Name"})

        update_log = ActivityLog.objects.filter(
            team_id=self.team.id, scope="AlertConfiguration", item_id=str(alert["id"]), activity="updated"
        ).first()

        self.assertIsNotNone(update_log)
        assert update_log is not None
        self.assertIsNotNone(update_log.detail)
        self.assertIsNotNone(update_log.detail.get("context"))

    def test_alert_configuration_activity_log_properties(self):
        alert = self.create_alert_configuration("Test alert properties")

        log = ActivityLog.objects.filter(
            team_id=self.team.id, scope="AlertConfiguration", item_id=str(alert["id"]), activity="created"
        ).first()

        self.assertIsNotNone(log)
        assert log is not None
        self.assertEqual(log.scope, "AlertConfiguration")
        self.assertEqual(log.activity, "created")
        self.assertEqual(log.item_id, str(alert["id"]))
        self.assertEqual(log.team_id, self.team.id)
        self.assertEqual(log.organization_id, self.organization.id)
        self.assertEqual(log.user, self.user)
        self.assertFalse(log.was_impersonated or False)
        self.assertFalse(log.is_system or False)

        self.assertIsNotNone(log.detail)
        detail = log.detail
        self.assertEqual(detail["name"], alert["name"])
        self.assertIsNotNone(detail.get("context"))
        self.assertIsNotNone(detail.get("changes"))

    def test_threshold_activity_logging(self):
        alert = self.create_alert_configuration(
            name="Alert with threshold",
            threshold={"configuration": {"type": "absolute", "bounds": {"lower": 100, "upper": 500}}},
        )

        self.update_alert_configuration(
            alert["id"], {"threshold": {"configuration": {"type": "absolute", "bounds": {"lower": 200, "upper": 800}}}}
        )

        threshold_update_log = (
            ActivityLog.objects.filter(
                team_id=self.team.id, scope="AlertConfiguration", item_id=str(alert["id"]), activity="updated"
            )
            .order_by("-created_at")
            .first()
        )

        self.assertIsNotNone(threshold_update_log)
        assert threshold_update_log is not None
        self.assertIsNotNone(threshold_update_log.detail)
        self.assertEqual(threshold_update_log.detail.get("type"), "threshold_change")

        changes = threshold_update_log.detail.get("changes", [])
        config_change = next((change for change in changes if change.get("field") == "configuration"), None)
        self.assertIsNotNone(config_change)
        assert config_change is not None
        self.assertEqual(config_change["action"], "changed")

    def test_alert_subscription_activity_logging(self):
        from posthog.models import User
        from posthog.models.alert import AlertSubscription

        alert = self.create_alert_configuration("Alert for subscription")
        other_user = User.objects.create_and_join(
            organization=self.organization,
            email="subscriber@posthog.com",
            password="password",
        )

        AlertSubscription.objects.create(
            user=other_user,
            alert_configuration_id=alert["id"],
            created_by=self.user,
        )

        subscription_logs = ActivityLog.objects.filter(
            team_id=self.team.id, scope="AlertConfiguration", item_id=str(alert["id"])
        ).filter(detail__type="alert_subscription_change")

        self.assertTrue(len(subscription_logs) > 0)
        subscription_log = subscription_logs.first()
        self.assertIsNotNone(subscription_log)

    def test_alert_subscription_deletion_logging(self):
        from posthog.models import User
        from posthog.models.alert import AlertSubscription

        alert = self.create_alert_configuration("Alert for deletion")
        other_user = User.objects.create_and_join(
            organization=self.organization,
            email="to_delete@posthog.com",
            password="password",
        )

        subscription = AlertSubscription.objects.create(
            user=other_user,
            alert_configuration_id=alert["id"],
            created_by=self.user,
        )

        subscription.delete()

        delete_logs = ActivityLog.objects.filter(
            team_id=self.team.id, scope="AlertConfiguration", item_id=str(alert["id"]), activity="deleted"
        ).filter(detail__type="alert_subscription_change")

        self.assertTrue(len(delete_logs) > 0)
        delete_log = delete_logs.first()
        self.assertIsNotNone(delete_log)
        assert delete_log is not None

        context = delete_log.detail.get("context", {})
        self.assertEqual(context["subscriber_email"], other_user.email)
