import datetime
import hashlib
from typing import List
from unittest.mock import patch

import pytz
from django.conf import settings
from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone
from freezegun import freeze_time

from posthog.email import EmailMessage, _send_email
from posthog.models import Event, MessagingRecord, Organization, Person, Team, User
from posthog.tasks.email import send_weekly_email_reports
from posthog.test.base import BaseTest


class TestEmail(BaseTest):
    def create_person(self, team: Team, base_distinct_id: str = "") -> Person:
        person = Person.objects.create(team=team)
        person.add_distinct_id(base_distinct_id)
        return person

    @freeze_time("2020-09-21")
    def setUp(self):
        super().setUp()
        self.organization = Organization.objects.create()
        self.team = Team.objects.create(organization=self.organization, name="The Bakery")
        self.user = User.objects.create(email="test@posthog.com")
        self.user2 = User.objects.create(email="test2@posthog.com")
        self.user_red_herring = User.objects.create(email="test+redherring@posthog.com")
        self.organization.members.add(self.user)
        self.organization.members.add(self.user2)
        self.organization.members.add(self.user_red_herring)

        MessagingRecord.objects.get_or_create(
            raw_email="test+redherring@posthog.com",
            campaign_key=f"weekly_report_for_team_{self.team.pk}_on_2020-09-14",
            defaults={"sent_at": timezone.now()},
        )  # This user should not get the emails

        last_week = datetime.datetime(2020, 9, 17, 3, 22, tzinfo=pytz.UTC)
        two_weeks_ago = datetime.datetime(2020, 9, 8, 19, 54, tzinfo=pytz.UTC)

        self.persons: List = [self.create_person(self.team, str(i)) for i in range(0, 7)]

        # Resurrected
        self.persons[0].created_at = timezone.now() - datetime.timedelta(weeks=3)
        self.persons[0].save()
        self.persons[1].created_at = timezone.now() - datetime.timedelta(weeks=4)
        self.persons[1].save()
        Event.objects.create(team=self.team, timestamp=last_week, distinct_id=0)
        Event.objects.create(team=self.team, timestamp=last_week, distinct_id=1)

        # Retained
        Event.objects.create(team=self.team, timestamp=last_week, distinct_id=2)
        Event.objects.create(team=self.team, timestamp=two_weeks_ago, distinct_id=2)
        Event.objects.create(team=self.team, timestamp=last_week, distinct_id=3)
        Event.objects.create(team=self.team, timestamp=two_weeks_ago, distinct_id=3)
        Event.objects.create(team=self.team, timestamp=last_week, distinct_id=4)
        Event.objects.create(team=self.team, timestamp=two_weeks_ago, distinct_id=4)

        # New
        Event.objects.create(team=self.team, timestamp=last_week, distinct_id=5)
        Event.objects.create(team=self.team, timestamp=last_week, distinct_id=5)

        # Churned
        Event.objects.create(team=self.team, timestamp=two_weeks_ago, distinct_id=6)

    def test_cant_send_emails_if_not_properly_configured(self) -> None:
        with self.settings(EMAIL_HOST=None):
            with self.assertRaises(ImproperlyConfigured) as e:
                EmailMessage("test_campaign", "Subject", "template")
            self.assertEqual(
                str(e.exception), "Email is not enabled in this instance.",
            )

        with self.settings(EMAIL_ENABLED=False):
            with self.assertRaises(ImproperlyConfigured) as e:
                EmailMessage("test_campaign", "Subject", "template")
            self.assertEqual(
                str(e.exception), "Email is not enabled in this instance.",
            )

    def test_cant_send_same_campaign_twice(self) -> None:
        sent_at = timezone.now()

        record, _ = MessagingRecord.objects.get_or_create(raw_email="test0@posthog.com", campaign_key="campaign_1")
        record.sent_at = sent_at
        record.save()

        with self.settings(
            EMAIL_HOST="localhost", CELERY_TASK_ALWAYS_EAGER=True,
        ):

            _send_email(
                campaign_key="campaign_1",
                to=[{"raw_email": "test0@posthog.com", "recipient": "Test Posthog <test0@posthog.com>"}],
                subject="Test email",
                headers={},
            )

        self.assertEqual(len(mail.outbox), 0)

        record.refresh_from_db()
        self.assertEqual(record.sent_at, sent_at)

    @freeze_time("2020-09-21")
    def test_weekly_email_report(self) -> None:

        record_count: int = MessagingRecord.objects.count()

        expected_recipients: List[str] = ["test@posthog.com", "test2@posthog.com"]

        with self.settings(
            EMAIL_HOST="localhost", SITE_URL="http://localhost:9999", CELERY_TASK_ALWAYS_EAGER=True,
        ):
            send_weekly_email_reports()

        self.assertSetEqual({",".join(outmail.to) for outmail in mail.outbox}, set(expected_recipients))

        self.assertEqual(
            mail.outbox[0].subject, "PostHog weekly report for Sep 14, 2020 to Sep 20",
        )

        self.assertEqual(
            mail.outbox[0].body, "",
        )  # no plain-text version support yet

        html_message = mail.outbox[0].alternatives[0][0]  # type: ignore
        self.validate_basic_html(
            html_message,
            "http://localhost:9999",
            preheader="Your PostHog weekly report is ready! Your team had 6 active users last week! &#127881;",
        )

        # Ensure records are properly saved to prevent duplicate emails
        self.assertEqual(MessagingRecord.objects.count(), record_count + 2)
        for email in expected_recipients:
            email_hash = hashlib.sha256(f"{settings.SECRET_KEY}_{email}".encode()).hexdigest()
            record = MessagingRecord.objects.get(
                email_hash=email_hash, campaign_key=f"weekly_report_for_team_{self.team.pk}_on_2020-09-14",
            )
            self.assertTrue((timezone.now() - record.sent_at).total_seconds() < 5)

    @patch("posthog.tasks.email.EmailMessage")
    @freeze_time("2020-09-21")
    def test_weekly_email_report_content(self, mock_email_message):

        with self.settings(
            EMAIL_HOST="localhost", CELERY_TASK_ALWAYS_EAGER=True,
        ):
            send_weekly_email_reports()

        self.assertEqual(
            mock_email_message.call_args[1]["campaign_key"], f"weekly_report_for_team_{self.team.pk}_on_2020-09-14",
        )  # Campaign key
        self.assertEqual(
            mock_email_message.call_args[1]["subject"], "PostHog weekly report for Sep 14, 2020 to Sep 20",
        )  # Email subject
        self.assertEqual(mock_email_message.call_args[1]["template_name"], "weekly_report")

        template_context = mock_email_message.call_args[1]["template_context"]

        self.assertEqual(template_context["team"], "The Bakery")
        self.assertEqual(
            template_context["period_start"], datetime.datetime(2020, 9, 14, tzinfo=pytz.UTC),
        )
        self.assertEqual(
            template_context["period_end"], datetime.datetime(2020, 9, 20, 23, 59, 59, 999999, tzinfo=pytz.UTC),
        )
        self.assertEqual(
            template_context["active_users"], 6,
        )
        self.assertEqual(
            template_context["active_users_delta"], 0.5,
        )
        self.assertEqual(
            round(template_context["user_distribution"]["new"], 2), 0.17,
        )
        self.assertEqual(
            template_context["user_distribution"]["retained"], 0.5,
        )
        self.assertEqual(
            round(template_context["user_distribution"]["resurrected"], 2), 0.33,
        )
        self.assertEqual(
            template_context["churned_users"], {"abs": 1, "ratio": 0.25, "delta": None},
        )
