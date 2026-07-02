from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from products.conversations.backend.teams_attachments import (
    _download_image,
    extract_teams_bot_attachments,
    extract_teams_graph_images,
)

VALID_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)


class TestTeamsImageIngest(SimpleTestCase):
    @patch("products.conversations.backend.teams_attachments.save_file_to_uploaded_media")
    @patch("products.conversations.backend.teams_attachments._download_image")
    def test_extract_bot_attachments_copies_to_uploaded_media(
        self, mock_download: MagicMock, mock_save: MagicMock
    ) -> None:
        mock_download.return_value = VALID_PNG_BYTES
        mock_save.return_value = "https://app.posthog.com/uploaded_media/abc"

        fake_team = MagicMock()
        fake_team.id = 1

        attachments = [
            {
                "contentType": "image/png",
                "contentUrl": "https://smba.trafficmanager.net/images/abc",
                "name": "screenshot.png",
            }
        ]
        images = extract_teams_bot_attachments(attachments, fake_team, "bot-token")

        assert len(images) == 1
        assert images[0]["url"] == "https://app.posthog.com/uploaded_media/abc"
        assert images[0]["name"] == "screenshot.png"
        mock_download.assert_called_once_with("https://smba.trafficmanager.net/images/abc", "bot-token")
        mock_save.assert_called_once()

    @patch("products.conversations.backend.teams_attachments._download_image")
    def test_extract_bot_attachments_skips_non_image(self, mock_download: MagicMock) -> None:
        fake_team = MagicMock()
        fake_team.id = 1

        attachments = [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {"type": "AdaptiveCard"},
            }
        ]
        images = extract_teams_bot_attachments(attachments, fake_team, "bot-token")

        assert images == []
        mock_download.assert_not_called()

    @patch("products.conversations.backend.teams_attachments.save_file_to_uploaded_media")
    @patch("products.conversations.backend.teams_attachments._download_image")
    def test_extract_bot_attachments_skips_invalid_image(self, mock_download: MagicMock, mock_save: MagicMock) -> None:
        mock_download.return_value = b"not-an-image"

        fake_team = MagicMock()
        fake_team.id = 1

        attachments = [
            {
                "contentType": "image/png",
                "contentUrl": "https://smba.trafficmanager.net/images/abc",
                "name": "bad.png",
            }
        ]
        images = extract_teams_bot_attachments(attachments, fake_team, "bot-token")

        assert images == []
        mock_save.assert_not_called()

    @patch("products.conversations.backend.teams_attachments._download_image")
    def test_extract_bot_attachments_skips_failed_download(self, mock_download: MagicMock) -> None:
        mock_download.return_value = None

        fake_team = MagicMock()
        fake_team.id = 1

        attachments = [
            {
                "contentType": "image/jpeg",
                "contentUrl": "https://smba.trafficmanager.net/images/abc",
                "name": "test.jpg",
            }
        ]
        images = extract_teams_bot_attachments(attachments, fake_team, "bot-token")

        assert images == []

    @patch("products.conversations.backend.teams_attachments.save_file_to_uploaded_media")
    @patch("products.conversations.backend.teams_attachments._download_image")
    def test_extract_graph_images_from_hosted_contents(self, mock_download: MagicMock, mock_save: MagicMock) -> None:
        mock_download.return_value = VALID_PNG_BYTES
        mock_save.return_value = "https://app.posthog.com/uploaded_media/xyz"

        fake_team = MagicMock()
        fake_team.id = 1

        hosted_url = "https://graph.microsoft.com/v1.0/teams/t1/channels/c1/messages/m1/hostedContents/hc1/$value"
        msg = {
            "id": "m1",
            "body": {
                "contentType": "html",
                "content": f'<p>Check this</p><img src="{hosted_url}" />',
            },
            "hostedContents": [
                {"id": "hc1", "contentType": "image/png"},
            ],
        }
        images = extract_teams_graph_images(msg, fake_team, "t1", "c1", "graph-token")

        assert len(images) == 1
        assert images[0]["url"] == "https://app.posthog.com/uploaded_media/xyz"
        mock_download.assert_called_once_with(hosted_url, "graph-token")

    @patch("products.conversations.backend.teams_attachments._download_image")
    def test_extract_graph_images_no_img_tags(self, mock_download: MagicMock) -> None:
        fake_team = MagicMock()
        fake_team.id = 1

        msg = {
            "id": "m1",
            "body": {"contentType": "html", "content": "<p>Just text</p>"},
        }
        images = extract_teams_graph_images(msg, fake_team, "t1", "c1", "graph-token")

        assert images == []
        mock_download.assert_not_called()

    def test_extract_bot_attachments_empty_list(self) -> None:
        fake_team = MagicMock()
        fake_team.id = 1
        assert extract_teams_bot_attachments([], fake_team, "bot-token") == []
        assert extract_teams_bot_attachments(None, fake_team, "bot-token") == []

    @patch("products.conversations.backend.teams_attachments._download_image")
    def test_extract_bot_attachments_rejects_untrusted_host(self, mock_download: MagicMock) -> None:
        fake_team = MagicMock()
        fake_team.id = 1

        attachments = [
            {
                "contentType": "image/png",
                "contentUrl": "https://evil.example.com/steal",
                "name": "x.png",
            }
        ]
        assert extract_teams_bot_attachments(attachments, fake_team, "bot-token") == []
        mock_download.assert_not_called()

    @patch("products.conversations.backend.teams_attachments._download_image")
    def test_extract_graph_images_rejects_wrong_team_channel(self, mock_download: MagicMock) -> None:
        fake_team = MagicMock()
        fake_team.id = 1

        # URL points to a different team/channel than the one we're processing
        evil_url = (
            "https://graph.microsoft.com/v1.0/teams/OTHER_TEAM/channels/OTHER_CH/messages/m1/hostedContents/hc1/$value"
        )
        msg = {
            "id": "m1",
            "body": {
                "contentType": "html",
                "content": f'<img src="{evil_url}" />',
            },
        }
        images = extract_teams_graph_images(msg, fake_team, "t1", "c1", "graph-token")

        assert images == []
        mock_download.assert_not_called()

    @patch("products.conversations.backend.teams_attachments._download_image")
    def test_extract_graph_images_rejects_wrong_message_id(self, mock_download: MagicMock) -> None:
        fake_team = MagicMock()
        fake_team.id = 1

        # URL references a different message than the one we're processing
        evil_url = "https://graph.microsoft.com/v1.0/teams/t1/channels/c1/messages/OTHER_MSG/hostedContents/hc1/$value"
        msg = {
            "id": "m1",
            "body": {
                "contentType": "html",
                "content": f'<img src="{evil_url}" />',
            },
        }
        images = extract_teams_graph_images(msg, fake_team, "t1", "c1", "graph-token")

        assert images == []
        mock_download.assert_not_called()

    @patch("products.conversations.backend.teams_attachments.save_file_to_uploaded_media")
    @patch("products.conversations.backend.teams_attachments._download_image")
    def test_extract_graph_images_accepts_reply_path(self, mock_download: MagicMock, mock_save: MagicMock) -> None:
        mock_download.return_value = VALID_PNG_BYTES
        mock_save.return_value = "https://app.posthog.com/uploaded_media/reply"

        fake_team = MagicMock()
        fake_team.id = 1

        reply_url = "https://graph.microsoft.com/v1.0/teams/t1/channels/c1/messages/root123/replies/r1/hostedContents/hc1/$value"
        msg = {
            "id": "r1",
            "body": {
                "contentType": "html",
                "content": f'<img src="{reply_url}" />',
            },
            "hostedContents": [{"id": "hc1", "contentType": "image/jpeg"}],
        }
        images = extract_teams_graph_images(msg, fake_team, "t1", "c1", "graph-token")

        assert len(images) == 1
        mock_download.assert_called_once_with(reply_url, "graph-token")

    @patch("products.conversations.backend.teams_attachments.requests.get")
    def test_download_image_blocks_redirects(self, mock_get: MagicMock) -> None:
        resp = MagicMock()
        resp.is_redirect = True
        resp.is_permanent_redirect = False
        resp.status_code = 302
        mock_get.return_value = resp

        assert _download_image("https://graph.microsoft.com/v1.0/x/$value", "graph-token") is None
        mock_get.assert_called_once()
        # token must not leak across the redirect hop
        assert mock_get.call_args.kwargs["allow_redirects"] is False
