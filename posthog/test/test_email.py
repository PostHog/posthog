from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone
from freezegun import freeze_time
from unittest.mock import patch, MagicMock
from decimal import Decimal

from posthog.email import EmailMessage, _send_email
from posthog.models import MessagingRecord, Organization, Person, Team, User
from posthog.models.instance_setting import override_instance_config
from posthog.test.base import BaseTest
from posthog.email import CUSTOMER_IO_TEMPLATE_ID_MAP
from django.conf import settings


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

    def test_cant_send_emails_if_not_properly_configured(self) -> None:
        with override_instance_config("EMAIL_HOST", None):
            with self.assertRaises(ImproperlyConfigured) as e:
                EmailMessage(campaign_key="test_campaign", subject="Subject", template_name="template")
            self.assertEqual(str(e.exception), "Email is not enabled in this instance.")

        with override_instance_config("EMAIL_ENABLED", False):
            with self.assertRaises(ImproperlyConfigured) as e:
                EmailMessage(campaign_key="test_campaign", subject="Subject", template_name="template")
            self.assertEqual(str(e.exception), "Email is not enabled in this instance.")

    def test_cant_send_same_campaign_twice(self) -> None:
        with override_instance_config("EMAIL_HOST", "localhost"):
            sent_at = timezone.now()

            record, _ = MessagingRecord.objects.get_or_create(raw_email="test0@posthog.com", campaign_key="campaign_1")
            record.sent_at = sent_at
            record.save()

            with self.settings(CELERY_TASK_ALWAYS_EAGER=True):
                _send_email(
                    campaign_key="campaign_1",
                    to=[
                        {
                            "raw_email": "test0@posthog.com",
                            "recipient": "Test PostHog <test0@posthog.com>",
                        }
                    ],
                    subject="Test email",
                    headers={},
                )

            self.assertEqual(len(mail.outbox), 0)

            record.refresh_from_db()
            self.assertEqual(record.sent_at, sent_at)

    def test_applies_default_utm_tags(self) -> None:
        with override_instance_config("EMAIL_HOST", "localhost"):
            template = "async_migration_error"
            message = EmailMessage(campaign_key="test_campaign", subject="Subject", template_name=template)

            assert (
                f"https://posthog.com/questions?utm_source=posthog&amp;utm_medium=email&amp;utm_campaign={template}"
                in message.html_body
            )

    @patch("requests.post")
    def test_send_via_http_success(self, mock_post) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        with override_instance_config("EMAIL_HOST", "localhost"), self.settings(CUSTOMER_IO_API_KEY="test-key"):
            message = EmailMessage(
                campaign_key="test_campaign", subject="Test subject", template_name="2fa_enabled", use_http=True
            )
            message.add_recipient("test@posthog.com", "Test User")
            message.send(send_async=False)

            mock_post.assert_called_once_with(
                f"{settings.CUSTOMER_IO_API_URL}/v1/send/email",
                headers={
                    "Authorization": "Bearer test-key",
                    "Content-Type": "application/json",
                },
                json={
                    "to": "test@posthog.com",
                    "identifiers": {"email": "test@posthog.com"},
                    "transactional_message_id": CUSTOMER_IO_TEMPLATE_ID_MAP["2fa_enabled"],
                    "message_data": {"utm_tags": "utm_source=posthog&utm_medium=email&utm_campaign=2fa_enabled"},
                },
            )

    @patch("requests.post")
    def test_send_via_http_handles_decimal_values(self, mock_post) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        with override_instance_config("EMAIL_HOST", "localhost"), self.settings(CUSTOMER_IO_API_KEY="test-key"):
            message = EmailMessage(
                campaign_key="test_campaign",
                subject="Test subject",
                template_name="2fa_enabled",
                template_context={"decimal_value": Decimal("1.23")},
                use_http=True,
            )
            message.add_recipient("test@posthog.com")
            message.send(send_async=False)

            mock_post.assert_called_once_with(
                f"{settings.CUSTOMER_IO_API_URL}/v1/send/email",
                headers={
                    "Authorization": "Bearer test-key",
                    "Content-Type": "application/json",
                },
                json={
                    "to": "test@posthog.com",
                    "identifiers": {"email": "test@posthog.com"},
                    "transactional_message_id": CUSTOMER_IO_TEMPLATE_ID_MAP["2fa_enabled"],
                    "message_data": {
                        "decimal_value": 1.23,
                        "utm_tags": "utm_source=posthog&utm_medium=email&utm_campaign=2fa_enabled",
                    },
                },
            )

    @patch("requests.post")
    def test_send_via_http_api_error(self, mock_post) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        mock_post.return_value = mock_response

        with override_instance_config("EMAIL_HOST", "localhost"), self.settings(CUSTOMER_IO_API_KEY="test-key"):
            message = EmailMessage(
                campaign_key="test_campaign", subject="Test subject", template_name="2fa_enabled", use_http=True
            )
            message.add_recipient("test@posthog.com")

            # The error should be caught and logged, not raised
            message.send(send_async=False)

            # Verify the message wasn't marked as sent
            record = MessagingRecord.objects.filter(campaign_key="test_campaign").first()
            self.assertIsNone(record)
