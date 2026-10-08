from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models.comment import Comment

from products.conversations.backend.models import ConversationDeliveryPart, TeamConversationsSlackConfig, Ticket
from products.conversations.backend.models.constants import Channel
from products.conversations.backend.services.delivery import (
    DELIVERY_MAX_ATTEMPTS,
    DELIVERY_PART_KEY_BODY,
    DELIVERY_PART_KEY_FALLBACK,
    IMAGE_UPLOAD_STEP_BYTES,
    IMAGE_UPLOAD_STEP_COMPLETE,
    IMAGE_UPLOAD_STEP_GET,
    redrive_failed_delivery_part,
    slack_image_part_key,
)
from products.conversations.backend.slack import (
    _download_slack_image_bytes,
    extract_slack_files,
    split_slack_attachments,
)
from products.conversations.backend.tasks.slack import (
    _read_image_bytes_for_slack_upload,
    post_reply_to_slack,
    process_slack_delivery_part,
)

VALID_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)
GRANTED_FILE_SCOPES = ["chat:write", "files:read", "files:write"]


def fake_slack_team(slack_scopes: list[str] | None = GRANTED_FILE_SCOPES) -> MagicMock:
    """A team whose install granted the file scopes. None means an install predating scope records."""
    team = MagicMock()
    team.id = 1
    team.conversations_settings = {"slack_scopes": slack_scopes} if slack_scopes is not None else {}
    return team


def fake_slack_client() -> MagicMock:
    client = MagicMock()
    client.token = "xoxb-token"
    return client


