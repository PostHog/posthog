import uuid
import asyncio
import threading

from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase

import grpc.aio
import requests
import dns.resolver
from parameterized import parameterized

from posthog.temporal.proxy_service.cloudflare import CLOUDFLARE_API_TIMEOUT_S
from posthog.temporal.proxy_service.monitor import (
    CHECK_START_TO_CLOSE,
    CLOUDFLARE_IPS_TIMEOUT_S,
    DNS_LOOKUP_LIFETIME_S,
    PROXY_LIVE_CHECK_TIMEOUT_S,
    CheckActivityInput,
    check_certificate_status,
    check_dns,
    check_proxy_is_live,
)

RECORD_ID = uuid.UUID("019d1de4-5a20-0000-9d77-91f1a96a9df0")

DNS_FAILURES = [
    ("no_answer", dns.resolver.NoAnswer()),
    ("nxdomain", dns.resolver.NXDOMAIN()),
    ("no_nameservers", dns.resolver.NoNameservers()),
    ("timeout", dns.resolver.Timeout()),
]


def _record(target_cname="x.cf-prod-us-proxy.proxyhog.com."):
    r = MagicMock()
    r.domain = "p.example.com"
    r.target_cname = target_cname
    r.organization_id = "org"
    r.id = RECORD_ID
    return r


# Only reached when the loop is blocked, so it bounds a deadlock instead of timing the loop.
BLOCKED_LOOP_TIMEOUT_S = 5.0


class _BlockingCall:
    """A blocking stub that reports whether the event loop ran while the stub held its thread."""

    def __init__(self, exception: Exception):
        self._exception = exception
        self._entered = threading.Event()
        self._released = threading.Event()
        self.loop_ran_while_blocked = False

    def __call__(self, *args, **kwargs):
        self._entered.set()
        self.loop_ran_while_blocked = self._released.wait(BLOCKED_LOOP_TIMEOUT_S)
        raise self._exception

    async def release_when_entered(self) -> None:
        await asyncio.to_thread(self._entered.wait, BLOCKED_LOOP_TIMEOUT_S)
        self._released.set()


class TestProxyChecksDoNotFailOnHandledConditions(SimpleTestCase):
    @parameterized.expand(DNS_FAILURES)
    @patch("posthog.temporal.proxy_service.monitor.get_record")
    async def test_a_lookup_failure_is_reported_not_raised(self, _name, exc, mock_get_record):
        mock_get_record.return_value = _record()

        def resolve(domain, rdtype, **kwargs):
            if rdtype == "CNAME":
                raise dns.resolver.NoAnswer()
            raise exc

        with patch("posthog.temporal.proxy_service.monitor.dnssec_resolver") as resolver:
            resolver.return_value.resolve.side_effect = resolve
            out = await check_dns(CheckActivityInput(proxy_record_id=RECORD_ID))

        assert out.errors == ["No CNAME or A record DNS records found"]

    @parameterized.expand(DNS_FAILURES[1:])
    @patch("posthog.temporal.proxy_service.monitor.get_record")
    async def test_a_cname_failure_is_reported_not_raised(self, _name, exc, mock_get_record):
        mock_get_record.return_value = _record()

        with patch("posthog.temporal.proxy_service.monitor.dnssec_resolver") as resolver:
            resolver.return_value.resolve.side_effect = exc
            out = await check_dns(CheckActivityInput(proxy_record_id=RECORD_ID))

        assert out.errors == ["Domain name not found"]

    @patch("posthog.temporal.proxy_service.monitor.get_record")
    async def test_a_failed_cloudflare_ip_fetch_does_not_fail_the_check(self, mock_get_record):
        mock_get_record.return_value = _record()
        a_rec = MagicMock()
        a_rec.to_text.return_value = "1.2.3.4"

        def resolve(domain, rdtype, **kwargs):
            if rdtype == "CNAME":
                raise dns.resolver.NoAnswer()
            return [a_rec]

        with patch("posthog.temporal.proxy_service.monitor.dnssec_resolver") as resolver:
            resolver.return_value.resolve.side_effect = resolve
            with patch(
                "posthog.temporal.proxy_service.monitor.requests.get",
                side_effect=requests.exceptions.Timeout(),
            ):
                out = await check_dns(CheckActivityInput(proxy_record_id=RECORD_ID))

        assert out.errors == ["DNS records not found"]


class TestProxyChecksKeepTheEventLoopFree(SimpleTestCase):
    @patch("posthog.temporal.proxy_service.monitor.get_record")
    async def test_check_dns_does_not_block(self, mock_get_record):
        mock_get_record.return_value = _record()
        lookup = _BlockingCall(dns.resolver.NXDOMAIN())

        with patch("posthog.temporal.proxy_service.monitor.dnssec_resolver") as resolver:
            resolver.return_value.resolve.side_effect = lookup
            check = asyncio.create_task(check_dns(CheckActivityInput(proxy_record_id=RECORD_ID)))
            await lookup.release_when_entered()
            await check

        assert lookup.loop_ran_while_blocked, "loop blocked: no coroutine ran while the DNS lookup blocked"

    @patch("posthog.temporal.proxy_service.monitor.get_record")
    async def test_check_proxy_is_live_does_not_block(self, mock_get_record):
        mock_get_record.return_value = _record()
        probe = _BlockingCall(requests.exceptions.Timeout())

        with patch("posthog.temporal.proxy_service.monitor.requests.post", side_effect=probe):
            check = asyncio.create_task(check_proxy_is_live(CheckActivityInput(proxy_record_id=RECORD_ID)))
            await probe.release_when_entered()
            await check

        assert probe.loop_ran_while_blocked, "loop blocked: no coroutine ran while the proxy probe blocked"


class TestLegacyCertificateStatus(SimpleTestCase):
    @patch("posthog.temporal.proxy_service.monitor.get_grpc_client")
    @patch("posthog.temporal.proxy_service.monitor.get_record")
    async def test_a_missing_certificate_is_reported_not_raised(self, mock_get_record, mock_get_client):
        mock_get_record.return_value = _record(target_cname="proxy.example.com.")

        client = MagicMock()
        client.Status = AsyncMock(
            side_effect=grpc.aio.AioRpcError(
                code=grpc.StatusCode.NOT_FOUND,
                initial_metadata=grpc.aio.Metadata(),
                trailing_metadata=grpc.aio.Metadata(),
                details="certificate not found",
            )
        )
        mock_get_client.return_value = client

        out = await check_certificate_status(CheckActivityInput(proxy_record_id=RECORD_ID))

        assert out.errors == ["No TLS certificate found for this domain"]


class TestActivityBudgetsCoverTheirNetworkCalls(SimpleTestCase):
    @parameterized.expand(
        [
            ("check_dns", 2 * DNS_LOOKUP_LIFETIME_S + CLOUDFLARE_IPS_TIMEOUT_S),
            ("check_proxy_is_live", 2 * PROXY_LIVE_CHECK_TIMEOUT_S),
            ("check_certificate_status", CLOUDFLARE_API_TIMEOUT_S),
        ]
    )
    def test_the_worst_case_fits_inside_the_budget(self, _name, worst_case_seconds):
        assert worst_case_seconds < CHECK_START_TO_CLOSE.total_seconds()
