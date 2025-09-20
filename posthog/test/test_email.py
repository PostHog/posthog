from decimal import Decimal

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from posthog.email import CUSTOMER_IO_TEMPLATE_ID_MAP, EmailMessage, _send_email, sanitize_email_properties
from posthog.models import MessagingRecord, Organization, Person, Team, User
from posthog.models.instance_setting import override_instance_config


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

    def test_sanitize_email_properties(self) -> None:
        # Test with various types of input including potential HTML injection
        properties = {
            "name": 'Test User"><img src=1 onerror=alert(1)>',
            "project_name": '<script>alert("XSS")</script>',
            "nested": {
                "html_content": '<b>Bold text</b><img src="x" onerror="javascript:alert(1)">',
                "safe_number": 123,
            },
            "list_with_html": ["normal text", "<script>bad()</script>", 42],
            "decimal_value": Decimal("1.23"),
            "boolean_value": True,
            "none_value": None,
            "utm_tags": "utm_source=posthog&utm_medium=email&utm_campaign=test",
        }

        sanitized = sanitize_email_properties(properties)

        # Check that strings are properly escaped
        self.assertEqual(sanitized["name"], "Test User&quot;&gt;&lt;img src=1 onerror=alert(1)&gt;")
        self.assertEqual(sanitized["project_name"], "&lt;script&gt;alert(&quot;XSS&quot;)&lt;/script&gt;")

        # Check that nested dictionaries are sanitized
        self.assertEqual(
            sanitized["nested"]["html_content"],
            "&lt;b&gt;Bold text&lt;/b&gt;&lt;img src=&quot;x&quot; onerror=&quot;javascript:alert(1)&quot;&gt;",
        )

        # Check that numbers and booleans are preserved
        self.assertEqual(sanitized["nested"]["safe_number"], 123)
        self.assertEqual(sanitized["decimal_value"], 1.23)
        self.assertEqual(sanitized["boolean_value"], True)
        self.assertEqual(sanitized["none_value"], None)

        # Check that lists are sanitized
        self.assertEqual(sanitized["list_with_html"][0], "normal text")
        self.assertEqual(sanitized["list_with_html"][1], "&lt;script&gt;bad()&lt;/script&gt;")
        self.assertEqual(sanitized["list_with_html"][2], 42)

        # Check that utm_tags are not sanitized (to preserve valid URL query parameters)
        self.assertEqual(sanitized["utm_tags"], "utm_source=posthog&utm_medium=email&utm_campaign=test")

    def test_sanitize_email_properties_raises_for_unsupported_types(self) -> None:
        # Test that sanitize_email_properties raises TypeError for unsupported types
        properties = {
            "custom_object": type("CustomObject", (), {})(),  # Create a simple custom object
        }

        with self.assertRaises(TypeError) as context:
            sanitize_email_properties(properties)

        # Check that the error message contains useful information
        self.assertIn("Unsupported type in email properties: CustomObject", str(context.exception))
        self.assertIn("Only str, int, float, bool, NoneType, Decimal", str(context.exception))

    def test_email_message_sanitizes_properties(self) -> None:
        # Test that EmailMessage constructor properly sanitizes template_context
        with override_instance_config("EMAIL_HOST", "localhost"):
            template_context = {
                "name": 'User"><img src=x onerror=alert(1)>',
                "project_name": '<script>alert("XSS")</script>',
                "utm_tags": "utm_source=posthog&utm_medium=email&utm_campaign=test_custom",
            }

            message = EmailMessage(
                campaign_key="test_campaign",
                subject="Test subject",
                template_name="2fa_enabled",
                template_context=template_context,
            )

            # Verify properties were sanitized
            self.assertEqual(message.properties["name"], "User&quot;&gt;&lt;img src=x onerror=alert(1)&gt;")
            self.assertEqual(message.properties["project_name"], "&lt;script&gt;alert(&quot;XSS&quot;)&lt;/script&gt;")

            # Verify utm_tags are preserved without sanitization
            self.assertEqual(
                message.properties["utm_tags"], "utm_source=posthog&utm_medium=email&utm_campaign=test_custom"
            )

            # Original template_context should be used for rendering (Django templates have their own escaping)
            self.assertIn("utm_source=posthog", message.properties["utm_tags"])

    def test_add_recipient_sanitizes_name(self) -> None:
        # Test that add_recipient properly sanitizes the name parameter
        with override_instance_config("EMAIL_HOST", "localhost"):
            message = EmailMessage(campaign_key="test_campaign", subject="Test subject", template_name="2fa_enabled")

            # Add recipient with a malicious name containing HTML/JavaScript
            message.add_recipient(email="test@example.com", name='Malicious"><script>alert("XSS")</script>')

            # Verify the name was properly sanitized in the recipient string
            self.assertEqual(
                message.to[0]["recipient"],
                '"Malicious&quot;&gt;&lt;script&gt;alert(&quot;XSS&quot;)&lt;/script&gt;" <test@example.com>',
            )

            # Raw email should remain unchanged
            self.assertEqual(message.to[0]["raw_email"], "test@example.com")
