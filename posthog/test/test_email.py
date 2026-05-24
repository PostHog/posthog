import datetime
import dataclasses
from decimal import Decimal
from typing import Any
from uuid import UUID

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from posthog.email import (
    CUSTOMER_IO_TEMPLATE_ID_MAP,
    EmailMessage,
    _send_email,
    _send_via_http,
    sanitize_email_properties,
)
from posthog.models import Organization, Person, Team, User
from posthog.models.instance_setting import override_instance_config
from posthog.models.messaging import MessagingRecord


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

    @patch("posthoganalytics.capture")
    @patch("posthog.email.requests.post")
    def test_send_via_http_success(self, mock_post, mock_capture) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"delivery_id": "test_delivery_id", "queued_at": 1604977406}
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

            mock_capture.assert_called_once_with(
                distinct_id="test@posthog.com",
                event="transactional email triggered",
                properties={
                    "template_name": "2fa_enabled",
                    "campaign_key": "test_campaign",
                    "recipient_email": "test@posthog.com",
                    "delivery_id": "test_delivery_id",
                    "queued_at": 1604977406,
                },
            )

    @patch("posthog.email.requests.post")
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

    @patch("posthog.email.requests.post")
    def test_send_via_http_api_error_reraises(self, mock_post) -> None:
        # _send_via_http must re-raise after capture_exception so the Celery task's
        # autoretry_for actually engages and synchronous callers (e.g. EmailVerifier)
        # can surface a user-visible failure instead of returning false success.
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        mock_post.return_value = mock_response

        with self.settings(CUSTOMER_IO_API_KEY="test-key"):
            with self.assertRaises(Exception) as ctx:
                _send_via_http(
                    to=[{"raw_email": "test@posthog.com", "recipient": "test@posthog.com"}],
                    campaign_key="test_campaign",
                    template_name="2fa_enabled",
                    properties={},
                )
            self.assertIn("Customer.io API error", str(ctx.exception))

            # The atomic block rolls back the record so a retry will re-create and resend.
            record = MessagingRecord.objects.filter(campaign_key="test_campaign").first()
            self.assertIsNone(record)

    @patch("posthog.email.requests.post")
    def test_send_via_http_retry_skips_already_sent_recipients(self, mock_post) -> None:
        # When a multi-recipient send fails partway, recipients already marked
        # sent_at on a prior attempt are skipped on retry so we don't double-send.
        sent_record, _ = MessagingRecord.objects.get_or_create(
            raw_email="already_sent@posthog.com", campaign_key="retry_campaign"
        )
        sent_record.sent_at = timezone.now()
        sent_record.save()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"delivery_id": "dlv", "queued_at": 1}
        mock_post.return_value = mock_response

        with self.settings(CUSTOMER_IO_API_KEY="test-key"):
            _send_via_http(
                to=[
                    {"raw_email": "already_sent@posthog.com", "recipient": "already_sent@posthog.com"},
                    {"raw_email": "first_try@posthog.com", "recipient": "first_try@posthog.com"},
                ],
                campaign_key="retry_campaign",
                template_name="2fa_enabled",
                properties={},
            )

            # Only the not-yet-sent recipient was sent to.
            self.assertEqual(mock_post.call_count, 1)
            self.assertEqual(mock_post.call_args.kwargs["json"]["to"], "first_try@posthog.com")

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

        # Check that nested dictionaries are sanitized — `javascript:` is defanged so
        # mail clients don't auto-link / treat it as a clickable scheme.
        self.assertEqual(
            sanitized["nested"]["html_content"],
            "&lt;b&gt;Bold text&lt;/b&gt;&lt;img src=&quot;x&quot; onerror=&quot;javascript:​alert(1)&quot;&gt;",
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

    def test_sanitize_email_properties_preserves_trusted_url_keys(self) -> None:
        # Clean PostHog-built URLs survive sanitization unchanged: html.escape is a
        # no-op on URL-shape characters (`:` `/` `.`), and trusted URL keys skip the
        # defang step so the link stays clickable.
        section: dict[str, str] = {"team_url": "https://app.posthog.com/project/3", "team_name": "Acme.com"}
        properties: dict[str, Any] = {
            "href": "http://localhost:8010/replay/test#panel=discussion",
            "url": "https://app.posthog.com/project/1/insights",
            "site_url": "https://app.posthog.com",
            "link": "/reset/uuid/token",
            "next_url": "https://app.posthog.com/dashboard",
            "dashboard_url": "https://app.posthog.com/dashboard/2",
            "error_tracking_url": "https://app.posthog.com/error_tracking",
            "verify_link": "/verify/abc",
            "section": section,
        }

        sanitized = sanitize_email_properties(properties)

        for key in [
            "href",
            "url",
            "site_url",
            "link",
            "next_url",
            "dashboard_url",
            "error_tracking_url",
            "verify_link",
        ]:
            self.assertEqual(sanitized[key], properties[key], f"trusted URL key {key} should pass through")
        self.assertEqual(sanitized["section"]["team_url"], section["team_url"])
        # ...but a user-controlled name nested under a non-URL key still gets defanged.
        self.assertEqual(sanitized["section"]["team_name"], "Acme.​com")

    def test_sanitize_email_properties_html_escapes_trusted_url_keys(self) -> None:
        # When a user-controlled fragment leaks into a trusted URL key (e.g. the
        # comment `slug` appended to settings.SITE_URL in build_comment_item_url),
        # attribute-injection characters are still escaped — the link works, but
        # the attacker can't break out of `<a href="...">`. URL-shape chars
        # (`:` `/` `.`) survive because we don't defang trusted keys.
        properties = {
            "href": 'https://app.posthog.com/x"><script>alert(1)</script>',
            "verify_link": "https://app.posthog.com/x?a=1&b=2",
        }

        sanitized = sanitize_email_properties(properties)

        self.assertEqual(
            sanitized["href"],
            "https://app.posthog.com/x&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;",
        )
        # `&` becomes `&amp;` — correct HTML attribute encoding for query strings.
        self.assertEqual(sanitized["verify_link"], "https://app.posthog.com/x?a=1&amp;b=2")

    def test_sanitize_email_properties_defangs_urls_embedded_in_user_content(self) -> None:
        # Realistic phishing-by-display-name: attacker sets first_name to a URL.
        # Mail clients should not auto-link this.
        properties = {
            "commenter": {"first_name": "Visit https://evil.com NOW"},
            "team": {"name": "evil.com"},
            "organization_name": "ｈｔｔｐ：／／phish.io",  # fullwidth bypass attempt
        }

        sanitized = sanitize_email_properties(properties)

        self.assertEqual(sanitized["commenter"]["first_name"], "Visit https:​//evil.​com NOW")
        self.assertEqual(sanitized["team"]["name"], "evil.​com")
        self.assertEqual(sanitized["organization_name"], "http:​//phish.​io")

    def test_sanitize_email_properties_handles_dataclasses(self) -> None:
        # Regression test: facade contracts (frozen dataclasses) used to raise TypeError,
        # silently killing tasks like send_error_tracking_issue_assigned via autoretry.
        # Mirror the real ErrorTrackingIssueAssignmentNotification shape — in particular
        # include a datetime field, since dataclasses.asdict() does not recurse into
        # datetime and the naive fix missed that.
        @dataclasses.dataclass(frozen=True)
        class Inner:
            id: UUID
            name: str | None
            description: str | None

        @dataclasses.dataclass(frozen=True)
        class Outer:
            id: UUID
            created_at: datetime.datetime
            issue: Inner

        outer = Outer(
            id=UUID("00000000-0000-0000-0000-000000000001"),
            created_at=datetime.datetime(2024, 1, 1, 12, 0, 0),
            issue=Inner(
                id=UUID("00000000-0000-0000-0000-000000000002"),
                name='<script>alert("xss")</script>',
                description=None,
            ),
        )

        sanitized = sanitize_email_properties({"assignment": outer})

        self.assertEqual(sanitized["assignment"]["id"], "00000000-0000-0000-0000-000000000001")
        self.assertEqual(sanitized["assignment"]["created_at"], "2024-01-01T12:00:00")
        self.assertEqual(sanitized["assignment"]["issue"]["id"], "00000000-0000-0000-0000-000000000002")
        self.assertEqual(
            sanitized["assignment"]["issue"]["name"],
            "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;",
        )
        self.assertIsNone(sanitized["assignment"]["issue"]["description"])

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

    def test_all_http_templates_are_registered_in_customer_io_map(self) -> None:
        # Every EmailMessage(use_http=True, template_name="X", ...) call in
        # production code under posthog/ needs "X" in CUSTOMER_IO_TEMPLATE_ID_MAP.
        # The Customer.io HTTP sender raises "Unknown template name" if it
        # isn't, and the Celery task wrapper swallows the exception via
        # capture_exception. Without this test, a new transactional email
        # added with a forgotten map entry sends zero emails and surfaces
        # nothing user-visible.
        import ast
        from pathlib import Path

        import posthog as posthog_pkg

        posthog_root = Path(posthog_pkg.__file__).parent
        sources = sorted(
            p
            for p in posthog_root.rglob("*.py")
            if "/test/" not in str(p) and "/tests/" not in str(p) and not p.name.startswith("test_")
        )

        missing: dict[str, str] = {}  # template_name -> first source path that uses it
        for source_path in sources:
            try:
                tree = ast.parse(source_path.read_text())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if not (isinstance(node.func, ast.Name) and node.func.id == "EmailMessage"):
                    continue
                kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg is not None}
                use_http = kwargs.get("use_http")
                if not (isinstance(use_http, ast.Constant) and use_http.value is True):
                    continue
                template_name = kwargs.get("template_name")
                if isinstance(template_name, ast.Constant) and isinstance(template_name.value, str):
                    if template_name.value not in CUSTOMER_IO_TEMPLATE_ID_MAP:
                        missing.setdefault(template_name.value, str(source_path.relative_to(posthog_root.parent)))

        self.assertEqual(
            missing,
            {},
            "These template_name values use use_http=True in production code but are missing "
            "from CUSTOMER_IO_TEMPLATE_ID_MAP in posthog/email.py. Add a map entry pointing to "
            "the Customer.io transactional message ID, otherwise the sender will raise "
            "'Unknown template name' at runtime and capture_exception will swallow it.",
        )
