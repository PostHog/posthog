import hashlib
import smtplib
import datetime
import dataclasses
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.email import (
    CUSTOMER_IO_TEMPLATE_ID_MAP,
    EmailMessage,
    _send_email,
    _send_via_http,
    _send_via_smtp,
    sanitize_email_properties,
)
from posthog.models import Organization, Person, Team, User
from posthog.models.instance_setting import override_instance_config
from posthog.models.messaging import MessagingRecord, get_email_hash, get_email_hashes
from posthog.test.persons import (
    add_distinct_id as add_test_distinct_id,
    create_person as create_test_person,
)


class TestEmail(BaseTest):
    def create_person(self, team: Team, base_distinct_id: str = "") -> Person:
        person = create_test_person(team=team)
        add_test_distinct_id(person=person, distinct_id=base_distinct_id)
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

    def test_smtp_send_increments_sent_metric(self) -> None:
        # The charts alert reads posthog_email_send_total{outcome,transport}; this locks the
        # name + label contract so a removed/mislabelled increment can't silently blind it.
        labels = {"outcome": "sent", "transport": "smtp"}
        before = REGISTRY.get_sample_value("posthog_email_send_total", labels) or 0.0

        with override_instance_config("EMAIL_HOST", "localhost"):
            message = EmailMessage(
                campaign_key="metric_test_campaign", subject="Subject", template_name="async_migration_error"
            )
            message.add_recipient("metric-test@posthog.com")
            message.send(send_async=False)

        self.assertEqual(len(mail.outbox), 1)
        after = REGISTRY.get_sample_value("posthog_email_send_total", labels) or 0.0
        self.assertEqual(after - before, 1.0)

    @parameterized.expand(
        [
            ("transient_disconnect", smtplib.SMTPServerDisconnected("dropped"), True),
            ("transient_oserror", ConnectionResetError("reset"), True),
            ("transient_timeout", TimeoutError("hung relay"), True),
            # Send-path 4xx ("try again later") must re-raise so autoretry fires, not be swallowed.
            ("transient_data_greylist", smtplib.SMTPDataError(451, b"greylisted, try later"), True),
            ("transient_sender_421", smtplib.SMTPSenderRefused(421, b"service unavailable", "from@posthog.com"), True),
            (
                "transient_recipients_greylist",
                smtplib.SMTPRecipientsRefused({"x@posthog.com": (450, b"greylisted")}),
                True,
            ),
            ("permanent_auth", smtplib.SMTPAuthenticationError(535, b"bad creds"), False),
            ("permanent_data_5xx", smtplib.SMTPDataError(554, b"transaction failed"), False),
            ("permanent_recipients", smtplib.SMTPRecipientsRefused({}), False),
            (
                "permanent_recipients_5xx",
                smtplib.SMTPRecipientsRefused({"x@posthog.com": (550, b"no such user")}),
                False,
            ),
        ]
    )
    def test_smtp_error_retry_classification(self, name, exc, should_reraise) -> None:
        # Transient errors (connection drops + send-path 4xx greylisting/421) re-raise so autoretry
        # fires; auth/5xx/permanent stay swallowed (no retry-storm of the relay's per-IP limit).
        # Both record one failed metric.
        failed_labels = {"outcome": "failed", "transport": "smtp"}
        before = REGISTRY.get_sample_value("posthog_email_send_total", failed_labels) or 0.0

        with (
            override_instance_config("EMAIL_HOST", "localhost"),
            patch("django.core.mail.backends.locmem.EmailBackend.send_messages", side_effect=exc),
        ):
            kwargs: dict[str, Any] = {
                "to": [{"raw_email": f"{name}@posthog.com", "recipient": f"{name}@posthog.com"}],
                "campaign_key": f"retry_{name}",
                "subject": "Subject",
                "txt_body": "",
                "html_body": "<p>hi</p>",
                "headers": {},
            }
            if should_reraise:
                with self.assertRaises(type(exc)):
                    _send_via_smtp(**kwargs)
            else:
                _send_via_smtp(**kwargs)

        after = REGISTRY.get_sample_value("posthog_email_send_total", failed_labels) or 0.0
        self.assertEqual(after - before, 1.0)

    def test_smtp_transient_failure_preserves_already_sent_recipients(self) -> None:
        # A transient failure on a later recipient must not roll back the recipients already
        # accepted by the relay — otherwise the task's autoretry re-sends the whole batch and
        # duplicates the already-delivered emails. Each delivery commits its own `sent_at`.
        with (
            override_instance_config("EMAIL_HOST", "localhost"),
            patch(
                "django.core.mail.backends.locmem.EmailBackend.send_messages",
                side_effect=[1, smtplib.SMTPServerDisconnected("dropped mid-batch")],
            ),
        ):
            kwargs: dict[str, Any] = {
                "to": [
                    {"raw_email": "first@posthog.com", "recipient": "first@posthog.com"},
                    {"raw_email": "second@posthog.com", "recipient": "second@posthog.com"},
                ],
                "campaign_key": "batch_transient",
                "subject": "Subject",
                "txt_body": "",
                "html_body": "<p>hi</p>",
                "headers": {},
            }
            with self.assertRaises(smtplib.SMTPServerDisconnected):
                _send_via_smtp(**kwargs)

        first = MessagingRecord.objects.filter(
            email_hash__in=get_email_hashes("first@posthog.com"), campaign_key="batch_transient"
        ).first()
        self.assertIsNotNone(first)
        self.assertIsNotNone(first.sent_at)  # committed before the failure → a retry skips it
        second = MessagingRecord.objects.filter(
            email_hash__in=get_email_hashes("second@posthog.com"), campaign_key="batch_transient"
        ).first()
        self.assertIsNone(second)  # its transaction rolled back → retried fresh, no half-written row

    def test_smtp_connection_built_with_bounded_timeout(self) -> None:
        # Without a socket timeout a silently-hung relay pins the worker forever and the new
        # TimeoutError retry branch can never fire — so the backend must get a bounded timeout.
        mock_backend_cls = MagicMock()
        with (
            override_instance_config("EMAIL_HOST", "localhost"),
            override_instance_config("EMAIL_TIMEOUT", 17),
            patch("posthog.email.import_string", return_value=mock_backend_cls),
            self.settings(EMAIL_BACKEND="some.smtp.Backend"),
        ):
            _send_via_smtp(
                to=[{"raw_email": "t@posthog.com", "recipient": "t@posthog.com"}],
                campaign_key="timeout_kwarg",
                subject="Subject",
                txt_body="",
                html_body="<p>hi</p>",
                headers={},
            )

        self.assertEqual(mock_backend_cls.call_args.kwargs.get("timeout"), 17)

    @patch("posthog.email.requests.post")
    def test_send_via_http_failed_metric_counts_undelivered_recipients(self, mock_post) -> None:
        # `failed` must count every recipient that didn't get through (the failing one + any not yet
        # attempted), per recipient like `sent` — not once per batch — or the alertable failure rate
        # under-reports multi-recipient batches.
        ok = MagicMock(status_code=200)
        ok.json.return_value = {}
        bad = MagicMock(status_code=500, text="boom")
        mock_post.side_effect = [ok, bad]

        failed_labels = {"outcome": "failed", "transport": "http"}
        before = REGISTRY.get_sample_value("posthog_email_send_total", failed_labels) or 0.0

        with override_instance_config("EMAIL_HOST", "localhost"), self.settings(CUSTOMER_IO_API_KEY="test-key"):
            _send_via_http(
                to=[
                    {"raw_email": "a@posthog.com"},
                    {"raw_email": "b@posthog.com"},
                    {"raw_email": "c@posthog.com"},
                ],
                campaign_key="http_failcount",
                template_name="2fa_enabled",
                properties={},
            )

        after = REGISTRY.get_sample_value("posthog_email_send_total", failed_labels) or 0.0
        self.assertEqual(after - before, 2.0)  # b failed + c never attempted; a succeeded

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


