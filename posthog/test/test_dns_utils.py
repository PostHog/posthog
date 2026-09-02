from django.test import SimpleTestCase

import dns.flags
import dns.nameserver

from posthog.dns_utils import DNSSEC_VALIDATING_NAMESERVERS, async_dnssec_resolver, dnssec_resolver


class TestDNSSECResolvers(SimpleTestCase):
    def test_resolvers_request_opportunistic_dnssec_validation(self) -> None:
        for resolver in (dnssec_resolver(), async_dnssec_resolver()):
            assert tuple(resolver.nameservers) == DNSSEC_VALIDATING_NAMESERVERS
            for nameserver in resolver.nameservers:
                assert isinstance(nameserver, dns.nameserver.DoHNameserver)
                assert nameserver.verify is True
            assert resolver.edns == 0
            assert resolver.ednsflags & dns.flags.DO
