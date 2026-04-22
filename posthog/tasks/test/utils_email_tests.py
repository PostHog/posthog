import os
import re
from typing import Any

from unittest.mock import MagicMock

from posthog.email import EmailMessage
from posthog.utils import get_absolute_path


def _current_test_name() -> str | None:
    # Pytest sets PYTEST_CURRENT_TEST to "path::Class::method (phase)".
    raw = os.environ.get("PYTEST_CURRENT_TEST")
    if not raw:
        return None
    method = raw.split("::")[-1].split(" ", 1)[0]
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", method) or None


def mock_email_messages(MockEmailMessage: MagicMock, path: str = "tasks/test/__emails__/") -> list[Any]:
    """
    Mock EmailMessage so .send() writes the rendered HTML to tasks/test/__emails__/<template>/,
    and returns a list that captures every EmailMessage created during the test.

    Filenames are deterministic across runs: `<test_name>.html` (or `<test_name>__n1.html`
    for the second/third/... email of a single test). Snapshots overwrite themselves instead
    of piling up with different campaign_keys (e.g. team_id or day) on each pytest invocation.

    Usage:
    @patch("posthog.my_class.EmailMessage")
    def test_mocked_email(MockEmailMessage):
        mocked_email_messages = mock_email_messages(MockEmailMessage)

        send_emails()

        assert len(mocked_email_messsages) > 0
        assert mocked_email_messages[0].send.call_count == 1
        assert mocked_email_messages[0].campaign_key == "my_campaign_key"
    """

    mocked_email_messages: list[Any] = []
    test_name = _current_test_name()

    def _email_message_side_effect(**kwargs: Any) -> EmailMessage:
        email_message = EmailMessage(**kwargs)
        _original_send = email_message.send

        def _send_side_effect(send_async: bool = True) -> Any:
            # Already appended before send() runs, so subtract 1 to get this message's index.
            index_in_test = len(mocked_email_messages) - 1
            base = test_name or email_message.campaign_key
            filename = f"{base}__n{index_in_test}.html" if index_in_test > 0 else f"{base}.html"
            output_file = get_absolute_path(f"{path}{kwargs['template_name']}/{filename}")
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