class TestMessagingHashSalt(BaseTest):
    def test_get_email_hash_defaults_preserve_legacy_secret_key_hashes(self) -> None:
        # MESSAGING_HASH_SALT defaults to SECRET_KEY, so hashes written before the salt
        # was decoupled (SHA-256(SECRET_KEY + email)) stay valid. If this breaks, an
        # upgrade would orphan every existing email_hash and re-send live campaigns.
        with self.settings(MESSAGING_HASH_SALT=settings.SECRET_KEY, MESSAGING_HASH_SALT_FALLBACKS=[]):
            legacy = hashlib.sha256(f"{settings.SECRET_KEY}_a@b.com".encode()).hexdigest()
            self.assertEqual(get_email_hash("a@b.com"), legacy)
            self.assertEqual(get_email_hashes("a@b.com"), [legacy])

    def test_get_email_hashes_includes_primary_and_fallbacks_deduped(self) -> None:
        with self.settings(MESSAGING_HASH_SALT="new_salt", MESSAGING_HASH_SALT_FALLBACKS=["old_salt", "new_salt"]):
            primary = hashlib.sha256(b"new_salt_a@b.com").hexdigest()
            fallback = hashlib.sha256(b"old_salt_a@b.com").hexdigest()
            self.assertEqual(get_email_hash("a@b.com"), primary)
            # both salts present and the duplicate "new_salt" collapsed; order is irrelevant
            # since the result only feeds an `email_hash__in=` lookup
            self.assertEqual(set(get_email_hashes("a@b.com")), {primary, fallback})

    def test_unset_fallbacks_is_empty_list_not_blank_string(self) -> None:
        # An unset env var yields [] (not [""]) — get_list("") returns [], and the
        # settings parsing additionally strips any blanks. This is the invariant that
        # keeps an empty salt from ever reaching the hash.
        self.assertEqual(settings.MESSAGING_HASH_SALT_FALLBACKS, [])
        self.assertNotIn("", settings.MESSAGING_HASH_SALT_FALLBACKS)

    def test_get_email_hash_refuses_empty_primary_salt(self) -> None:
        # Empty primary salt is a misconfiguration (would write a brute-forceable hash):
        # the write path fails loud rather than silently degrade.
        with self.settings(MESSAGING_HASH_SALT=""):
            with self.assertRaises(ValueError):
                get_email_hash("a@b.com")

    def test_get_email_hashes_never_hashes_an_empty_salt(self) -> None:
        # Even if a blank slips into the fallback list (e.g. a stray comma in the env
        # var), it is skipped — the empty-salt hash is never produced.
        with self.settings(MESSAGING_HASH_SALT="new_salt", MESSAGING_HASH_SALT_FALLBACKS=["", "old_salt"]):
            primary = hashlib.sha256(b"new_salt_a@b.com").hexdigest()
            fallback = hashlib.sha256(b"old_salt_a@b.com").hexdigest()
            empty_salt_hash = hashlib.sha256(b"_a@b.com").hexdigest()
            hashes = get_email_hashes("a@b.com")
            self.assertEqual(set(hashes), {primary, fallback})
            self.assertNotIn(empty_salt_hash, hashes)

    def test_dedup_matches_record_written_under_fallback_salt(self) -> None:
        # Record written before rotation, under the old salt.
        with self.settings(MESSAGING_HASH_SALT="old_salt", MESSAGING_HASH_SALT_FALLBACKS=[]):
            MessagingRecord.objects.get_or_create(
                raw_email="rotate@posthog.com", campaign_key="c", defaults={"sent_at": timezone.now()}
            )

        # After rotation, with the old salt listed as a fallback, the existing record is
        # found and reused — no duplicate row, no re-send.
        with self.settings(MESSAGING_HASH_SALT="new_salt", MESSAGING_HASH_SALT_FALLBACKS=["old_salt"]):
            record, created = MessagingRecord.objects.get_or_create(raw_email="rotate@posthog.com", campaign_key="c")
            self.assertFalse(created)
            self.assertIsNotNone(record.sent_at)
            self.assertEqual(MessagingRecord.objects.filter(campaign_key="c").count(), 1)

    def test_dedup_misses_after_rotation_without_fallback(self) -> None:
        # Control for the test above: without the old salt as a fallback, the pre-rotation
        # record is unreachable and a fresh row is created — proving the fallback is what
        # bridges the rotation.
        with self.settings(MESSAGING_HASH_SALT="old_salt", MESSAGING_HASH_SALT_FALLBACKS=[]):
            MessagingRecord.objects.get_or_create(
                raw_email="rotate@posthog.com", campaign_key="c", defaults={"sent_at": timezone.now()}
            )

        with self.settings(MESSAGING_HASH_SALT="new_salt", MESSAGING_HASH_SALT_FALLBACKS=[]):
            _, created = MessagingRecord.objects.get_or_create(raw_email="rotate@posthog.com", campaign_key="c")
            self.assertTrue(created)
            self.assertEqual(MessagingRecord.objects.filter(campaign_key="c").count(), 2)

    def test_filter_by_raw_email_matches_across_salts(self) -> None:
        with self.settings(MESSAGING_HASH_SALT="old_salt", MESSAGING_HASH_SALT_FALLBACKS=[]):
            MessagingRecord.objects.get_or_create(
                raw_email="rotate@posthog.com", campaign_key="c", defaults={"sent_at": timezone.now()}
            )

        with self.settings(MESSAGING_HASH_SALT="new_salt", MESSAGING_HASH_SALT_FALLBACKS=["old_salt"]):
            self.assertTrue(
                # django-stubs' mypy plugin resolves filter() kwargs against model fields
                # and can't follow the manager's raw_email→email_hash__in remap.
                MessagingRecord.objects.filter(  # type: ignore[misc]
                    raw_email="rotate@posthog.com", campaign_key="c", sent_at__isnull=False
                ).exists()
            )


