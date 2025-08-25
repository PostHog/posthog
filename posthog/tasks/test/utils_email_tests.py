import os
from typing import Any

from unittest.mock import MagicMock

from posthog.email import EmailMessage
from posthog.utils import get_absolute_path


def mock_email_messages(MockEmailMessage: MagicMock, path: str = "tasks/test/__emails__/") -> list[Any]:
    """
    Takes a mocked EmailMessage class and returns a list of all subsequently created EmailMessage instances
    The "send" method is spyed on to write the generated email to a file

    Usage:
    @patch("posthog.my_class.EmailMessage")
    def test_mocked_email(MockEmailMessage):
        mocked_email_messages = mock_email_messages(MockEmailMessage)

        send_emails()

        assert len(mocked_email_messsages) > 0
        assert mocked_email_messages[0].send.call_count == 1
        assert mocked_email_messages[0].campaign_key == "my_campaign_key"
    """

    mocked_email_messages = []

    def _email_message_side_effect(**kwargs: Any) -> EmailMessage:
        email_message = EmailMessage(**kwargs)
        _original_send = email_message.send

        def _send_side_effect(send_async: bool = True) -> Any:
            output_file = get_absolute_path(f"{path}{kwargs['template_name']}/{email_message.campaign_key}.html")
            os.makedirs(os.path.dirname(output_file), exist_ok=True)

            with open(output_file, "w", encoding="utf_8") as f:
                f.write(email_message.html_body)

            print(f"Email rendered to {output_file}")  # noqa: T201

            return _original_send()

        email_message.send = MagicMock()  # type: ignore
        email_message.send.side_effect = _send_side_effect
        mocked_email_messages.append(email_message)
        return email_message

    MockEmailMessage.side_effect = _email_message_side_effect

    return mocked_email_messages
