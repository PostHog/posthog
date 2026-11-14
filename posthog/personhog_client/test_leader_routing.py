from typing import Any

from unittest.mock import MagicMock

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.personhog_client.client import PersonHogClient
from posthog.personhog_client.proto import RaisePersonVersionRequest, UpdatePersonPropertiesRequest


class TestLeaderRouting(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "raise_person_version",
                "RaisePersonVersion",
                RaisePersonVersionRequest(team_id=7, person_id=42, min_version=5),
            ),
            (
                "update_person_properties",
                "UpdatePersonProperties",
                UpdatePersonPropertiesRequest(team_id=7, person_id=42, event_name="$set"),
            ),
        ]
    )
    def test_leader_calls_go_to_the_leader_router_with_their_routing_key(
        self, method: str, rpc: str, request: Any
    ) -> None:
        client = PersonHogClient("localhost:1", lifecycle_addr="localhost:2")
        self.addCleanup(client.close)
        stub = MagicMock()
        client._leader_stub = stub

        getattr(client, method)(request)

        assert getattr(stub, rpc).call_args.kwargs["metadata"] == [("x-team-id", "7"), ("x-person-id", "42")]
