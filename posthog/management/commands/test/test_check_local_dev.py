import json

from unittest.mock import patch

from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized

from posthog.management.commands.check_local_dev import LocalDevCheck


def conversation_line(role: str, text: str) -> str:
    return (
        json.dumps(
            {"notification": {"params": {"update": {"sessionUpdate": role, "content": {"type": "text", "text": text}}}}}
        )
        + "\n"
    )


@override_settings(SITE_URL="http://localhost:8010")
class TestLocalConversationCheck(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "complete",
                conversation_line("user_message", "What should I check?")
                + conversation_line("agent_message", "Check the signup flow."),
                False,
            ),
            ("missing_log", "", True),
            ("missing_assistant", conversation_line("user_message", "What should I check?"), True),
            (
                "blank_assistant",
                conversation_line("user_message", "What should I check?") + conversation_line("agent_message", " "),
                True,
            ),
        ]
    )
    def test_checks_saved_messages_through_the_http_boundary(self, _name: str, logs: str, should_fail: bool) -> None:
        def response(method: str, url: str, **kwargs: object) -> requests.Response:
            result = requests.Response()
            result.status_code = 200
            result._content = (logs if url.endswith("/logs/") else json.dumps({"status": "completed"})).encode()
            return result

        check = LocalDevCheck("posthog-dev://callback")
        try:
            with patch("requests.Session.request", side_effect=response):
                if should_fail:
                    with self.assertRaisesMessage(CommandError, "missing its user or assistant message"):
                        check.check_demo_chat(1, 2)
                else:
                    check.check_demo_chat(1, 2)
        finally:
            check.session.close()
