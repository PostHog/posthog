import smtplib
from datetime import UTC, date, datetime
from typing import Literal

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core import mail
from django.db import DatabaseError
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import OrganizationMembership
from posthog.models.instance_setting import override_instance_config
from posthog.models.messaging import MessagingRecord

from products.customer_analytics.backend.facade.contracts import TaskDigestPreferences
from products.customer_analytics.backend.facade.tasks import schedule_task_digests
from products.customer_analytics.backend.logic.task_digest_delivery import (
    MAX_SEND_ATTEMPTS,
    TemporaryTaskDigestFailure,
    deliver_task_digest,
    task_digest_campaign_key,
    task_digest_scheduled_at,
)
from products.customer_analytics.backend.models import CustomerTask, UserCustomerAnalyticsConfig


class TestTaskDigestSchedule(SimpleTestCase):
    @parameterized.expand(
        [
            ("before", "2026-03-06T13:59:00+00:00", "09:00", "weekdays", None),
            ("winter", "2026-03-06T14:00:00+00:00", "09:00", "weekdays", "2026-03-06T14:00:00+00:00"),
            ("summer", "2026-03-09T13:00:00+00:00", "09:00", "weekdays", "2026-03-09T13:00:00+00:00"),
            ("weekend", "2026-03-08T13:00:00+00:00", "09:00", "weekdays", None),
            ("daily", "2026-03-08T13:00:00+00:00", "09:00", "every_day", "2026-03-08T13:00:00+00:00"),
            ("gap_before", "2026-03-08T07:15:00+00:00", "02:30", "every_day", None),
            ("gap", "2026-03-08T07:30:00+00:00", "02:30", "every_day", "2026-03-08T07:30:00+00:00"),
            ("fold", "2026-11-01T06:30:00+00:00", "01:30", "every_day", "2026-11-01T05:30:00+00:00"),
        ]
    )
    def test_project_local_schedule(
        self, _name: str, now: str, send_time: str, cadence: Literal["weekdays", "every_day"], expected: str | None
    ) -> None:
        preferences = TaskDigestPreferences(enabled=True, send_time=send_time, cadence=cadence)
        result = task_digest_scheduled_at(preferences, "America/New_York", datetime.fromisoformat(now))
        assert result == (datetime.fromisoformat(expected) if expected else None)


@time_machine.travel("2026-09-18T09:05:00Z", tick=False)
class TestTaskDigestDelivery(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(override_instance_config("EMAIL_HOST", "localhost"))
        self.enterContext(patch("posthoganalytics.feature_enabled", return_value=True))
        self.enterContext(patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True))
        self.team.timezone = "UTC"
        self.team.save(update_fields=["timezone"])
        self.config = UserCustomerAnalyticsConfig.objects.for_team(self.team.pk).create(
            team=self.team,
            user=self.user,
            properties={"task_digest": {"enabled": True, "send_time": "09:00", "cadence": "weekdays"}},
        )
        self.task = CustomerTask.objects.for_team(self.team.pk).create(
            team=self.team,
            assigned_to=self.user,
            name="Prepare example follow-up",
            due_at=datetime(2026, 9, 18, 12, tzinfo=UTC),
        )
        self.campaign_key = task_digest_campaign_key(self.team.pk, self.user.pk, date(2026, 9, 18))

    def test_accepted_send_and_repeated_scheduler_do_not_resend(self) -> None:
        with patch("products.customer_analytics.backend.facade.tasks.send_task_digest.delay") as enqueue:
            schedule_task_digests()
            enqueue.assert_called_once_with(self.team.pk, self.user.pk, "2026-09-18")
        deliver_task_digest(self.team.pk, self.user.pk, "2026-09-18")
        self.user.email = "changed@example.com"
        self.user.save(update_fields=["email"])
        deliver_task_digest(self.team.pk, self.user.pk, "2026-09-18")
        with patch("products.customer_analytics.backend.facade.tasks.send_task_digest.delay") as enqueue:
            schedule_task_digests()
            enqueue.assert_not_called()
        assert len(mail.outbox) == 1
        assert MessagingRecord.objects.get(campaign_key=self.campaign_key).sent_at is not None

    def test_ambiguous_send_failure_does_not_retry(self) -> None:
        message = MagicMock()
        message.send.side_effect = DatabaseError("delivery accepted before database failure")
        with patch(
            "products.customer_analytics.backend.logic.task_digest_delivery.build_customer_task_digest_email",
            return_value=message,
        ):
            with self.assertRaises(DatabaseError):
                deliver_task_digest(self.team.pk, self.user.pk, "2026-09-18")
            deliver_task_digest(self.team.pk, self.user.pk, "2026-09-18")

        message.send.assert_called_once_with(send_async=False, retry=False)
        record = MessagingRecord.objects.get(campaign_key=self.campaign_key)
        assert record.sent_at is None
        assert record.campaign_count == MAX_SEND_ATTEMPTS

    @parameterized.expand(
        [
            ("temporary", smtplib.SMTPDataError(451, b"Try later"), True),
            ("permanent", smtplib.SMTPDataError(550, b"Rejected"), False),
            ("no_acceptance", None, False),
        ]
    )
    def test_transport_failures_have_bounded_retry(self, _name: str, error: Exception | None, temporary: bool) -> None:
        with patch(
            "django.core.mail.backends.locmem.EmailBackend.send_messages", side_effect=error, return_value=0
        ) as send:
            for attempt in range(MAX_SEND_ATTEMPTS + 1):
                if temporary and attempt < MAX_SEND_ATTEMPTS - 1:
                    with self.assertRaises(TemporaryTaskDigestFailure):
                        deliver_task_digest(self.team.pk, self.user.pk, "2026-09-18")
                else:
                    deliver_task_digest(self.team.pk, self.user.pk, "2026-09-18")
            assert send.call_count == (MAX_SEND_ATTEMPTS if temporary else 1)
        record = MessagingRecord.objects.get(campaign_key=self.campaign_key)
        assert record.sent_at is None
        assert record.campaign_count == MAX_SEND_ATTEMPTS

    @parameterized.expand([("opt_out",), ("membership",), ("reassigned",), ("disabled",), ("flag",)])
    def test_current_state_is_checked_before_sending(self, change: str) -> None:
        if change == "opt_out":
            self.config.properties["task_digest"]["enabled"] = False
            self.config.save(update_fields=["properties"])
        elif change == "membership":
            OrganizationMembership.objects.filter(user=self.user, organization=self.organization).delete()
        elif change == "reassigned":
            self.task.assigned_to = None
            self.task.save(update_fields=["assigned_to"])
        elif change == "disabled":
            self.user.is_active = False
            self.user.save(update_fields=["is_active"])
        with patch("posthoganalytics.feature_enabled", return_value=change != "flag"):
            deliver_task_digest(self.team.pk, self.user.pk, "2026-09-18")
        assert len(mail.outbox) == 0
        assert not MessagingRecord.objects.filter(campaign_key=self.campaign_key, sent_at__isnull=False).exists()

    def test_missing_smtp_configuration_is_not_acceptance(self) -> None:
        with override_instance_config("EMAIL_HOST", None):
            deliver_task_digest(self.team.pk, self.user.pk, "2026-09-18")
        assert len(mail.outbox) == 0
        record = MessagingRecord.objects.get(campaign_key=self.campaign_key)
        assert record.sent_at is None
        assert record.campaign_count == MAX_SEND_ATTEMPTS
