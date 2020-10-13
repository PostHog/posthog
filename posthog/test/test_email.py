import datetime
from typing import List
from unittest.mock import patch

import pytz
from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time

from posthog.email import EmailMessage
from posthog.models import Event, Organization, Person, Team, User
from posthog.tasks.email import send_weekly_email_report


class TestEmail(TestCase):
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
        self.organization.members.add(self.user)
        self.organization.members.add(self.user2)

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
                EmailMessage("Subject", "template")
            self.assertEqual(
                str(e.exception), "Email settings not configured! Set at least the EMAIL_HOST environment variable.",
            )

    @freeze_time("2020-09-21")
    def test_weekly_email_report(self) -> None:

        with self.settings(
            EMAIL_HOST="localhost", SITE_URL="http://localhost:9999",
        ):
            send_weekly_email_report()

        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[0].to, ["test@posthog.com"])
        self.assertEqual(mail.outbox[1].to, ["test2@posthog.com"])

        self.assertEqual(
            mail.outbox[0].subject, "PostHog weekly report for Sep 14, 2020 to Sep 20",
        )
        self.assertEqual(
            mail.outbox[0].body, "",
        )  # no plain-text version support yet

        html_message = mail.outbox[0].alternatives[0][0]  # type: ignore
        self.assertIn(
            "http://localhost:9999/static/posthog-logo.png", html_message,
        )  # absolute URLs are used

        self.assertIn('style="font-weight: 300"', html_message)  # CSS is inlined

        self.assertIn(
            "Your PostHog weekly report is ready! Your team had 6 active users last week! &#127881;", html_message,
        )  # preheader

    @patch("posthog.tasks.email.EmailMessage")
    @freeze_time("2020-09-21")
    def test_weekly_email_report_content(self, mock_email_message):

        with self.settings(EMAIL_HOST="localhost"):
            send_weekly_email_report()

        self.assertEqual(
            mock_email_message.call_args[0][0], "PostHog weekly report for Sep 14, 2020 to Sep 20",
        )  # Email subject
        self.assertEqual(mock_email_message.call_args[0][1], "weekly_report")

        template_context = mock_email_message.call_args[0][2]

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
