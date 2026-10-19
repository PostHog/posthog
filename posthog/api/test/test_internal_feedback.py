from pathlib import Path

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

FIXTURE_IMAGE = Path(__file__).parent / "fixtures" / "a-small-but-valid.gif"


@override_settings(INTERNAL_FEEDBACK_SLACK_BOT_TOKEN="xoxb-test", INTERNAL_FEEDBACK_SLACK_CHANNEL="C123")
class TestInternalFeedbackAPI(APIBaseTest):
    def _post(self, **extra: object):
        return self.client.post(
            "/api/internal_feedback/",
            {
                "comment": "Button overlaps <!channel>",
                "page_url": "https://us.posthog.com/project/1/insights",
                "element_identifier": '[data-attr="save-insight"]',
                **extra,
            },
            format="multipart",
        )

    @parameterized.expand(
        [
            ("outside_email", "someone@example.com", True),
            ("unverified_posthog_email", "someone@posthog.com", False),
            ("unknown_verification_posthog_email", "someone@posthog.com", None),
        ]
    )
    @patch("posthog.api.internal_feedback.SlackWebClient")
    def test_rejects_non_staff(self, _name: str, email: str, verified: bool | None, mock_client: MagicMock) -> None:
        self.user.email = email
        self.user.is_email_verified = verified
        self.user.save()

        response = self._post()

        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_client.assert_not_called()

    @parameterized.expand(
        [
            ("element", {}, '*Element:* `[data-attr="save-insight"]`'),
            ("whole_page", {"element_identifier": ""}, "*Element:* whole page"),
        ]
    )
    @patch("posthog.api.internal_feedback.SlackWebClient")
    def test_uploads_screenshot_with_escaped_message(
        self, _name: str, extra: dict[str, str], element_line: str, mock_client: MagicMock
    ) -> None:
        self.user.is_email_verified = True
        self.user.save()

        with FIXTURE_IMAGE.open("rb") as image:
            response = self._post(screenshot=image, **extra)

        assert response.status_code == status.HTTP_200_OK, response.json()
        kwargs = mock_client.return_value.files_upload_v2.call_args.kwargs
        assert kwargs["channel"] == "C123"
        assert kwargs["content"] == FIXTURE_IMAGE.read_bytes()
        message = kwargs["initial_comment"]
        assert self.user.email in message
        assert "https://us.posthog.com/project/1/insights" in message
        assert "&lt;!channel&gt;" in message
        assert "<!channel>" not in message
        assert element_line in message