# Async tests live as standalone functions — the async ORM (afirst/aget_or_create) can't
# run inside BaseTest's wrapping transaction, so they need django_db(transaction=True).
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_aget_or_create_reuses_record_written_under_fallback_salt() -> None:
    with override_settings(MESSAGING_HASH_SALT="old_salt", MESSAGING_HASH_SALT_FALLBACKS=[]):
        original, created = await MessagingRecord.objects.aget_or_create(
            raw_email="async@posthog.com", campaign_key="c", defaults={"sent_at": timezone.now()}
        )
        assert created

    # After rotation the old salt is a fallback, so the read finds the existing record:
    # no duplicate row, no re-send.
    with override_settings(MESSAGING_HASH_SALT="new_salt", MESSAGING_HASH_SALT_FALLBACKS=["old_salt"]):
        found, created = await MessagingRecord.objects.aget_or_create(raw_email="async@posthog.com", campaign_key="c")
        assert not created
        assert found.pk == original.pk
        assert await MessagingRecord.objects.filter(campaign_key="c").acount() == 1


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_aget_or_create_writes_under_primary_salt_not_a_fallback() -> None:
    with override_settings(MESSAGING_HASH_SALT="primary_salt", MESSAGING_HASH_SALT_FALLBACKS=["other_salt"]):
        record, created = await MessagingRecord.objects.aget_or_create(raw_email="async@posthog.com", campaign_key="c")
        assert created
        assert record.email_hash == hashlib.sha256(b"primary_salt_async@posthog.com").hexdigest()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_aget_or_create_without_fallback_creates_duplicate_after_rotation() -> None:
    # Control: without the old salt as a fallback, the pre-rotation record is unreachable
    # and a fresh row is created — proving the fallback is what bridges the rotation.
    with override_settings(MESSAGING_HASH_SALT="old_salt", MESSAGING_HASH_SALT_FALLBACKS=[]):
        await MessagingRecord.objects.aget_or_create(
            raw_email="async@posthog.com", campaign_key="c", defaults={"sent_at": timezone.now()}
        )

    with override_settings(MESSAGING_HASH_SALT="new_salt", MESSAGING_HASH_SALT_FALLBACKS=[]):
        _, created = await MessagingRecord.objects.aget_or_create(raw_email="async@posthog.com", campaign_key="c")
        assert created
        assert await MessagingRecord.objects.filter(campaign_key="c").acount() == 2
