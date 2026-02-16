from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from products.conversations.backend.slack import _download_slack_image_bytes, extract_slack_files
from products.conversations.backend.tasks import _read_image_bytes_for_slack_upload, post_reply_to_slack

VALID_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)


class TestSlackImageIngest(SimpleTestCase):
    @patch("products.conversations.backend.slack.build_opener")
    def test_download_rejects_non_slack_host(self, mock_build_opener: MagicMock) -> None:
        image_bytes = _download_slack_image_bytes("https://example.com/a.png", "xoxb-token")
        assert image_bytes is None
        mock_build_opener.assert_not_called()

    @patch("products.conversations.backend.slack._save_image_to_uploaded_media")
    @patch("products.conversations.backend.slack._download_slack_image_bytes")
    def test_extract_slack_files_copies_to_uploaded_media(self, mock_download: MagicMock, mock_save: MagicMock) -> None:
        mock_download.return_value = VALID_PNG_BYTES
        mock_save.return_value = "https://app.posthog.com/uploaded_media/abc"

        fake_team = MagicMock()
        fake_team.id = 1
        fake_client = MagicMock()
        fake_client.token = "xoxb-token"

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

    @patch("products.conversations.backend.slack._save_image_to_uploaded_media")
    @patch("products.conversations.backend.slack._download_slack_image_bytes")
    def test_extract_slack_files_skips_failed_downloads(self, mock_download: MagicMock, mock_save: MagicMock) -> None:
        mock_download.return_value = None
        fake_team = MagicMock()
        fake_team.id = 1
        fake_client = MagicMock()
        fake_client.token = "xoxb-token"

        files = [
            {
                "id": "F123",
                "mimetype": "image/jpeg",
                "name": "test.jpg",
                "url_private_download": "https://files.slack.com/files-pri/T/F/test.jpg",
            }
        ]
        images = extract_slack_files(files, fake_team, fake_client)

        assert images == []
        mock_save.assert_not_called()

    @patch("products.conversations.backend.slack._save_image_to_uploaded_media")
    @patch("products.conversations.backend.slack._download_slack_image_bytes")
    def test_extract_slack_files_skips_invalid_image_payload(
        self, mock_download: MagicMock, mock_save: MagicMock
    ) -> None:
        mock_download.return_value = b"not-an-image"
        fake_team = MagicMock()
        fake_team.id = 1
        fake_client = MagicMock()
        fake_client.token = "xoxb-token"

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


class TestSlackImageOutbound(SimpleTestCase):
    def test_outbound_reader_rejects_non_uploaded_media_urls(self) -> None:
        payload = _read_image_bytes_for_slack_upload(1, "https://example.com/test.png")
        assert payload is None

    @patch("products.conversations.backend.tasks.Team.objects.get")
    @patch("products.conversations.backend.tasks._upload_image_to_slack_thread")
    @patch("products.conversations.backend.tasks._read_image_bytes_for_slack_upload")
    @patch("products.conversations.backend.slack.get_slack_client")
    def test_post_reply_to_slack_uploads_rich_images(
        self,
        mock_get_client: MagicMock,
        mock_read_bytes: MagicMock,
        mock_upload_image: MagicMock,
        mock_team_get: MagicMock,
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

    @patch("products.conversations.backend.tasks.Team.objects.get")
    @patch("products.conversations.backend.tasks._upload_image_to_slack_thread")
    @patch("products.conversations.backend.tasks._read_image_bytes_for_slack_upload")
    @patch("products.conversations.backend.slack.get_slack_client")
    def test_post_reply_to_slack_continues_when_image_upload_fails(
        self,
        mock_get_client: MagicMock,
        mock_read_bytes: MagicMock,
        mock_upload_image: MagicMock,
        mock_team_get: MagicMock,
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
