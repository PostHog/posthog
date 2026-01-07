from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.test.activity_log_utils import ActivityLogTestHelper


class TestAlertActivityLogging(ActivityLogTestHelper):
    def test_alert_configuration_creation_activity_logging(self):
        alert = self.create_alert_configuration("Test alert")

        log = ActivityLog.objects.filter(
            team_id=self.team.id, scope="AlertConfiguration", item_id=str(alert["id"]), activity="created"
        ).first()
        assert log is not None
        assert log is not None
        assert log.detail is not None

    def test_alert_configuration_update_activity_logging(self):
        alert = self.create_alert_configuration("Original alert")

        self.update_alert_configuration(alert["id"], {"name": "Updated alert"})

        update_log = ActivityLog.objects.filter(
            team_id=self.team.id, scope="AlertConfiguration", item_id=str(alert["id"]), activity="updated"
        ).first()

        assert update_log is not None
        assert update_log is not None
        assert update_log.detail is not None

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

        assert log is not None
        assert log is not None
        assert log.detail is not None
        assert log.detail.get("context") is not None

        context = log.detail["context"]
        assert context["insight_id"] == insight["id"]
        assert context["insight_short_id"] == insight["short_id"]
        assert context["insight_name"] == insight["name"]

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

        assert log1 is not None
        assert log1 is not None

        alert2 = self.create_alert_configuration(
            name="Alert with series index",
            insight=insight["id"],
            config={"type": "TrendsAlertConfig", "series_index": 1},
        )

        log2 = ActivityLog.objects.filter(
            team_id=self.team.id, scope="AlertConfiguration", item_id=str(alert2["id"]), activity="created"
        ).first()

        assert log2 is not None
        assert log2 is not None
        context2 = log2.detail["context"]
        assert context2["insight_id"] == insight["id"]

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

        assert disable_log is not None
        assert disable_log is not None
        changes = disable_log.detail.get("changes", [])
        enabled_change = next((change for change in changes if change.get("field") == "enabled"), None)
        assert enabled_change is not None
        assert enabled_change is not None
        assert enabled_change["action"] == "changed"
        assert enabled_change["before"]
        assert not enabled_change["after"]

        # Test name field changes
        self.update_alert_configuration(alert["id"], {"name": "Updated Alert Name"})
        name_log = (
            ActivityLog.objects.filter(
                team_id=self.team.id, scope="AlertConfiguration", item_id=str(alert["id"]), activity="updated"
            )
            .order_by("-created_at")
            .first()
        )

        assert name_log is not None
        assert name_log is not None
        changes = name_log.detail.get("changes", [])
        name_change = next((change for change in changes if change.get("field") == "name"), None)
        assert name_change is not None
        assert name_change is not None
        assert name_change["action"] == "changed"
        assert name_change["before"] == "Alert for field tracking"
        assert name_change["after"] == "Updated Alert Name"

        # Test calculation_interval field changes
        self.update_alert_configuration(alert["id"], {"calculation_interval": "hourly"})
        interval_log = (
            ActivityLog.objects.filter(
                team_id=self.team.id, scope="AlertConfiguration", item_id=str(alert["id"]), activity="updated"
            )
            .order_by("-created_at")
            .first()
        )

        assert interval_log is not None
        assert interval_log is not None
        changes = interval_log.detail.get("changes", [])
        interval_change = next((change for change in changes if change.get("field") == "calculation_interval"), None)
        assert interval_change is not None
        assert interval_change is not None
        assert interval_change["action"] == "changed"
        assert interval_change["before"] == "daily"
        assert interval_change["after"] == "hourly"

    def test_alert_configuration_threshold_update_logging(self):
        alert = self.create_alert_configuration(
            name="Alert for threshold update",
            threshold={"configuration": {"type": "absolute", "bounds": {"lower": 100, "upper": 1000}}},
        )

        self.update_alert_configuration(alert["id"], {"name": "Updated Alert Name"})

        update_log = ActivityLog.objects.filter(
            team_id=self.team.id, scope="AlertConfiguration", item_id=str(alert["id"]), activity="updated"
        ).first()

        assert update_log is not None
        assert update_log is not None
        assert update_log.detail is not None
        assert update_log.detail.get("context") is not None

    def test_alert_configuration_activity_log_properties(self):
        alert = self.create_alert_configuration("Test alert properties")

        log = ActivityLog.objects.filter(
            team_id=self.team.id, scope="AlertConfiguration", item_id=str(alert["id"]), activity="created"
        ).first()

        assert log is not None
        assert log is not None
        assert log.scope == "AlertConfiguration"
        assert log.activity == "created"
        assert log.item_id == str(alert["id"])
        assert log.team_id == self.team.id
        assert log.organization_id == self.organization.id
        assert log.user == self.user
        assert not (log.was_impersonated or False)
        assert not (log.is_system or False)

        assert log.detail is not None
        detail = log.detail
        assert detail["name"] == alert["name"]
        assert detail.get("context") is not None
        assert detail.get("changes") is not None

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

        assert threshold_update_log is not None
        assert threshold_update_log is not None
        assert threshold_update_log.detail is not None
        assert threshold_update_log.detail.get("type") == "threshold_change"

        changes = threshold_update_log.detail.get("changes", [])
        config_change = next((change for change in changes if change.get("field") == "configuration"), None)
        assert config_change is not None
        assert config_change is not None
        assert config_change["action"] == "changed"

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

        assert len(subscription_logs) > 0
        subscription_log = subscription_logs.first()
        assert subscription_log is not None

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

        assert len(delete_logs) > 0
        delete_log = delete_logs.first()
        assert delete_log is not None
        assert delete_log is not None

        context = delete_log.detail.get("context", {})
        assert context["subscriber_email"] == other_user.email