class TestSlackImageIngest(SimpleTestCase):
    @patch("products.conversations.backend.slack.build_opener")
    def test_download_rejects_non_slack_host(self, mock_build_opener: MagicMock) -> None:
        image_bytes = _download_slack_image_bytes("https://example.com/a.png", "xoxb-token")
        assert image_bytes is None
        mock_build_opener.assert_not_called()

    @parameterized.expand(
        [
            ("sign_in_page_for_a_pdf", "text/html; charset=utf-8", "application/pdf", None),
            ("sign_in_page_for_an_image", "text/html", "image/png", None),
            ("genuine_html_attachment", "text/html", "text/html", b"<html>report</html>"),
            ("matching_content_type", "application/pdf", "application/pdf", b"%PDF-1.4 fake content"),
        ]
    )
    @patch("products.conversations.backend.slack.build_opener")
    def test_download_rejects_slack_sign_in_page(
        self,
        _label: str,
        content_type: str,
        expected_mimetype: str,
        expected_bytes: bytes | None,
        mock_build_opener: MagicMock,
    ) -> None:
        body = expected_bytes or b"<html>Sign in to Slack</html>"
        fake_response = MagicMock()
        fake_response.getcode.return_value = 200
        fake_response.headers = {"Content-Type": content_type}
        fake_response.read.return_value = body
        mock_build_opener.return_value.open.return_value.__enter__.return_value = fake_response

        payload = _download_slack_image_bytes(
            "https://files.slack.com/files-pri/T/F/report.pdf",
            "xoxb-token",
            expected_mimetype=expected_mimetype,
        )

        assert payload == expected_bytes

    @patch("products.conversations.backend.slack.save_file_to_uploaded_media")
    @patch("products.conversations.backend.slack._download_slack_image_bytes")
    def test_extract_slack_files_copies_to_uploaded_media(self, mock_download: MagicMock, mock_save: MagicMock) -> None:
        mock_download.return_value = VALID_PNG_BYTES
        mock_save.return_value = "https://app.posthog.com/uploaded_media/abc"

        fake_team = fake_slack_team()
        fake_client = fake_slack_client()

        files = [
            {
                "id": "F123",
                "mimetype": "image/png",
                "name": "test.png",
                "url_private_download": "https://files.slack.com/files-pri/T/F/test.png",
            }
        ]
        images = extract_slack_files(files, fake_team, fake_client)

        assert len(images) == 1
        assert images[0]["url"] == "https://app.posthog.com/uploaded_media/abc"
        mock_download.assert_called_once()
        mock_save.assert_called_once()

    @parameterized.expand(
        [
            ("with_permalink", "https://acme.slack.com/files/U1/F123/test.jpg", True),
            ("with_untrusted_permalink", "https://phish.example.com/files/U1/F123/test.jpg", False),
            ("without_permalink", None, False),
        ]
    )
    @patch("products.conversations.backend.slack.save_file_to_uploaded_media")
    @patch("products.conversations.backend.slack._download_slack_image_bytes")
    def test_extract_slack_files_falls_back_to_slack_link_when_download_fails(
        self,
        _label: str,
        permalink: str | None,
        expects_link: bool,
        mock_download: MagicMock,
        mock_save: MagicMock,
    ) -> None:
        mock_download.return_value = None
        fake_team = fake_slack_team()
        fake_client = fake_slack_client()

        files: list[dict] = [
            {
                "id": "F123",
                "mimetype": "image/jpeg",
                "name": "test.jpg",
                "url_private_download": "https://files.slack.com/files-pri/T/F/test.jpg",
            }
        ]
        if permalink:
            files[0]["permalink"] = permalink
        attachments = extract_slack_files(files, fake_team, fake_client)
        split = split_slack_attachments(attachments)

        mock_save.assert_not_called()
        # Nothing is re-hosted, so nothing can be inlined
        assert split.images == []
        if expects_link:
            # Rendered as a link instead of vanishing from the ticket
            assert split.files == [
                {"url": permalink, "name": "test.jpg", "mimetype": "image/jpeg", "unavailable": True}
            ]
        else:
            assert split.files == []

    @parameterized.expand(
        [
            ("install_predating_scope_records", None),
            ("install_without_files_read", ["chat:write", "files:write"]),
        ]
    )
    @patch("products.conversations.backend.slack.save_file_to_uploaded_media")
    @patch("products.conversations.backend.slack._download_slack_image_bytes")
    def test_extract_slack_files_does_not_download_without_files_read(
        self,
        _label: str,
        slack_scopes: list[str] | None,
        mock_download: MagicMock,
        mock_save: MagicMock,
    ) -> None:
        # A text/html attachment is the case content-type checks can't screen: Slack's sign-in page
        # and the real file are both HTML, so an under-scoped install must not fetch at all.
        permalink = "https://acme.slack.com/files/U1/F123/report.html"
        files = [
            {
                "id": "F123",
                "mimetype": "text/html",
                "name": "report.html",
                "url_private_download": "https://files.slack.com/files-pri/T/F/report.html",
                "permalink": permalink,
            }
        ]

        attachments = extract_slack_files(files, fake_slack_team(slack_scopes), fake_slack_client())

        mock_download.assert_not_called()
        mock_save.assert_not_called()
        assert attachments == [{"url": permalink, "name": "report.html", "mimetype": "text/html", "unavailable": True}]

    @patch("products.conversations.backend.slack.save_file_to_uploaded_media")
    @patch("products.conversations.backend.slack._download_slack_image_bytes")
    def test_extract_slack_files_skips_invalid_image_payload(
        self, mock_download: MagicMock, mock_save: MagicMock
    ) -> None:
        mock_download.return_value = b"not-an-image"
        fake_team = fake_slack_team()
        fake_client = fake_slack_client()

        files = [
            {
                "id": "F123",
                "mimetype": "image/png",
                "name": "test.png",
                "url_private_download": "https://files.slack.com/files-pri/T/F/test.png",
            }
        ]
        images = extract_slack_files(files, fake_team, fake_client)

        assert images == []
        mock_save.assert_not_called()

    @patch("products.conversations.backend.slack.save_file_to_uploaded_media")
    @patch("products.conversations.backend.slack._download_slack_image_bytes")
    def test_extract_slack_files_keeps_non_image_file(self, mock_download: MagicMock, mock_save: MagicMock) -> None:
        mock_download.return_value = b"%PDF-1.4 fake content"
        mock_save.return_value = "https://app.posthog.com/uploaded_media/pdf"

        fake_team = fake_slack_team()
        fake_client = fake_slack_client()

        files = [
            {
                "id": "F123",
                "mimetype": "application/pdf",
                "name": "invoice.pdf",
                "url_private_download": "https://files.slack.com/files-pri/T/F/invoice.pdf",
            }
        ]
        attachments = extract_slack_files(files, fake_team, fake_client)
        split = split_slack_attachments(attachments)

        assert split.images == []
        assert len(split.files) == 1
        assert split.files[0]["mimetype"] == "application/pdf"
        assert split.files[0]["name"] == "invoice.pdf"
        # Non-image bytes are stored without image validation
        assert mock_save.call_args.kwargs["validate_images"] is False

    @patch("products.conversations.backend.slack.save_file_to_uploaded_media")
    @patch("products.conversations.backend.slack._download_slack_image_bytes")
    def test_extract_slack_files_sanitizes_markdown_in_name(
        self, mock_download: MagicMock, mock_save: MagicMock
    ) -> None:
        mock_download.return_value = b"%PDF-1.4 fake content"
        mock_save.return_value = "https://app.posthog.com/uploaded_media/pdf"

        fake_team = fake_slack_team()
        fake_client = fake_slack_client()

        files = [
            {
                "id": "F123",
                "mimetype": "application/pdf",
                "name": "evil](https://phish.example.com).pdf",
                "url_private_download": "https://files.slack.com/files-pri/T/F/evil.pdf",
            }
        ]
        attachments = extract_slack_files(files, fake_team, fake_client)

        # Markdown link syntax stripped so the name can't inject a link
        assert "[" not in attachments[0]["name"]
        assert "]" not in attachments[0]["name"]


