from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team
from posthog.redis import get_client

OFFER = {"type": "offer", "sdp": "v=0 offer"}
ANSWER = {"type": "answer", "sdp": "v=0 answer"}


class TestTerminalNetplay(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        get_client().flushdb()
        self.enabled = self.enterContext(
            patch("posthog.api.terminal_netplay.feature_enabled_or_false", return_value=True)
        )
        self.url = f"/api/projects/{self.team.id}/terminal_netplay"

    def _signal(self, room: str, sender: str, recipient: str, description: dict, url: str | None = None):
        return self.client.post(
            f"{url or self.url}/signal/",
            {"room": room, "sender": sender, "recipient": recipient, "description": description},
            format="json",
        )

    def _mailbox(self, room: str, peer: str, url: str | None = None):
        return self.client.get(f"{url or self.url}/mailbox/", {"room": room, "peer": peer})

    def test_host_and_client_exchange_descriptions(self) -> None:
        self.assertEqual(self._mailbox("ROOM42", "host").json(), {"signals": []})

        self.assertEqual(self._signal("ROOM42", "abc", "host", OFFER).status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self._mailbox("ROOM42", "host").json(), {"signals": [{"sender": "abc", "description": OFFER}]})
        self.assertEqual(self._mailbox("ROOM42", "host").json(), {"signals": []})

        self.assertEqual(self._signal("ROOM42", "host", "abc", ANSWER).status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(
            self._mailbox("ROOM42", "abc").json(), {"signals": [{"sender": "host", "description": ANSWER}]}
        )

    def test_joining_a_closed_room_returns_not_found(self) -> None:
        response = self._signal("NOROOM", "abc", "host", OFFER)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json()["detail"], "No deathmatch room has this code. Check the code and try again.")

    def test_rooms_are_scoped_to_the_project(self) -> None:
        self._mailbox("ROOM42", "host")
        other = Team.objects.create(organization=self.organization, name="Other project")
        other_url = f"/api/projects/{other.id}/terminal_netplay"

        self.assertEqual(self._signal("ROOM42", "abc", "host", OFFER, other_url).status_code, 404)

    def test_other_organizations_cannot_use_the_room(self) -> None:
        self._mailbox("ROOM42", "host")
        other = Team.objects.create(organization=Organization.objects.create(name="Other"), name="Other")

        response = self._signal("ROOM42", "abc", "host", OFFER, f"/api/projects/{other.id}/terminal_netplay")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_mailbox_keeps_only_recent_descriptions(self) -> None:
        self._mailbox("ROOM42", "host")
        for index in range(20):
            self._signal("ROOM42", f"p{index}", "host", OFFER)

        senders = [signal["sender"] for signal in self._mailbox("ROOM42", "host").json()["signals"]]

        self.assertEqual(senders, [f"p{index}" for index in range(4, 20)])

    @parameterized.expand(
        [
            ("lowercase_room", {"room": "room42"}),
            ("short_room", {"room": "AB"}),
            ("uppercase_peer", {"sender": "ABC"}),
            ("unknown_type", {"description": {"type": "candidate", "sdp": "x"}}),
            ("large_description", {"description": {"type": "offer", "sdp": "x" * 16385}}),
        ]
    )
    def test_rejects_invalid_signals(self, _name: str, override: dict) -> None:
        self._mailbox("ROOM42", "host")
        body = {"room": "ROOM42", "sender": "abc", "recipient": "host", "description": OFFER, **override}

        response = self.client.post(f"{self.url}/signal/", body, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_requires_the_terminal_flag(self) -> None:
        self.enabled.return_value = False

        self.assertEqual(self._mailbox("ROOM42", "host").status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self._signal("ROOM42", "abc", "host", OFFER).status_code, status.HTTP_403_FORBIDDEN)

    def test_requires_a_session(self) -> None:
        self.client.logout()

        self.assertEqual(self._mailbox("ROOM42", "host").status_code, status.HTTP_401_UNAUTHORIZED)
