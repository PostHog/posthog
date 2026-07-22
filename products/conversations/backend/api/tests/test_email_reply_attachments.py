from email import message_from_bytes

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile

from rest_framework import status

from posthog.models.comment import Comment
from posthog.models.team import Team
from posthog.models.uploaded_media import UploadedMedia

from products.conversations.backend.models import EmailChannel, EmailOutboxMessage, Ticket
from products.conversations.backend.models.constants import Channel, Status
from products.conversations.backend.tasks import _process_outbox_row


class TestOutboundEmailAttachments(BaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_settings = {"email_enabled": True}
        self.team.save()
        self.config = EmailChannel.objects.create(
            team=self.team,
            inbound_token="attachtest001",
            from_email="support@example.com",
            from_name="Support",
            domain="example.com",
            domain_verified=True,
        )
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.EMAIL,
            email_config=self.config,
            widget_session_id="",
            distinct_id="customer@external.com",
            email_from="customer@external.com",
            email_subject="Help",
            status=Status.OPEN,
        )
        self.blobs: dict[str, bytes] = {}

    def _media(self, team: Team, name: str, content: bytes) -> UploadedMedia:
        media = UploadedMedia.objects.create(
            team=team,
            file_name=name,
            content_type="application/octet-stream",
            media_location=f"loc/{team.id}/{name}",
        )
        self.blobs[media.media_location] = content
        return media

    def _send(self, attachment_media_ids: list[str]):
        comment = Comment.objects.create(
            team=self.team,
            created_by=self.user,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="see attached",
            item_context={
                "author_type": "support",
                "is_private": False,
                "attachment_media_ids": attachment_media_ids,
            },
        )
        outbox = EmailOutboxMessage.objects.create(
            team=self.team, ticket=self.ticket, comment=comment, message_id="<msg-a@example.com>"
        )

        def fake_read(location, missing_ok=False):
            return self.blobs.get(location)

        with patch(
            "products.conversations.backend.services.attachments.object_storage.read_bytes", side_effect=fake_read
        ):
            with patch("products.conversations.backend.tasks.send_mime") as mock_send:
                _process_outbox_row(outbox)
        return message_from_bytes(mock_send.call_args.args[1])

    def test_attachment_is_included_in_outbound_email(self) -> None:
        media = self._media(self.team, "howto.docx", b"cheat-sheet-bytes")
        parsed = self._send([str(media.id)])
        attached = {part.get_filename(): part.get_payload(decode=True) for part in parsed.walk() if part.get_filename()}
        assert attached == {"howto.docx": b"cheat-sheet-bytes"}

    def test_attachment_from_another_team_is_dropped(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        foreign = self._media(other_team, "secret.pdf", b"not-yours")
        parsed = self._send([str(foreign.id)])
        filenames = [part.get_filename() for part in parsed.walk() if part.get_filename()]
        assert filenames == []


class TestUploadAttachmentEndpoint(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_enabled = True
        self.team.save()
        self.url = f"/api/projects/{self.team.id}/conversations/tickets/upload_attachment/"

    def test_accepts_non_image_file(self) -> None:
        # The point of this endpoint: unlike the image-only media upload, it stores arbitrary files.
        stored = UploadedMedia.objects.create(
            team=self.team, file_name="howto.docx", content_type="application/octet-stream"
        )
        upload = SimpleUploadedFile("howto.docx", b"contents", content_type="application/octet-stream")
        with patch("products.conversations.backend.api.tickets.save_uploaded_media", return_value=stored) as mock_save:
            response = self.client.post(self.url, {"file": upload}, format="multipart")
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["id"] == str(stored.id)
        assert mock_save.call_args.kwargs["validate_images"] is False

    def test_rejects_oversized_file(self) -> None:
        upload = SimpleUploadedFile("big.bin", b"x" * 10, content_type="application/octet-stream")
        with patch("products.conversations.backend.api.tickets.MAX_OUTBOUND_ATTACHMENT_BYTES", 5):
            response = self.client.post(self.url, {"file": upload}, format="multipart")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
