import socket

import pytest
from unittest.mock import patch

import psycopg
from parameterized import parameterized

from posthog.psycopg_helpers import prefer_routable_addresses, resolve_psycopg_hostaddr_with_timeout

_V6 = ["2600:1f16:1c4:661c:d148:b481:5246:e29d", "2600:1f16:1c4:6621:c8f:607d:ea25:4345"]
_V4 = ["13.58.18.166", "16.59.10.57"]
_HELPERS = "posthog.psycopg_helpers"


class TestPreferRoutableAddresses:
    @parameterized.expand(
        [
            ("v6_first", [*_V6, *_V4]),
            ("interleaved", [_V6[0], _V4[0], _V6[1], _V4[1]]),
            ("v6_last", [*_V4, *_V6]),
        ]
    )
    def test_unroutable_addresses_are_dropped_when_ipv6_has_no_route(self, _name, addresses):
        # An unroutable address left at the end of the list is not just wasted latency: psycopg
        # reports only the last attempt's error, so it overwrites the real one from an address
        # that reached the server.
        with patch(f"{_HELPERS}.has_ipv6_route", return_value=False):
            assert prefer_routable_addresses(addresses) == _V4

    def test_every_address_stands_when_ipv6_routes(self):
        with patch(f"{_HELPERS}.has_ipv6_route", return_value=True):
            assert prefer_routable_addresses([*_V6, *_V4]) == [*_V6, *_V4]

    def test_a_v6_only_host_keeps_its_addresses(self):
        # Unroutable beats nothing to connect to — and the route probe can be wrong.
        with patch(f"{_HELPERS}.has_ipv6_route", return_value=False):
            assert prefer_routable_addresses(_V6) == _V6

    def test_anything_that_is_not_an_ipv6_address_survives(self):
        with patch(f"{_HELPERS}.has_ipv6_route", return_value=False):
            assert prefer_routable_addresses(["db.example.com", _V6[0]]) == ["db.example.com"]


class TestResolveTemporaryFailure:
    @parameterized.expand(
        [
            ("try_again", socket.EAI_AGAIN, "Temporary failure in name resolution"),
            ("system_error", socket.EAI_SYSTEM, "System error"),
            ("out_of_memory", socket.EAI_MEMORY, "Memory allocation failure"),
        ]
    )
    def test_a_resolver_failure_raises_a_retryable_error_when_asked(self, _name, errno, message) -> None:
        with patch(f"{_HELPERS}.socket.getaddrinfo", side_effect=socket.gaierror(errno, message)):
            with pytest.raises(psycopg.OperationalError, match="Temporary failure"):
                resolve_psycopg_hostaddr_with_timeout("db.example.com", 5432, 5, raise_on_temporary_failure=True)

    def test_a_name_that_does_not_exist_stays_a_refusal(self) -> None:
        missing = socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        with patch(f"{_HELPERS}.socket.getaddrinfo", side_effect=missing):
            assert (
                resolve_psycopg_hostaddr_with_timeout("db.example.com", 5432, 5, raise_on_temporary_failure=True)
                is None
            )

    def test_a_try_again_answer_is_none_by_default(self) -> None:
        blip = socket.gaierror(socket.EAI_AGAIN, "Temporary failure in name resolution")
        with patch(f"{_HELPERS}.socket.getaddrinfo", side_effect=blip):
            assert resolve_psycopg_hostaddr_with_timeout("db.example.com", 5432, 5) is None
