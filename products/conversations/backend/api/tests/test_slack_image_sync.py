from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.conversations.backend.slack import (
    _download_slack_image_bytes,
    extract_slack_files,
    split_slack_attachments,
)
from products.conversations.backend.tasks import _read_image_bytes_for_slack_upload, post_reply_to_slack

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
        images, file_attachments = split_slack_attachments(attachments)

        mock_save.assert_not_called()
        # Nothing is re-hosted, so nothing can be inlined
        assert images == []
        if expects_link:
            # Rendered as a link instead of vanishing from the ticket
            assert file_attachments == [
                {"url": permalink, "name": "test.jpg", "mimetype": "image/jpeg", "unavailable": True}
            ]
        else:
            assert file_attachments == []

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
        images, file_attachments = split_slack_attachments(attachments)

        assert images == []
        assert len(file_attachments) == 1
        assert file_attachments[0]["mimetype"] == "application/pdf"
        assert file_attachments[0]["name"] == "invoice.pdf"
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

    @patch("products.conversations.backend.tasks.resolve_slack_avatar_by_email", return_value=None)
    @patch("products.conversations.backend.tasks.Team.objects.get")
    @patch("products.conversations.backend.tasks._upload_image_to_slack_thread")
    @patch("products.conversations.backend.tasks._read_image_bytes_for_slack_upload")
    @patch("products.conversations.backend.tasks.get_slack_client")
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
    @patch("products.conversations.backend.tasks.Team.objects.get")
    @patch("products.conversations.backend.tasks.get_slack_client")
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

        with patch("products.conversations.backend.tasks.resolve_slack_avatar_by_email", return_value=avatar_url):
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

    @patch("products.conversations.backend.tasks.resolve_slack_avatar_by_email", return_value=None)
    @patch("products.conversations.backend.tasks.Team.objects.get")
    @patch("products.conversations.backend.tasks._upload_image_to_slack_thread")
    @patch("products.conversations.backend.tasks._read_image_bytes_for_slack_upload")
    @patch("products.conversations.backend.tasks.get_slack_client")
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
