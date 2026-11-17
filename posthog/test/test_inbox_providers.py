import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

import dns.rdata
import dns.resolver
import dns.exception
from parameterized import parameterized

from posthog.inbox_providers import InboxProvider, InboxProviderLookup, detect_inbox_provider


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

    @parameterized.expand(
        [
            (
                "primary_mx",
                _answers("20 aspmx.l.google.com.", "1 acme.mail.protection.outlook.com."),
                InboxProvider.MICROSOFT_365,
            ),
            ("failed_lookup", dns.resolver.NoNameservers(), None),
        ]
    )
    def test_company_domain_reads_primary_mx(
        self, _name: str, side_effect: object, expected: InboxProvider | None
    ) -> None:
        with _resolver(side_effect):
            assert InboxProviderLookup.start("someone@acme.example").result() == expected

    def test_slow_lookup_reads_as_unknown_within_budget(self) -> None:
        release = threading.Event()

        def slow_resolve(*_args: object, **_kwargs: object) -> list[dns.rdata.Rdata]:
            release.wait(timeout=5)
            return _mx_answer("1 aspmx.l.google.com.")

        try:
            with _resolver(slow_resolve), patch("posthog.inbox_providers.LOOKUP_TIMEOUT_SECONDS", 0.01):
                assert InboxProviderLookup.start("someone@slow-dns.example").result() is None
        finally:
            release.set()

    def test_busy_workers_skip_the_lookup(self) -> None:
        with (
            _resolver(_answers("1 aspmx.l.google.com.")) as resolve,
            patch("posthog.inbox_providers._lookup_slots", threading.BoundedSemaphore(1)) as slots,
        ):
            slots.acquire()
            assert InboxProviderLookup.start("someone@busy.example").result() is None

        resolve.assert_not_called()
