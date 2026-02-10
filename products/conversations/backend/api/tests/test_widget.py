import os
import uuid
import base64
import shutil
import tempfile

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from boto3 import resource
from botocore.config import Config
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import UploadedMedia
from posthog.models.comment import Comment
from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
)

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Status


class TestWidgetAPI(BaseTest):
    def setUp(self):
        super().setUp()
        self.widget_token = "test_widget_token_123"
        self.team.conversations_enabled = True
        self.team.conversations_settings = {"widget_public_token": self.widget_token}
        self.team.save()

        self.widget_session_id = str(uuid.uuid4())
        self.distinct_id = "user-123"

        self.client = APIClient()

    def _get_headers(self):
        return {"HTTP_X_CONVERSATIONS_TOKEN": self.widget_token}

    def test_authentication_required(self):
        response = self.client.post("/api/conversations/v1/widget/message", {"message": "Hello"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_authentication_invalid_token(self):
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {"message": "Hello"},
            HTTP_X_CONVERSATIONS_TOKEN="invalid_token",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_authentication_conversations_disabled(self):
        self.team.conversations_enabled = False
        self.team.save()
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {"message": "Hello", "widget_session_id": self.widget_session_id, "distinct_id": self.distinct_id},
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_message_creates_ticket(self):
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {
                "message": "Hello, I need help!",
                "widget_session_id": self.widget_session_id,
                "distinct_id": self.distinct_id,
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("ticket_id", response.json())
        self.assertIn("message_id", response.json())

        ticket = Ticket.objects.get(id=response.json()["ticket_id"])
        self.assertEqual(ticket.widget_session_id, self.widget_session_id)
        self.assertEqual(ticket.distinct_id, self.distinct_id)
        self.assertEqual(ticket.status, "new")
        self.assertEqual(ticket.unread_team_count, 1)

    def test_create_message_to_existing_ticket(self):
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id=self.distinct_id,
            channel_source="widget",
        )
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {
                "message": "Follow up message",
                "widget_session_id": self.widget_session_id,
                "distinct_id": self.distinct_id,
                "ticket_id": str(ticket.id),
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["ticket_id"], str(ticket.id))

    def test_create_message_updates_session_data_on_existing_ticket(self):
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id=self.distinct_id,
            channel_source="widget",
            session_id="old-session-id",
            session_context={"current_url": "/some-page", "replay_url": "https://app.posthog.com/replay/old"},
        )
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {
                "message": "Follow up message",
                "widget_session_id": self.widget_session_id,
                "distinct_id": self.distinct_id,
                "ticket_id": str(ticket.id),
                "session_id": "new-session-id",
                "session_context": {"replay_url": "https://app.posthog.com/replay/new"},
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ticket.refresh_from_db()
        self.assertEqual(ticket.session_id, "new-session-id")
        # session_context should merge, not replace - preserves current_url while updating replay_url
        self.assertEqual(ticket.session_context["current_url"], "/some-page")
        self.assertEqual(ticket.session_context["replay_url"], "https://app.posthog.com/replay/new")

    def test_create_message_wrong_widget_session_forbidden(self):
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="other-user",
            channel_source="widget",
        )
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {
                "message": "Trying to access other ticket",
                "widget_session_id": self.widget_session_id,
                "distinct_id": self.distinct_id,
                "ticket_id": str(ticket.id),
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_message_missing_widget_session_id(self):
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {"message": "Hello", "distinct_id": self.distinct_id},
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_message_missing_distinct_id(self):
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {"message": "Hello", "widget_session_id": self.widget_session_id},
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_message_empty_content(self):
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {
                "message": "",
                "widget_session_id": self.widget_session_id,
                "distinct_id": self.distinct_id,
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_message_with_traits(self):
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {
                "message": "Hello",
                "widget_session_id": self.widget_session_id,
                "distinct_id": self.distinct_id,
                "traits": {"name": "John", "email": "john@example.com"},
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ticket = Ticket.objects.get(id=response.json()["ticket_id"])
        self.assertEqual(ticket.anonymous_traits["name"], "John")
        self.assertEqual(ticket.anonymous_traits["email"], "john@example.com")

    def test_get_messages(self):
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id=self.distinct_id,
            channel_source="widget",
        )
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="First message",
            item_context={"author_type": "customer", "is_private": False},
        )
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="Response from team",
            item_context={"author_type": "team", "is_private": False},
        )

        response = self.client.get(
            f"/api/conversations/v1/widget/messages/{ticket.id}?widget_session_id={self.widget_session_id}",
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["messages"]), 2)
        self.assertEqual(response.json()["messages"][0]["content"], "First message")

    def test_get_messages_excludes_private(self):
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id=self.distinct_id,
            channel_source="widget",
        )
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="Public message",
            item_context={"author_type": "customer", "is_private": False},
        )
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="Private internal note",
            item_context={"author_type": "team", "is_private": True},
        )

        response = self.client.get(
            f"/api/conversations/v1/widget/messages/{ticket.id}?widget_session_id={self.widget_session_id}",
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["messages"]), 1)
        self.assertEqual(response.json()["messages"][0]["content"], "Public message")

    def test_get_messages_does_not_expose_is_private_field(self):
        """Verify is_private field is never sent to widget, even for public messages."""
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id=self.distinct_id,
            channel_source="widget",
        )
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="Public message",
            item_context={"author_type": "customer", "is_private": False},
        )

        response = self.client.get(
            f"/api/conversations/v1/widget/messages/{ticket.id}?widget_session_id={self.widget_session_id}",
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["messages"]), 1)
        # is_private should NOT be present in the response
        self.assertNotIn("is_private", response.json()["messages"][0])

    def test_get_messages_wrong_widget_session_forbidden(self):
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="other-user",
            channel_source="widget",
        )
        response = self.client.get(
            f"/api/conversations/v1/widget/messages/{ticket.id}?widget_session_id={self.widget_session_id}",
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_messages_ticket_not_found(self):
        fake_ticket_id = str(uuid.uuid4())
        response = self.client.get(
            f"/api/conversations/v1/widget/messages/{fake_ticket_id}?widget_session_id={self.widget_session_id}",
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_list_tickets(self):
        ticket1 = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id=self.distinct_id,
            channel_source="widget",
            status=Status.NEW,
        )
        ticket2 = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id=self.distinct_id,
            channel_source="widget",
            status=Status.RESOLVED,
        )
        # Ticket from another session - should not appear
        Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="other-user",
            channel_source="widget",
        )

        response = self.client.get(
            f"/api/conversations/v1/widget/tickets?widget_session_id={self.widget_session_id}",
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)
        ticket_ids = {t["id"] for t in response.json()["results"]}
        self.assertIn(str(ticket1.id), ticket_ids)
        self.assertIn(str(ticket2.id), ticket_ids)

    def test_list_tickets_filter_by_status(self):
        Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id=self.distinct_id,
            channel_source="widget",
            status=Status.NEW,
        )
        Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id=self.distinct_id,
            channel_source="widget",
            status=Status.RESOLVED,
        )

        response = self.client.get(
            f"/api/conversations/v1/widget/tickets?widget_session_id={self.widget_session_id}&status={Status.NEW}",
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["status"], Status.NEW)

    def test_mark_read(self):
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id=self.distinct_id,
            channel_source="widget",
            unread_customer_count=5,
        )

        response = self.client.post(
            f"/api/conversations/v1/widget/messages/{ticket.id}/read",
            {"widget_session_id": self.widget_session_id},
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["unread_count"], 0)

        ticket.refresh_from_db()
        self.assertEqual(ticket.unread_customer_count, 0)

    def test_mark_read_wrong_widget_session_forbidden(self):
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="other-user",
            channel_source="widget",
            unread_customer_count=5,
        )

        response = self.client.post(
            f"/api/conversations/v1/widget/messages/{ticket.id}/read",
            {"widget_session_id": self.widget_session_id},
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        ticket.refresh_from_db()
        self.assertEqual(ticket.unread_customer_count, 5)

    def test_honeypot_rejects_bot(self):
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {
                "message": "I am a bot",
                "widget_session_id": self.widget_session_id,
                "distinct_id": self.distinct_id,
                "_hp": "filled_by_bot",
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_widget_session_id_format(self):
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {
                "message": "Hello",
                "widget_session_id": "not-a-uuid",
                "distinct_id": self.distinct_id,
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_message_too_long(self):
        response = self.client.post(
            "/api/conversations/v1/widget/message",
            {
                "message": "x" * 6000,
                "widget_session_id": self.widget_session_id,
                "distinct_id": self.distinct_id,
            },
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TestWidgetCacheInvalidation(BaseTest):
    """Test that widget message creation invalidates unread count cache."""

    def setUp(self):
        super().setUp()
        self.widget_token = "test_widget_token_123"
        self.team.conversations_enabled = True
        self.team.conversations_settings = {"widget_public_token": self.widget_token}
        self.team.save()

        self.widget_session_id = str(uuid.uuid4())
        self.distinct_id = "user-123"

        self.client = APIClient()

    def _get_headers(self):
        return {"HTTP_X_CONVERSATIONS_TOKEN": self.widget_token}

    def test_create_message_new_ticket_invalidates_cache(self):
        with patch("products.conversations.backend.api.widget.invalidate_unread_count_cache") as mock_invalidate:
            response = self.client.post(
                "/api/conversations/v1/widget/message",
                {
                    "message": "Hello, I need help!",
                    "widget_session_id": self.widget_session_id,
                    "distinct_id": self.distinct_id,
                },
                **self._get_headers(),
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            mock_invalidate.assert_called_once_with(self.team.id)

    def test_create_message_existing_ticket_invalidates_cache(self):
        ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id=self.distinct_id,
            channel_source="widget",
        )

        with patch("products.conversations.backend.api.widget.invalidate_unread_count_cache") as mock_invalidate:
            response = self.client.post(
                "/api/conversations/v1/widget/message",
                {
                    "message": "Follow up message",
                    "widget_session_id": self.widget_session_id,
                    "distinct_id": self.distinct_id,
                    "ticket_id": str(ticket.id),
                },
                **self._get_headers(),
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            mock_invalidate.assert_called_once_with(self.team.id)


# Test fixtures
# Small valid PNG (1x1 pixel, red)
VALID_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="
)

# Small valid GIF (1x1 pixel)
VALID_GIF = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")

# HTML with PNG magic bytes (XSS attempt)
FAKE_PNG_HTML = b"\x89PNG\r\n\x1a\n<script>alert('xss')</script>"

# HTML with GIF magic bytes (XSS attempt)
FAKE_GIF_HTML = b"GIF89a<script>alert('xss')</script>"

# SVG with embedded script
SVG_WITH_SCRIPT = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert("xss")</script></svg>'

# JavaScript content
JAVASCRIPT_CONTENT = b"function malicious() { document.cookie; }"


TEST_BUCKET = "Test-Widget-Uploads"
MEDIA_ROOT = tempfile.mkdtemp()


def get_fixture_path(fixture_file: str) -> str:
    file_dir = os.path.dirname(__file__)
    return os.path.join(file_dir, "..", "..", "..", "..", "..", "posthog", "api", "test", "fixtures", fixture_file)


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class TestWidgetUploadAPI(BaseTest):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)
        # Clean up S3 test files
        try:
            s3 = resource(
                "s3",
                endpoint_url=OBJECT_STORAGE_ENDPOINT,
                aws_access_key_id=OBJECT_STORAGE_ACCESS_KEY_ID,
                aws_secret_access_key=OBJECT_STORAGE_SECRET_ACCESS_KEY,
                config=Config(signature_version="s3v4"),
                region_name="us-east-1",
            )
            bucket = s3.Bucket(OBJECT_STORAGE_BUCKET)
            bucket.objects.filter(Prefix=TEST_BUCKET).delete()
        except Exception:
            pass  # Ignore cleanup errors in tests
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.widget_token = "test_widget_token_123"
        self.team.conversations_enabled = True
        self.team.conversations_settings = {"widget_public_token": self.widget_token}
        self.team.save()

        self.widget_session_id = str(uuid.uuid4())
        self.client = APIClient()

    def _get_headers(self):
        return {"HTTP_X_CONVERSATIONS_TOKEN": self.widget_token}

    def _create_ticket(self):
        """Create a ticket for the current widget_session_id (required for uploads)."""
        return Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=self.widget_session_id,
            distinct_id="test-user",
            channel_source="widget",
        )

    # === Authentication Tests ===

    def test_upload_requires_authentication(self):
        fake_image = SimpleUploadedFile("test.png", VALID_PNG, content_type="image/png")
        response = self.client.post(
            "/api/conversations/v1/widget/upload",
            {"image": fake_image, "widget_session_id": self.widget_session_id},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_upload_invalid_token(self):
        fake_image = SimpleUploadedFile("test.png", VALID_PNG, content_type="image/png")
        response = self.client.post(
            "/api/conversations/v1/widget/upload",
            {"image": fake_image, "widget_session_id": self.widget_session_id},
            format="multipart",
            HTTP_X_CONVERSATIONS_TOKEN="invalid_token",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_upload_conversations_disabled(self):
        self.team.conversations_enabled = False
        self.team.save()

        fake_image = SimpleUploadedFile("test.png", VALID_PNG, content_type="image/png")
        response = self.client.post(
            "/api/conversations/v1/widget/upload",
            {"image": fake_image, "widget_session_id": self.widget_session_id},
            format="multipart",
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("products.conversations.backend.api.widget.posthoganalytics.feature_enabled", return_value=True)
    def test_upload_circuit_breaker_disabled(self, mock_feature_flag):
        """Circuit breaker: disable-widget-uploads feature flag stops all uploads."""
        fake_image = SimpleUploadedFile("test.png", VALID_PNG, content_type="image/png")
        response = self.client.post(
            "/api/conversations/v1/widget/upload",
            {"image": fake_image, "widget_session_id": self.widget_session_id},
            format="multipart",
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.json()["code"], "uploads_disabled")

    # === Authorization Tests ===

    def test_upload_requires_widget_session_id(self):
        fake_image = SimpleUploadedFile("test.png", VALID_PNG, content_type="image/png")
        response = self.client.post(
            "/api/conversations/v1/widget/upload",
            {"image": fake_image},
            format="multipart",
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("widget_session_id", response.json().get("details", {}))

    def test_upload_invalid_widget_session_id_format(self):
        fake_image = SimpleUploadedFile("test.png", VALID_PNG, content_type="image/png")
        response = self.client.post(
            "/api/conversations/v1/widget/upload",
            {"image": fake_image, "widget_session_id": "not-a-uuid"},
            format="multipart",
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_upload_requires_existing_ticket(self):
        # No ticket created - should fail
        fake_image = SimpleUploadedFile("test.png", VALID_PNG, content_type="image/png")
        response = self.client.post(
            "/api/conversations/v1/widget/upload",
            {"image": fake_image, "widget_session_id": self.widget_session_id},
            format="multipart",
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()["code"], "no_ticket")
        self.assertEqual(response.json()["error"], "Must have an active conversation to upload images")

    def test_upload_succeeds_with_existing_ticket(self):
        # Create a ticket first
        self._create_ticket()

        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            fake_image = SimpleUploadedFile("test.png", VALID_PNG, content_type="image/png")
            response = self.client.post(
                "/api/conversations/v1/widget/upload",
                {"image": fake_image, "widget_session_id": self.widget_session_id},
                format="multipart",
                **self._get_headers(),
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    # === Origin Validation Tests ===

    def test_upload_blocked_from_disallowed_origin(self):
        self.team.conversations_settings = {
            "widget_public_token": self.widget_token,
            "widget_domains": ["https://allowed.com"],
        }
        self.team.save()

        fake_image = SimpleUploadedFile("test.png", VALID_PNG, content_type="image/png")
        response = self.client.post(
            "/api/conversations/v1/widget/upload",
            {"image": fake_image, "widget_session_id": self.widget_session_id},
            format="multipart",
            HTTP_ORIGIN="https://malicious.com",
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()["error"], "Origin not allowed")

    def test_upload_allowed_from_permitted_origin(self):
        self._create_ticket()
        self.team.conversations_settings = {
            "widget_public_token": self.widget_token,
            "widget_domains": ["https://allowed.com"],
        }
        self.team.save()

        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            fake_image = SimpleUploadedFile("test.png", VALID_PNG, content_type="image/png")
            response = self.client.post(
                "/api/conversations/v1/widget/upload",
                {"image": fake_image, "widget_session_id": self.widget_session_id},
                format="multipart",
                HTTP_ORIGIN="https://allowed.com",
                **self._get_headers(),
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_upload_allowed_when_no_domains_configured(self):
        self._create_ticket()
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            fake_image = SimpleUploadedFile("test.png", VALID_PNG, content_type="image/png")
            response = self.client.post(
                "/api/conversations/v1/widget/upload",
                {"image": fake_image, "widget_session_id": self.widget_session_id},
                format="multipart",
                HTTP_ORIGIN="https://any-domain.com",
                **self._get_headers(),
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    # === File Validation Tests ===

    def test_upload_requires_image_file(self):
        self._create_ticket()
        response = self.client.post(
            "/api/conversations/v1/widget/upload",
            {"widget_session_id": self.widget_session_id},
            format="multipart",
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["code"], "no-image-provided")

    def test_upload_rejects_non_image_content_type_html(self):
        self._create_ticket()
        fake_file = SimpleUploadedFile("test.html", b"<html>test</html>", content_type="text/html")
        response = self.client.post(
            "/api/conversations/v1/widget/upload",
            {"image": fake_file, "widget_session_id": self.widget_session_id},
            format="multipart",
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)

    def test_upload_rejects_non_image_content_type_pdf(self):
        self._create_ticket()
        fake_file = SimpleUploadedFile("test.pdf", b"%PDF-1.4", content_type="application/pdf")
        response = self.client.post(
            "/api/conversations/v1/widget/upload",
            {"image": fake_file, "widget_session_id": self.widget_session_id},
            format="multipart",
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)

    def test_upload_rejects_file_exceeding_size_limit(self):
        self._create_ticket()
        # Create a file just over 4MB
        large_content = b"x" * (4 * 1024 * 1024 + 1)
        large_file = SimpleUploadedFile("large.png", large_content, content_type="image/png")
        response = self.client.post(
            "/api/conversations/v1/widget/upload",
            {"image": large_file, "widget_session_id": self.widget_session_id},
            format="multipart",
            **self._get_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["code"], "file_too_large")

    def test_upload_rejects_fake_image_magic_bytes(self):
        self._create_ticket()
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            # File with PNG magic bytes but actually contains HTML/script
            fake_image = SimpleUploadedFile("fake.png", FAKE_PNG_HTML, content_type="image/png")
            response = self.client.post(
                "/api/conversations/v1/widget/upload",
                {"image": fake_image, "widget_session_id": self.widget_session_id},
                format="multipart",
                **self._get_headers(),
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.json()["code"], "invalid_image")
            # Ensure no orphan record was created
            self.assertEqual(UploadedMedia.objects.count(), 0)

    # === XSS Prevention Tests ===

    def test_upload_rejects_svg_with_script(self):
        self._create_ticket()
        svg_file = SimpleUploadedFile("test.svg", SVG_WITH_SCRIPT, content_type="image/svg+xml")
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            response = self.client.post(
                "/api/conversations/v1/widget/upload",
                {"image": svg_file, "widget_session_id": self.widget_session_id},
                format="multipart",
                **self._get_headers(),
            )
            # SVG should fail PIL validation as it's not a raster image
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_upload_rejects_html_disguised_as_image(self):
        self._create_ticket()
        html_content = b"<!DOCTYPE html><html><body><script>alert('xss')</script></body></html>"
        disguised_html = SimpleUploadedFile("malicious.png", html_content, content_type="image/png")
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            response = self.client.post(
                "/api/conversations/v1/widget/upload",
                {"image": disguised_html, "widget_session_id": self.widget_session_id},
                format="multipart",
                **self._get_headers(),
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.json()["code"], "invalid_image")

    def test_upload_rejects_fake_gif_magic_bytes(self):
        self._create_ticket()
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            # File with GIF magic bytes but actually contains HTML/script
            fake_gif = SimpleUploadedFile("fake.gif", FAKE_GIF_HTML, content_type="image/gif")
            response = self.client.post(
                "/api/conversations/v1/widget/upload",
                {"image": fake_gif, "widget_session_id": self.widget_session_id},
                format="multipart",
                **self._get_headers(),
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.json()["code"], "invalid_image")

    def test_upload_rejects_javascript_with_image_content_type(self):
        self._create_ticket()
        js_file = SimpleUploadedFile("script.png", JAVASCRIPT_CONTENT, content_type="image/png")
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            response = self.client.post(
                "/api/conversations/v1/widget/upload",
                {"image": js_file, "widget_session_id": self.widget_session_id},
                format="multipart",
                **self._get_headers(),
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.json()["code"], "invalid_image")

    def test_upload_rejects_empty_file(self):
        self._create_ticket()
        empty_file = SimpleUploadedFile("empty.png", b"", content_type="image/png")
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            response = self.client.post(
                "/api/conversations/v1/widget/upload",
                {"image": empty_file, "widget_session_id": self.widget_session_id},
                format="multipart",
                **self._get_headers(),
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.json()["code"], "invalid_image")

    # === Success Cases ===

    def test_upload_valid_png(self):
        self._create_ticket()
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            image_file = SimpleUploadedFile("test.png", VALID_PNG, content_type="image/png")
            response = self.client.post(
                "/api/conversations/v1/widget/upload",
                {"image": image_file, "widget_session_id": self.widget_session_id},
                format="multipart",
                **self._get_headers(),
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertIn("id", response.json())
            self.assertIn("image_location", response.json())
            self.assertIn("name", response.json())
            self.assertEqual(response.json()["name"], "test.png")

    def test_upload_valid_gif(self):
        self._create_ticket()
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            image_file = SimpleUploadedFile("test.gif", VALID_GIF, content_type="image/gif")
            response = self.client.post(
                "/api/conversations/v1/widget/upload",
                {"image": image_file, "widget_session_id": self.widget_session_id},
                format="multipart",
                **self._get_headers(),
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_upload_with_fixture_file(self):
        self._create_ticket()
        fixture_path = get_fixture_path("a-small-but-valid.gif")
        if os.path.exists(fixture_path):
            with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
                with open(fixture_path, "rb") as image:
                    response = self.client.post(
                        "/api/conversations/v1/widget/upload",
                        {"image": image, "widget_session_id": self.widget_session_id},
                        format="multipart",
                        **self._get_headers(),
                    )
                    self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_upload_returns_correct_response_format(self):
        self._create_ticket()
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            image_file = SimpleUploadedFile("my-image.png", VALID_PNG, content_type="image/png")
            response = self.client.post(
                "/api/conversations/v1/widget/upload",
                {"image": image_file, "widget_session_id": self.widget_session_id},
                format="multipart",
                **self._get_headers(),
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            data = response.json()

            # Verify response structure
            self.assertIn("id", data)
            self.assertIn("image_location", data)
            self.assertIn("name", data)

            # Verify id is a valid UUID
            uuid.UUID(data["id"])

            # Verify image_location format
            self.assertIn("/uploaded_media/", data["image_location"])

            # Verify name matches
            self.assertEqual(data["name"], "my-image.png")

    def test_upload_creates_media_record_without_user(self):
        self._create_ticket()
        with self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER=TEST_BUCKET):
            image_file = SimpleUploadedFile("test.png", VALID_PNG, content_type="image/png")
            response = self.client.post(
                "/api/conversations/v1/widget/upload",
                {"image": image_file, "widget_session_id": self.widget_session_id},
                format="multipart",
                **self._get_headers(),
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

            # Verify the media record was created without a user
            media = UploadedMedia.objects.get(id=response.json()["id"])
            self.assertIsNone(media.created_by)
            self.assertEqual(media.team_id, self.team.id)

    # === Object Storage Unavailable ===

    def test_upload_fails_when_object_storage_unavailable(self):
        self._create_ticket()
        with override_settings(OBJECT_STORAGE_ENABLED=False):
            image_file = SimpleUploadedFile("test.png", VALID_PNG, content_type="image/png")
            response = self.client.post(
                "/api/conversations/v1/widget/upload",
                {"image": image_file, "widget_session_id": self.widget_session_id},
                format="multipart",
                **self._get_headers(),
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.json()["code"], "object_storage_required")
