from unittest.mock import patch

from freezegun import freeze_time

from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models import Organization, Team, User
from posthog.models.instance_setting import set_instance_setting
from posthog.models.messaging import MessagingRecord, get_email_hash
from posthog.models.organization import OrganizationMembership
from posthog.tasks.email import send_first_ingestion_reminder_emails, send_second_ingestion_reminder_emails
from posthog.test.base import APIBaseTest


def create_org_team_and_user(creation_date: str, email: str, ingested_event: bool = False) -> Organization:
    with freeze_time(creation_date):
        org = Organization.objects.create(name="too_late_org")
        Team.objects.create(organization=org, name="Default Project", ingested_event=ingested_event)
        User.objects.create_and_join(
            organization=org, email=email, password=None, level=OrganizationMembership.Level.OWNER,
        )
        return org


class TestEmail(APIBaseTest, ClickhouseTestMixin):
    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_first_email_sent_to_correct_users_only_once(self, _) -> None:
        set_instance_setting("EMAIL_HOST", "fake_host")
        set_instance_setting("EMAIL_ENABLED", True)
        create_org_team_and_user("2022-01-01 00:00:00", "too_late_user@posthog.com")
        create_org_team_and_user("2022-01-02 00:00:00", "ingested_event_in_range_user@posthog.com", ingested_event=True)
        create_org_team_and_user("2022-01-03 00:00:00", "too_early_user@posthog.com")
        in_range_org = create_org_team_and_user("2022-01-02 00:00:00", "in_range_user@posthog.com")
        User.objects.create_and_join(
            organization=in_range_org,
            email="in_range_user_not_admin@posthog.com",
            password=None,
            level=OrganizationMembership.Level.MEMBER,
        )

        with freeze_time("2022-01-03 15:00:00"):
            send_first_ingestion_reminder_emails()
            self.assertEqual(MessagingRecord.objects.all().count(), 2)
            self.assertEqual(
                set([record[0] for record in MessagingRecord.objects.all().values_list("email_hash")]),
                set(
                    [get_email_hash("in_range_user_not_admin@posthog.com"), get_email_hash("in_range_user@posthog.com")]
                ),
            )

            send_first_ingestion_reminder_emails()
            self.assertEqual(MessagingRecord.objects.all().count(), 2)

    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_second_first_email_sent_to_correct_users_only_once(self, _) -> None:
        set_instance_setting("EMAIL_HOST", "fake_host")
        set_instance_setting("EMAIL_ENABLED", True)
        create_org_team_and_user("2022-01-01 00:00:00", "too_late_user@posthog.com")
        create_org_team_and_user("2022-01-02 00:00:00", "ingested_event_in_range_user@posthog.com", ingested_event=True)
        create_org_team_and_user("2022-01-03 00:00:00", "too_early_user@posthog.com")
        in_range_org = create_org_team_and_user("2022-01-02 00:00:00", "in_range_user@posthog.com")
        User.objects.create_and_join(
            organization=in_range_org,
            email="in_range_user_not_admin@posthog.com",
            password=None,
            level=OrganizationMembership.Level.MEMBER,
        )

        with freeze_time("2022-01-06 15:00:00"):
            send_second_ingestion_reminder_emails()
            self.assertEqual(MessagingRecord.objects.all().count(), 2)
            self.assertEqual(
                set([record[0] for record in MessagingRecord.objects.all().values_list("email_hash")]),
                set(
                    [get_email_hash("in_range_user_not_admin@posthog.com"), get_email_hash("in_range_user@posthog.com")]
                ),
            )

            send_second_ingestion_reminder_emails()
            self.assertEqual(MessagingRecord.objects.all().count(), 2)