class TestSlackImageOutbound(SimpleTestCase):
    def test_outbound_reader_rejects_non_uploaded_media_urls(self) -> None:
        payload = _read_image_bytes_for_slack_upload(1, "https://example.com/test.png")
        assert payload is None

    @patch("products.conversations.backend.tasks.slack.resolve_slack_avatar_by_email", return_value=None)
    @patch("products.conversations.backend.tasks.slack.Team.objects.get")
    @patch("products.conversations.backend.tasks.slack._upload_image_to_slack_thread")
    @patch("products.conversations.backend.tasks.slack._read_image_bytes_for_slack_upload")
    @patch("products.conversations.backend.tasks.slack.get_slack_client")
    def test_post_reply_to_slack_uploads_rich_images(
        self,
        mock_get_client: MagicMock,
        mock_read_bytes: MagicMock,
        mock_upload_image: MagicMock,
        mock_team_get: MagicMock,
        _mock_avatar: MagicMock,
    ) -> None:
        fake_client = MagicMock()
        mock_get_client.return_value = fake_client
        mock_read_bytes.return_value = b"image-bytes"
        fake_team = MagicMock()
        fake_team.id = 1
        mock_team_get.return_value = fake_team

        rich_content = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Hello"},
                        {"type": "image", "attrs": {"src": "https://app.posthog.com/uploaded_media/a", "alt": "a.png"}},
                    ],
                }
            ],
        }

        post_reply_to_slack(
            ticket_id="ticket-1",
            team_id=1,
            content="Hello\n\n![a.png](https://app.posthog.com/uploaded_media/a)",
            rich_content=rich_content,
            author_name="Support",
            slack_channel_id="C123",
            slack_thread_ts="1700000000.000100",
        )

        fake_client.chat_postMessage.assert_called_once()
        mock_upload_image.assert_called_once()

    @parameterized.expand(
        [
            (
                "avatar_found",
                "https://avatars.slack-edge.com/agent_72.jpg",
                "https://avatars.slack-edge.com/agent_72.jpg",
            ),
            ("avatar_not_found", None, None),
        ]
    )
    @patch("products.conversations.backend.tasks.slack.Team.objects.get")
    @patch("products.conversations.backend.tasks.slack.get_slack_client")
    def test_post_reply_to_slack_icon_url_from_avatar(
        self,
        _label: str,
        avatar_url: str | None,
        expected_icon: str | None,
        mock_get_client: MagicMock,
        mock_team_get: MagicMock,
    ) -> None:
        fake_client = MagicMock()
        mock_get_client.return_value = fake_client
        fake_team = MagicMock()
        fake_team.id = 1
        fake_team.conversations_settings = {}
        mock_team_get.return_value = fake_team

        with patch("products.conversations.backend.tasks.slack.resolve_slack_avatar_by_email", return_value=avatar_url):
            post_reply_to_slack(
                ticket_id="ticket-avatar",
                team_id=1,
                content="Hello",
                rich_content=None,
                author_name="Alice Smith",
                author_email="alice@example.com",
                slack_channel_id="C123",
                slack_thread_ts="1700000000.000100",
            )

        call_kwargs = fake_client.chat_postMessage.call_args[1]
        assert call_kwargs["username"] == "Alice Smith"
        if expected_icon:
            assert call_kwargs["icon_url"] == expected_icon
        else:
            assert "icon_url" not in call_kwargs

    @patch("products.conversations.backend.tasks.slack.resolve_slack_avatar_by_email", return_value=None)
    @patch("products.conversations.backend.tasks.slack.Team.objects.get")
    @patch("products.conversations.backend.tasks.slack._upload_image_to_slack_thread")
    @patch("products.conversations.backend.tasks.slack._read_image_bytes_for_slack_upload")
    @patch("products.conversations.backend.tasks.slack.get_slack_client")
    def test_post_reply_to_slack_continues_when_image_upload_fails(
        self,
        mock_get_client: MagicMock,
        mock_read_bytes: MagicMock,
        mock_upload_image: MagicMock,
        mock_team_get: MagicMock,
        _mock_avatar: MagicMock,
    ) -> None:
        fake_client = MagicMock()
        mock_get_client.return_value = fake_client
        mock_read_bytes.return_value = b"image-bytes"
        mock_upload_image.side_effect = Exception("upload failed")
        fake_team = MagicMock()
        fake_team.id = 1
        mock_team_get.return_value = fake_team

        rich_content = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "image", "attrs": {"src": "https://app.posthog.com/uploaded_media/a"}}],
                }
            ],
        }

        post_reply_to_slack(
            ticket_id="ticket-2",
            team_id=1,
            content="",
            rich_content=rich_content,
            author_name="Support",
            slack_channel_id="C123",
            slack_thread_ts="1700000000.000100",
        )

        mock_upload_image.assert_called_once()
        fake_client.chat_postMessage.assert_called_once()


