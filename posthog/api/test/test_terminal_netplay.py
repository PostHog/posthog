import hashlib
from typing import TYPE_CHECKING

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, PersonalAPIKey, Team, User
from posthog.models.personal_api_key import hash_key_value
from posthog.redis import get_client
from posthog.token_bucket import BucketUnavailable

if TYPE_CHECKING:
    from rest_framework.response import _MonkeyPatchedResponse

OFFER = {"type": "offer", "sdp": "v=0\r\ns=offer\r\n"}
ANSWER = {"type": "answer", "sdp": "v=0\r\ns=answer\r\n"}


class TestTerminalNetplay(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        get_client().flushdb()
        self.enabled = self.enterContext(
            patch("posthog.api.terminal_netplay.feature_enabled_or_false", return_value=True)
        )
        self.url = f"/api/projects/{self.team.id}/terminal_netplay"

    def _token(self, peer: str) -> str:
        return hashlib.sha256(peer.encode()).hexdigest()

    def _signal(
        self,
        room: str,
        sender: str,
        recipient: str,
        description: dict[str, str],
        url: str | None = None,
        token: str | None = None,
    ) -> _MonkeyPatchedResponse:
        return self.client.post(
            f"{url or self.url}/signal/",
            {"room": room, "sender": sender, "recipient": recipient, "description": description},
            format="json",
            HTTP_X_TERMINAL_NETPLAY_TOKEN=self._token(sender) if token is None else token,
        )

    def _mailbox(
        self, room: str, peer: str, url: str | None = None, token: str | None = None
    ) -> _MonkeyPatchedResponse:
        return self.client.get(
            f"{url or self.url}/mailbox/",
            {"room": room, "peer": peer},
            HTTP_X_TERMINAL_NETPLAY_TOKEN=self._token(peer) if token is None else token,
        )

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

    @parameterized.expand([("host",), ("abc",)])
    def test_only_the_owner_can_read_or_send_as_a_peer(self, peer: str) -> None:
        self._mailbox("ROOM42", "host")
        self._signal("ROOM42", "abc", "host", OFFER)
        self._signal("ROOM42", "host", "abc", ANSWER)
        recipient, description = ("abc", ANSWER) if peer == "host" else ("host", OFFER)

        self.assertEqual(self._mailbox("ROOM42", peer, token="f" * 64).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self._signal("ROOM42", peer, recipient, description, token="f" * 64).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        expected = OFFER if peer == "host" else ANSWER
        self.assertEqual(self._mailbox("ROOM42", peer).json()["signals"][0]["description"], expected)

    def test_tokens_are_bound_to_the_signed_in_user(self) -> None:
        self._mailbox("ROOM42", "host")
        teammate = User.objects.create_and_join(self.organization, "teammate@example.com", "password")
        self.client.force_login(teammate)

        self.assertEqual(self._mailbox("ROOM42", "host").status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self._signal("ROOM42", "host", "abc", ANSWER).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self._signal("ROOM42", "abc", "host", OFFER).status_code, status.HTTP_204_NO_CONTENT)

    @parameterized.expand([("",), ("invalid",), ("a" * 65,)])
    def test_requires_a_valid_game_token(self, token: str) -> None:
        self.assertEqual(self._mailbox("ROOM42", "host", token=token).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self._signal("ROOM42", "abc", "host", OFFER, token=token).status_code, status.HTTP_403_FORBIDDEN
        )

    @parameterized.expand(
        [("abc", "host", ANSWER), ("abc", "other", OFFER), ("host", "abc", OFFER), ("host", "host", ANSWER)]
    )
    def test_rejects_invalid_signal_routes(self, sender: str, recipient: str, description: dict[str, str]) -> None:
        self._mailbox("ROOM42", "host")
        self.assertEqual(
            self._signal("ROOM42", sender, recipient, description).status_code, status.HTTP_400_BAD_REQUEST
        )

    def test_expired_rooms_reject_signals_and_do_not_reuse_mailboxes(self) -> None:
        self._mailbox("ROOM42", "host")
        self._signal("ROOM42", "abc", "host", OFFER)
        self._signal("ROOM42", "host", "abc", ANSWER)
        get_client().delete(f"terminal_netplay:{self.team.id}:ROOM42")

        self.assertEqual(self._signal("ROOM42", "host", "abc", ANSWER).status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self._mailbox("ROOM42", "abc").status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self._mailbox("ROOM42", "host", token="f" * 64).json(), {"signals": []})
        self.assertEqual(self._mailbox("ROOM42", "abc").status_code, status.HTTP_403_FORBIDDEN)

    def test_host_cannot_answer_an_unregistered_player(self) -> None:
        self._mailbox("ROOM42", "host")
        self.assertEqual(self._signal("ROOM42", "host", "unknown", ANSWER).status_code, status.HTTP_404_NOT_FOUND)

    def test_answer_ownership_lasts_as_long_as_the_mailbox(self) -> None:
        with time_machine.travel(timezone.now(), tick=False) as clock:
            self._mailbox("ROOM42", "host")
            self._signal("ROOM42", "abc", "host", OFFER)
            clock.shift(25)
            self._mailbox("ROOM42", "host")
            self._signal("ROOM42", "host", "abc", ANSWER)
            clock.shift(25)
            self._mailbox("ROOM42", "host")
            clock.shift(11)

            self.assertEqual(
                self._signal("ROOM42", "abc", "host", OFFER, token="f" * 64).status_code,
                status.HTTP_403_FORBIDDEN,
            )
            self.assertEqual(self._mailbox("ROOM42", "abc").json()["signals"][0]["description"], ANSWER)

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

    def test_offer_limit_cannot_be_bypassed_with_new_peer_ids_or_tokens(self) -> None:
        with time_machine.travel(timezone.now(), tick=False) as clock:
            self._mailbox("ROOM42", "host")
            self._mailbox("OTHER42", "host")
            for index in range(4):
                self.assertEqual(self._signal("ROOM42", f"p{index}", "host", OFFER).status_code, 204)

            response = self._signal("ROOM42", "newpeer", "host", OFFER, token="f" * 64)
            self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
            self.assertEqual(response["Retry-After"], "30")
            self.assertEqual(self._signal("OTHER42", "abc", "host", OFFER).status_code, 204)
            self.assertEqual(self._signal("ROOM42", "host", "p0", ANSWER).status_code, 204)

            teammate = User.objects.create_and_join(self.organization, "teammate@example.com", "password")
            self.client.force_login(teammate)
            self.assertEqual(self._signal("ROOM42", "teammate", "host", OFFER).status_code, 204)
            self.client.force_login(self.user)
            clock.shift(25)
            self._mailbox("ROOM42", "host")
            clock.shift(5)
            self.assertEqual(self._signal("ROOM42", "retry", "host", OFFER).status_code, 204)

    @parameterized.expand([("room_rate", False), ("mailbox_capacity", True)])
    def test_flooding_cannot_evict_queued_offers(self, _name: str, allow_refill: bool) -> None:
        with time_machine.travel(timezone.now(), tick=False) as clock:
            self._mailbox("ROOM42", "host")
            for index in range(17):
                if index % 4 == 0:
                    teammate = User.objects.create_and_join(self.organization, f"player{index}@example.com", "password")
                    self.client.force_login(teammate)
                response = self._signal("ROOM42", f"p{index}", "host", OFFER)
                self.assertEqual(response.status_code, 204 if index < 16 else 429)
                if allow_refill:
                    clock.shift(1)

            self.client.force_login(self.user)
            signals = self._mailbox("ROOM42", "host").json()["signals"]
            self.assertEqual([signal["sender"] for signal in signals], [f"p{index}" for index in range(16)])
            self.client.force_login(teammate)
            self.assertEqual(self._signal("ROOM42", "retry", "host", OFFER).status_code, 204 if allow_refill else 429)

    def test_signaling_fails_closed_when_the_rate_limiter_is_unavailable(self) -> None:
        self._mailbox("ROOM42", "host")
        with patch("posthog.api.terminal_netplay.consume", return_value=BucketUnavailable(error="unavailable")):
            self.assertEqual(self._signal("ROOM42", "abc", "host", OFFER).status_code, 429)
        self.assertEqual(self._mailbox("ROOM42", "host").json(), {"signals": []})

    @parameterized.expand(
        [
            ("lowercase_room", {"room": "room42"}),
            ("short_room", {"room": "AB"}),
            ("uppercase_peer", {"sender": "ABC"}),
            ("unknown_type", {"description": {"type": "candidate", "sdp": "x"}}),
            ("large_description", {"description": {"type": "offer", "sdp": "x" * 16385}}),
        ]
    )
    def test_rejects_invalid_signals(self, _name: str, override: dict[str, object]) -> None:
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

    def test_personal_api_keys_cannot_use_signaling(self) -> None:
        token = "phx_test_terminal_netplay_key"
        PersonalAPIKey.objects.create(user=self.user, label="Test", secure_value=hash_key_value(token), scopes=["*"])
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        self.assertEqual(self._mailbox("ROOM42", "host").status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self._signal("ROOM42", "abc", "host", OFFER).status_code, status.HTTP_403_FORBIDDEN)
