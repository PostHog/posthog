import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

import dns.rdata
import dns.resolver
import dns.exception
from parameterized import parameterized

from posthog.inbox_providers import InboxProvider, InboxProviderLookup, detect_inbox_provider
from posthog.test.waiting import wait_until


def _mx_answer(*records: str) -> list[dns.rdata.Rdata]:
    return [dns.rdata.from_text("IN", "MX", record) for record in records]


@contextmanager
def _resolver(side_effect: object, cloud: bool = True) -> Iterator[MagicMock]:
    with (
        patch("posthog.inbox_providers.is_cloud", return_value=cloud),
        patch("posthog.inbox_providers.dns.resolver.Resolver.resolve", side_effect=side_effect) as resolve,
    ):
        yield resolve


def _answers(*records: str) -> Callable[..., list[dns.rdata.Rdata]]:
    return lambda *_args, **_kwargs: _mx_answer(*records)


class TestDetectInboxProvider(SimpleTestCase):
    @parameterized.expand(
        [
            ("aspmx.l.google.com.", InboxProvider.GMAIL),
            ("SMTP.GOOGLE.COM", InboxProvider.GMAIL),
            ("acme-com.mail.protection.outlook.com.", InboxProvider.MICROSOFT_365),
            ("hotmail-com.olc.protection.outlook.com", InboxProvider.OUTLOOK),
            ("mta5.am0.yahoodns.net", InboxProvider.YAHOO),
            ("mx01.mail.icloud.com", InboxProvider.ICLOUD),
            ("mail.protonmail.ch", InboxProvider.PROTON),
            ("eu-smtp-inbound-1.mimecast.com", None),
            ("mx.notgoogle.com", None),
            ("aspmx.l.google.com.evil.example", None),
            (None, None),
        ]
    )
    def test_names_provider_from_mx_host(self, mx_host: str | None, expected: InboxProvider | None) -> None:
        assert detect_inbox_provider(mx_host) == expected


class TestInboxProviderLookup(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    @parameterized.expand(
        [
            ("consumer_domain_on_cloud", "Someone@GMail.com", True, InboxProvider.GMAIL),
            ("consumer_domain_self_hosted", "someone@hotmail.com", False, InboxProvider.OUTLOOK),
            ("company_domain_self_hosted", "someone@selfhosted-company.example", False, None),
            ("out_of_band_domain", "someone@lookup.oast.live", True, None),
        ]
    )
    def test_answers_without_dns(self, _name: str, email: str, cloud: bool, expected: InboxProvider | None) -> None:
        with _resolver(_answers("10 aspmx.l.google.com."), cloud=cloud) as resolve:
            provider = InboxProviderLookup.start(email).result()

        assert provider == expected
        resolve.assert_not_called()

    def test_company_domain_uses_primary_mx_and_caches_answer(self) -> None:
        with _resolver(_answers("20 aspmx.l.google.com.", "1 acme-example.mail.protection.outlook.com.")):
            assert InboxProviderLookup.start("someone@acme-cached.example").result() == InboxProvider.MICROSOFT_365

        with _resolver(dns.exception.Timeout()) as resolve:
            assert InboxProviderLookup.start("other@acme-cached.example").result() == InboxProvider.MICROSOFT_365
        resolve.assert_not_called()

    def test_failed_lookup_is_not_cached(self) -> None:
        with _resolver(dns.resolver.NoNameservers()):
            assert InboxProviderLookup.start("someone@flaky-dns.example").result() is None

        with _resolver(_answers("1 aspmx.l.google.com.")):
            assert InboxProviderLookup.start("someone@flaky-dns.example").result() == InboxProvider.GMAIL

    def test_slow_lookup_reads_as_unknown_and_caches_late_answer(self) -> None:
        release = threading.Event()

        def slow_resolve(*_args: object, **_kwargs: object) -> list[dns.rdata.Rdata]:
            release.wait(timeout=5)
            return _mx_answer("1 aspmx.l.google.com.")

        try:
            with _resolver(slow_resolve), patch("posthog.inbox_providers.LOOKUP_TIMEOUT_SECONDS", 0.01):
                assert InboxProviderLookup.start("someone@slow-dns.example").result() is None
        finally:
            release.set()

        with _resolver(dns.exception.Timeout()):
            wait_until(
                lambda: InboxProviderLookup.start("other@slow-dns.example").result() == InboxProvider.GMAIL,
                message="the late answer was never cached",
            )