SLACK_UPLOAD_URL = "https://files.slack.com/upload/v1"


def _ok_upload_response() -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status.return_value = None
    return response


def _rich_images(*urls: str) -> dict:
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "image", "attrs": {"src": url, "alt": "img"}} for url in urls],
            }
        ],
    }


class TestSlackDurableImageDelivery(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team.conversations_enabled = True
        self.team.conversations_settings = {"slack_enabled": True}
        self.team.save()
        TeamConversationsSlackConfig.objects.update_or_create(
            team=self.team,
            defaults={"slack_team_id": "T123", "slack_bot_token": "xoxb-test"},
        )
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id="",
            distinct_id="slack-user",
            channel_source=Channel.SLACK,
            slack_channel_id="C123",
            slack_thread_ts="1700000000.000100",
        )
        self.image_a = uuid4()
        self.image_b = uuid4()
        self.url_a = f"https://app.posthog.com/uploaded_media/{self.image_a}"
        self.url_b = f"https://app.posthog.com/uploaded_media/{self.image_b}"
        wake_patcher = patch("products.conversations.backend.tasks.slack.wake_delivery_part")
        self.addCleanup(wake_patcher.stop)
        wake_patcher.start()

    def _create_reply(self, *image_urls: str) -> Comment:
        return Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="Support reply",
            rich_content=_rich_images(*image_urls) if image_urls else None,
            created_by=self.user,
            item_context={"author_type": "team", "is_private": False},
        )

    def _part(self, part_key: str) -> ConversationDeliveryPart:
        return ConversationDeliveryPart.objects.unscoped().select_related("delivery").get(part_key=part_key)

    def _slack_client(self, *, fail_on: str | None = None) -> MagicMock:
        client = MagicMock()
        client.chat_postMessage.return_value = {"ok": True, "ts": "1700.1"}

        def api_call(api_method: str, **_kwargs: object) -> dict[str, str | bool]:
            if fail_on == api_method:
                raise TimeoutError(f"{api_method} timed out")
            if api_method == "files.getUploadURLExternal":
                return {"ok": True, "upload_url": SLACK_UPLOAD_URL, "file_id": "F123"}
            if api_method == "files.completeUploadExternal":
                return {"ok": True}
            raise AssertionError(api_method)

        client.api_call.side_effect = api_call
        return client

    def _process_due(self, part: ConversationDeliveryPart) -> ConversationDeliveryPart:
        part.due_at = timezone.now()
        part.save(update_fields=["due_at", "updated_at"])
        process_slack_delivery_part(str(part.id))
        part.refresh_from_db()
        return part

    def _api_method_calls(self, client: MagicMock, method: str) -> int:
        return sum(1 for call in client.api_call.call_args_list if call.kwargs.get("api_method") == method)

    @patch("products.conversations.backend.tasks.slack.requests.post", return_value=_ok_upload_response())
    @patch("products.conversations.backend.tasks.slack._read_image_bytes_for_slack_upload", return_value=b"img")
    @patch("products.conversations.backend.tasks.slack.resolve_slack_avatar_by_email", return_value=None)
    @patch("products.conversations.backend.tasks.slack.get_slack_client")
    def test_body_success_enqueues_image_and_retry_does_not_repost_body(
        self,
        mock_get_client: MagicMock,
        _avatar: MagicMock,
        _read: MagicMock,
        mock_post: MagicMock,
    ) -> None:
        self._create_reply(self.url_a)
        client = self._slack_client()
        mock_get_client.return_value = client

        body = self._part(DELIVERY_PART_KEY_BODY)
        process_slack_delivery_part(str(body.id))
        body.refresh_from_db()
        image = self._part(slack_image_part_key(self.url_a))
        assert body.status == ConversationDeliveryPart.Status.ACCEPTED
        assert body.provider_message_id == "1700.1"
        assert image.status == ConversationDeliveryPart.Status.PENDING
        assert image.payload is not None
        assert image.payload["step"] == IMAGE_UPLOAD_STEP_GET
        mock_post.assert_not_called()
        assert client.chat_postMessage.call_count == 1

        self._process_due(image)
        image.refresh_from_db()
        assert image.status == ConversationDeliveryPart.Status.ACCEPTED
        assert image.provider_message_id == "F123"
        body.refresh_from_db()
        assert body.status == ConversationDeliveryPart.Status.ACCEPTED
        assert body.provider_message_id == "1700.1"
        assert client.chat_postMessage.call_count == 1
        mock_post.assert_called_once()

        process_slack_delivery_part(str(image.id))
        assert client.chat_postMessage.call_count == 1
        assert mock_post.call_count == 1

    @parameterized.expand(
        [
            (
                "get_upload",
                "files.getUploadURLExternal",
                False,
                IMAGE_UPLOAD_STEP_GET,
                0,
            ),
            (
                "byte_upload",
                "post",
                True,
                IMAGE_UPLOAD_STEP_BYTES,
                1,
            ),
            (
                "complete_upload",
                "files.completeUploadExternal",
                True,
                IMAGE_UPLOAD_STEP_COMPLETE,
                1,
            ),
        ]
    )
    @patch("products.conversations.backend.tasks.slack.requests.post")
    @patch("products.conversations.backend.tasks.slack._read_image_bytes_for_slack_upload", return_value=b"img")
    @patch("products.conversations.backend.tasks.slack.resolve_slack_avatar_by_email", return_value=None)
    @patch("products.conversations.backend.tasks.slack.get_slack_client")
    def test_resume_after_crash_between_substeps(
        self,
        _label: str,
        fail_on: str,
        persist_step: bool,
        expected_step: str,
        expected_posts_before_retry: int,
        mock_get_client: MagicMock,
        _avatar: MagicMock,
        _read: MagicMock,
        mock_post: MagicMock,
    ) -> None:
        self._create_reply(self.url_a)
        fail_method = fail_on if fail_on != "post" else None
        client = self._slack_client(fail_on=fail_method)
        mock_get_client.return_value = client
        if fail_on == "post":
            mock_post.side_effect = TimeoutError("byte upload timed out")
        else:
            mock_post.return_value = _ok_upload_response()

        body = self._part(DELIVERY_PART_KEY_BODY)
        process_slack_delivery_part(str(body.id))
        image = self._part(slack_image_part_key(self.url_a))
        self._process_due(image)

        assert image.status == ConversationDeliveryPart.Status.PENDING
        assert image.payload is not None
        if persist_step:
            assert image.payload["step"] == expected_step
            assert image.payload.get("file_id") == "F123"
        else:
            assert image.payload.get("step") in {IMAGE_UPLOAD_STEP_GET, None}
        assert mock_post.call_count == expected_posts_before_retry
        first_get_count = self._api_method_calls(client, "files.getUploadURLExternal")

        mock_post.side_effect = None
        mock_post.return_value = _ok_upload_response()
        client.api_call.side_effect = self._slack_client().api_call.side_effect
        self._process_due(image)

        assert image.status == ConversationDeliveryPart.Status.ACCEPTED
        second_get_count = self._api_method_calls(client, "files.getUploadURLExternal")
        if expected_step == IMAGE_UPLOAD_STEP_GET:
            assert second_get_count == first_get_count + 1
        else:
            assert second_get_count == first_get_count
        if expected_step == IMAGE_UPLOAD_STEP_COMPLETE:
            assert mock_post.call_count == expected_posts_before_retry
        else:
            assert mock_post.call_count == expected_posts_before_retry + 1
        body.refresh_from_db()
        assert body.status == ConversationDeliveryPart.Status.ACCEPTED
        assert client.chat_postMessage.call_count == 1

    @patch("products.conversations.backend.tasks.slack.requests.post", return_value=_ok_upload_response())
    @patch("products.conversations.backend.tasks.slack._read_image_bytes_for_slack_upload")
    @patch("products.conversations.backend.tasks.slack.resolve_slack_avatar_by_email", return_value=None)
    @patch("products.conversations.backend.tasks.slack.get_slack_client")
    def test_partial_success_posts_one_fallback_for_the_failed_image(
        self,
        mock_get_client: MagicMock,
        _avatar: MagicMock,
        mock_read: MagicMock,
        _post: MagicMock,
    ) -> None:
        self._create_reply(self.url_a, self.url_b)
        client = self._slack_client()
        mock_get_client.return_value = client
        mock_read.side_effect = lambda _team_id, url: None if url == self.url_b else b"img"

        process_slack_delivery_part(str(self._part(DELIVERY_PART_KEY_BODY).id))
        image_a = self._part(slack_image_part_key(self.url_a))
        image_b = self._part(slack_image_part_key(self.url_b))
        self._process_due(image_a)
        assert image_a.status == ConversationDeliveryPart.Status.ACCEPTED
        assert not ConversationDeliveryPart.objects.unscoped().filter(part_key=DELIVERY_PART_KEY_FALLBACK).exists()

        self._process_due(image_b)
        image_b.refresh_from_db()
        assert image_b.status == ConversationDeliveryPart.Status.FAILED
        fallback = self._part(DELIVERY_PART_KEY_FALLBACK)
        assert fallback.status == ConversationDeliveryPart.Status.PENDING
        assert fallback.client_msg_id
        assert fallback.payload is not None
        assert fallback.payload["urls"] == [self.url_b]

        self._process_due(fallback)
        assert fallback.status == ConversationDeliveryPart.Status.ACCEPTED
        assert client.chat_postMessage.call_count == 2
        fallback_kwargs = client.chat_postMessage.call_args_list[1].kwargs
        assert fallback_kwargs["client_msg_id"] == fallback.client_msg_id
        assert self.url_b in fallback_kwargs["text"]
        assert self.url_a not in fallback_kwargs["text"]

        self._process_due(image_b)
        assert ConversationDeliveryPart.objects.unscoped().filter(part_key=DELIVERY_PART_KEY_FALLBACK).count() == 1
        assert client.chat_postMessage.call_count == 2

    @patch("products.conversations.backend.tasks.slack._read_image_bytes_for_slack_upload", return_value=None)
    @patch("products.conversations.backend.tasks.slack.resolve_slack_avatar_by_email", return_value=None)
    @patch("products.conversations.backend.tasks.slack.get_slack_client")
    def test_two_permanent_image_failures_create_one_fallback(
        self,
        mock_get_client: MagicMock,
        _avatar: MagicMock,
        _read: MagicMock,
    ) -> None:
        self._create_reply(self.url_a, self.url_b)
        client = self._slack_client()
        mock_get_client.return_value = client

        process_slack_delivery_part(str(self._part(DELIVERY_PART_KEY_BODY).id))
        self._process_due(self._part(slack_image_part_key(self.url_a)))
        assert not ConversationDeliveryPart.objects.unscoped().filter(part_key=DELIVERY_PART_KEY_FALLBACK).exists()

        self._process_due(self._part(slack_image_part_key(self.url_b)))
        fallback = self._part(DELIVERY_PART_KEY_FALLBACK)
        assert fallback.client_msg_id
        assert fallback.payload is not None
        assert set(fallback.payload["urls"]) == {self.url_a, self.url_b}
        assert ConversationDeliveryPart.objects.unscoped().filter(part_key=DELIVERY_PART_KEY_FALLBACK).count() == 1

        process_slack_delivery_part(str(self._part(slack_image_part_key(self.url_a)).id))
        process_slack_delivery_part(str(self._part(slack_image_part_key(self.url_b)).id))
        assert ConversationDeliveryPart.objects.unscoped().filter(part_key=DELIVERY_PART_KEY_FALLBACK).count() == 1
        assert client.chat_postMessage.call_count == 1

    @patch("products.conversations.backend.tasks.slack._read_image_bytes_for_slack_upload", return_value=None)
    @patch("products.conversations.backend.tasks.slack.resolve_slack_avatar_by_email", return_value=None)
    @patch("products.conversations.backend.tasks.slack.get_slack_client")
    def test_redrive_failed_image_keeps_accepted_body(
        self,
        mock_get_client: MagicMock,
        _avatar: MagicMock,
        _read: MagicMock,
    ) -> None:
        self._create_reply(self.url_a)
        mock_get_client.return_value = self._slack_client()
        process_slack_delivery_part(str(self._part(DELIVERY_PART_KEY_BODY).id))
        image = self._process_due(self._part(slack_image_part_key(self.url_a)))
        body = self._part(DELIVERY_PART_KEY_BODY)
        assert image.status == ConversationDeliveryPart.Status.FAILED
        assert body.status == ConversationDeliveryPart.Status.ACCEPTED
        assert body.provider_message_id == "1700.1"

        result = redrive_failed_delivery_part(str(image.id), wake=MagicMock())
        assert result is not None
        body.refresh_from_db()
        body.delivery.refresh_from_db()
        image.refresh_from_db()
        assert body.status == ConversationDeliveryPart.Status.ACCEPTED
        assert body.provider_message_id == "1700.1"
        assert body.delivery.status == ConversationDeliveryPart.Status.ACCEPTED
        assert body.delivery.provider_message_id == "1700.1"
        assert image.status == ConversationDeliveryPart.Status.PENDING

    @patch("products.conversations.backend.tasks.slack.requests.post", return_value=_ok_upload_response())
    @patch("products.conversations.backend.tasks.slack._read_image_bytes_for_slack_upload")
    @patch("products.conversations.backend.tasks.slack.resolve_slack_avatar_by_email", return_value=None)
    @patch("products.conversations.backend.tasks.slack.get_slack_client")
    def test_fallback_does_not_post_after_redriven_image_succeeds(
        self,
        mock_get_client: MagicMock,
        _avatar: MagicMock,
        mock_read: MagicMock,
        _post: MagicMock,
    ) -> None:
        self._create_reply(self.url_a)
        client = self._slack_client()
        mock_get_client.return_value = client
        mock_read.return_value = None
        process_slack_delivery_part(str(self._part(DELIVERY_PART_KEY_BODY).id))
        image = self._process_due(self._part(slack_image_part_key(self.url_a)))
        fallback = self._part(DELIVERY_PART_KEY_FALLBACK)
        assert image.status == ConversationDeliveryPart.Status.FAILED
        assert fallback.status == ConversationDeliveryPart.Status.PENDING
        assert client.chat_postMessage.call_count == 1

        result = redrive_failed_delivery_part(str(image.id), wake=MagicMock())
        assert result is not None
        self._process_due(fallback)
        assert fallback.status == ConversationDeliveryPart.Status.PENDING
        assert client.chat_postMessage.call_count == 1

        mock_read.return_value = b"img"
        self._process_due(image)
        assert image.status == ConversationDeliveryPart.Status.ACCEPTED
        self._process_due(fallback)
        assert fallback.status == ConversationDeliveryPart.Status.ACCEPTED
        assert client.chat_postMessage.call_count == 1

    @patch("products.conversations.backend.tasks.slack.requests.post", return_value=_ok_upload_response())
    @patch("products.conversations.backend.tasks.slack._read_image_bytes_for_slack_upload")
    @patch("products.conversations.backend.tasks.slack.resolve_slack_avatar_by_email", return_value=None)
    @patch("products.conversations.backend.tasks.slack.get_slack_client")
    def test_fallback_wait_does_not_spend_the_retry_budget(
        self,
        mock_get_client: MagicMock,
        _avatar: MagicMock,
        mock_read: MagicMock,
        _post: MagicMock,
    ) -> None:
        self._create_reply(self.url_a)
        client = self._slack_client()
        mock_get_client.return_value = client
        mock_read.return_value = None
        process_slack_delivery_part(str(self._part(DELIVERY_PART_KEY_BODY).id))
        image = self._process_due(self._part(slack_image_part_key(self.url_a)))
        fallback = self._part(DELIVERY_PART_KEY_FALLBACK)
        assert redrive_failed_delivery_part(str(image.id), wake=MagicMock()) is not None

        for _ in range(DELIVERY_MAX_ATTEMPTS + 2):
            self._process_due(fallback)
            assert fallback.status == ConversationDeliveryPart.Status.PENDING
        assert fallback.attempts == 0
        assert fallback.last_error_code == "images_in_flight"
        assert client.chat_postMessage.call_count == 1

        self._process_due(self._part(slack_image_part_key(self.url_a)))
        self._process_due(fallback)
        assert fallback.status == ConversationDeliveryPart.Status.ACCEPTED
        assert self.url_a in client.chat_postMessage.call_args_list[1].kwargs["text"]

    @patch("products.conversations.backend.tasks.slack.requests.post", return_value=_ok_upload_response())
    @patch("products.conversations.backend.tasks.slack._read_image_bytes_for_slack_upload")
    @patch("products.conversations.backend.tasks.slack.resolve_slack_avatar_by_email", return_value=None)
    @patch("products.conversations.backend.tasks.slack.get_slack_client")
    def test_redriven_image_success_refreshes_waiting_fallback_urls(
        self,
        mock_get_client: MagicMock,
        _avatar: MagicMock,
        mock_read: MagicMock,
        _post: MagicMock,
    ) -> None:
        self._create_reply(self.url_a, self.url_b)
        client = self._slack_client()
        mock_get_client.return_value = client
        mock_read.return_value = None
        process_slack_delivery_part(str(self._part(DELIVERY_PART_KEY_BODY).id))
        self._process_due(self._part(slack_image_part_key(self.url_a)))
        image_a = self._part(slack_image_part_key(self.url_a))
        self._process_due(self._part(slack_image_part_key(self.url_b)))
        fallback = self._part(DELIVERY_PART_KEY_FALLBACK)
        assert fallback.payload is not None
        assert set(fallback.payload["urls"]) == {self.url_a, self.url_b}

        assert redrive_failed_delivery_part(str(image_a.id), wake=MagicMock()) is not None
        mock_read.side_effect = lambda _team_id, url: b"img" if url == self.url_a else None
        image_a = self._process_due(image_a)
        assert image_a.status == ConversationDeliveryPart.Status.ACCEPTED

        fallback.refresh_from_db()
        assert fallback.status == ConversationDeliveryPart.Status.PENDING
        assert fallback.payload is not None
        assert fallback.payload["urls"] == [self.url_b]
        assert fallback.due_at <= timezone.now()

        self._process_due(fallback)
        assert fallback.status == ConversationDeliveryPart.Status.ACCEPTED
        fallback_text = client.chat_postMessage.call_args_list[1].kwargs["text"]
        assert self.url_b in fallback_text
        assert self.url_a not in fallback_text

    @patch("products.conversations.backend.tasks.slack.requests.post")
    @patch("products.conversations.backend.tasks.slack._read_image_bytes_for_slack_upload", return_value=b"img")
    @patch("products.conversations.backend.tasks.slack.resolve_slack_avatar_by_email", return_value=None)
    @patch("products.conversations.backend.tasks.slack.get_slack_client")
    def test_expired_upload_url_resets_to_get_upload(
        self,
        mock_get_client: MagicMock,
        _avatar: MagicMock,
        _read: MagicMock,
        mock_post: MagicMock,
    ) -> None:
        self._create_reply(self.url_a)
        client = self._slack_client()
        mock_get_client.return_value = client
        expired = MagicMock()
        expired.status_code = 404
        mock_post.return_value = expired

        process_slack_delivery_part(str(self._part(DELIVERY_PART_KEY_BODY).id))
        image = self._process_due(self._part(slack_image_part_key(self.url_a)))

        assert image.status == ConversationDeliveryPart.Status.PENDING
        assert image.payload is not None
        assert image.payload["step"] == IMAGE_UPLOAD_STEP_GET
        assert "file_id" not in image.payload
        assert "upload_url" not in image.payload
        first_get_count = self._api_method_calls(client, "files.getUploadURLExternal")
        assert first_get_count == 1
        assert client.chat_postMessage.call_count == 1

        mock_post.return_value = _ok_upload_response()
        self._process_due(image)
        assert image.status == ConversationDeliveryPart.Status.ACCEPTED
        assert self._api_method_calls(client, "files.getUploadURLExternal") == first_get_count + 1
        assert client.chat_postMessage.call_count == 1

    @patch("products.conversations.backend.tasks.slack.requests.post", return_value=_ok_upload_response())
    @patch("products.conversations.backend.tasks.slack._read_image_bytes_for_slack_upload", return_value=b"img")
    @patch("products.conversations.backend.tasks.slack.resolve_slack_avatar_by_email", return_value=None)
    @patch("products.conversations.backend.tasks.slack.get_slack_client")
    def test_max_attempts_on_image_enqueues_fallback(
        self,
        mock_get_client: MagicMock,
        _avatar: MagicMock,
        _read: MagicMock,
        _post: MagicMock,
    ) -> None:
        self._create_reply(self.url_a)
        mock_get_client.return_value = self._slack_client()
        process_slack_delivery_part(str(self._part(DELIVERY_PART_KEY_BODY).id))
        image = self._part(slack_image_part_key(self.url_a))
        ConversationDeliveryPart.objects.unscoped().filter(id=image.id).update(attempts=DELIVERY_MAX_ATTEMPTS)

        self._process_due(image)
        assert image.status == ConversationDeliveryPart.Status.FAILED
        fallback = self._part(DELIVERY_PART_KEY_FALLBACK)
        assert fallback.status == ConversationDeliveryPart.Status.PENDING
        assert fallback.payload is not None
        assert fallback.payload["urls"] == [self.url_a]
        body = self._part(DELIVERY_PART_KEY_BODY)
        assert body.status == ConversationDeliveryPart.Status.ACCEPTED
        assert body.provider_message_id == "1700.1"

    @patch("products.conversations.backend.tasks.slack._read_image_bytes_for_slack_upload", return_value=b"img")
    @patch("products.conversations.backend.tasks.slack.resolve_slack_avatar_by_email", return_value=None)
    @patch("products.conversations.backend.tasks.slack.get_slack_client")
    def test_last_in_flight_attempt_enqueues_fallback(
        self,
        mock_get_client: MagicMock,
        _avatar: MagicMock,
        _read: MagicMock,
    ) -> None:
        self._create_reply(self.url_a)
        client = self._slack_client(fail_on="files.getUploadURLExternal")
        mock_get_client.return_value = client
        process_slack_delivery_part(str(self._part(DELIVERY_PART_KEY_BODY).id))
        image = self._part(slack_image_part_key(self.url_a))
        ConversationDeliveryPart.objects.unscoped().filter(id=image.id).update(attempts=DELIVERY_MAX_ATTEMPTS - 1)

        self._process_due(image)
        assert image.status == ConversationDeliveryPart.Status.FAILED
        fallback = self._part(DELIVERY_PART_KEY_FALLBACK)
        assert fallback.status == ConversationDeliveryPart.Status.PENDING
        assert fallback.payload is not None
        assert fallback.payload["urls"] == [self.url_a]
        assert client.chat_postMessage.call_count == 1
