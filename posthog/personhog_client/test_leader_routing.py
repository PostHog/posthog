from unittest.mock import MagicMock

from django.test import SimpleTestCase

from posthog.personhog_client.client import PersonHogClient
from posthog.personhog_client.proto import RaisePersonVersionRequest


class TestLeaderRouting(SimpleTestCase):
    def test_raise_person_version_carries_the_leader_routing_key(self) -> None:
        client = PersonHogClient("localhost:1")
        self.addCleanup(client.close)
        stub = MagicMock()
        client._stub = stub

        client.raise_person_version(RaisePersonVersionRequest(team_id=7, person_id=42, min_version=5))

        assert stub.RaisePersonVersion.call_args.kwargs["metadata"] == [("x-team-id", "7"), ("x-person-id", "42")]
