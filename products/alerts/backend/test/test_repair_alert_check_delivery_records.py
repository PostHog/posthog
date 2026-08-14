from datetime import timedelta

from posthog.test.base import APIBaseTest

from django.core.management import call_command
from django.utils import timezone

from posthog.schema import AlertConditionType, AlertState

from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration
from products.product_analytics.backend.models.insight import Insight


class TestRepairAlertCheckDeliveryRecords(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # relative to timezone.now() (not a hardcoded date) so ordering holds under freeze_time
        # leaked in from other alert test modules in the same run
        now = timezone.now()
        old_created_at = now - timedelta(hours=2)
        self.cutoff = (now - timedelta(hours=1)).isoformat()

        insight = Insight.objects.create(team=self.team, name="Test insight", created_by=self.user)
        self.alert = AlertConfiguration.objects.create(
            team=self.team,
            insight=insight,
            name="Test alert",
            condition={"type": AlertConditionType.ABSOLUTE_VALUE},
            created_by=self.user,
        )
        self.false_yes = AlertCheck.objects.create(
            alert_configuration=self.alert,
            state=AlertState.ERRORED,
            targets_notified={"users": ["a@example.com"]},
            notification_sent_at=old_created_at,
        )
        # disable_invalid_alert-style row: really sent, but never stamped
        self.disabled_row = AlertCheck.objects.create(
            alert_configuration=self.alert,
            state=AlertState.ERRORED,
            targets_notified={"users": ["a@example.com"]},
            notification_sent_at=None,
        )
        self.firing_row = AlertCheck.objects.create(
            alert_configuration=self.alert,
            state=AlertState.FIRING,
            targets_notified={"users": ["a@example.com"]},
            notification_sent_at=old_created_at,
        )
        # created_at is auto_now_add — backdate so the cutoff genuinely filters
        AlertCheck.objects.filter(id__in=[self.false_yes.id, self.disabled_row.id, self.firing_row.id]).update(
            created_at=old_created_at
        )

    def test_before_is_required(self) -> None:
        with self.assertRaises(Exception):
            call_command("repair_alert_check_delivery_records")

    def test_before_must_be_timezone_aware(self) -> None:
        with self.assertRaises(Exception):
            call_command("repair_alert_check_delivery_records", "--before", "2026-08-11T00:00:00")

    def test_dry_run_reports_without_writing(self) -> None:
        call_command("repair_alert_check_delivery_records", "--before", self.cutoff)

        self.false_yes.refresh_from_db()
        self.disabled_row.refresh_from_db()
        self.firing_row.refresh_from_db()
        assert self.false_yes.targets_notified == {"users": ["a@example.com"]}
        assert self.false_yes.notification_sent_at is not None
        assert self.disabled_row.targets_notified == {"users": ["a@example.com"]}
        assert self.firing_row.targets_notified == {"users": ["a@example.com"]}

    def test_execute_clears_only_stamped_errored_rows_before_cutoff(self) -> None:
        call_command("repair_alert_check_delivery_records", "--before", self.cutoff, "--execute")

        self.false_yes.refresh_from_db()
        self.disabled_row.refresh_from_db()
        self.firing_row.refresh_from_db()
        assert self.false_yes.targets_notified == {}
        assert self.false_yes.notification_sent_at is None
        assert self.disabled_row.targets_notified == {"users": ["a@example.com"]}
        assert self.firing_row.targets_notified == {"users": ["a@example.com"]}

    def test_execute_ignores_rows_after_cutoff(self) -> None:
        recent_false_yes = AlertCheck.objects.create(
            alert_configuration=self.alert,
            state=AlertState.ERRORED,
            targets_notified={"users": ["a@example.com"]},
            notification_sent_at=timezone.now(),
        )

        call_command("repair_alert_check_delivery_records", "--before", self.cutoff, "--execute")

        recent_false_yes.refresh_from_db()
        assert recent_false_yes.targets_notified == {"users": ["a@example.com"]}
