import dns.flags
import dns.resolver
import dns.asyncresolver

DNSSEC_VALIDATING_NAMESERVERS = ("1.1.1.1", "1.0.0.1")


def dnssec_resolver() -> dns.resolver.Resolver:
    resolver = dns.resolver.Resolver(configure=False)
    resolver.nameservers = list(DNSSEC_VALIDATING_NAMESERVERS)
    resolver.use_edns(edns=0, ednsflags=dns.flags.DO)
    return resolver


def async_dnssec_resolver() -> dns.asyncresolver.Resolver:
    resolver = dns.asyncresolver.Resolver(configure=False)
    resolver.nameservers = list(DNSSEC_VALIDATING_NAMESERVERS)
    resolver.use_edns(edns=0, ednsflags=dns.flags.DO)
    return resolver
