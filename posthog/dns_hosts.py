import logging

from django.core.cache import cache

import dns.resolver
import dns.exception
from dns.rdtypes.ANY.NS import NS

from posthog.dataclasses import frozen

logger = logging.getLogger(__name__)

LOOKUP_TIMEOUT_SECONDS = 3
CACHE_SECONDS = 60 * 60


@frozen
class DnsHost:
    name: str
    dns_settings_url: str


ROUTE_53 = DnsHost(name="Route 53", dns_settings_url="https://console.aws.amazon.com/route53/v2/hostedzones")
GODADDY = DnsHost(name="GoDaddy", dns_settings_url="https://dcc.godaddy.com/control/portfolio")
NAMECHEAP = DnsHost(name="Namecheap", dns_settings_url="https://ap.www.namecheap.com/domains/list/")
SQUARESPACE = DnsHost(name="Squarespace", dns_settings_url="https://account.squarespace.com/domains")
HOSTINGER = DnsHost(name="Hostinger", dns_settings_url="https://hpanel.hostinger.com/domains")
IONOS = DnsHost(name="IONOS", dns_settings_url="https://my.ionos.com/domains")
DIGITALOCEAN = DnsHost(name="DigitalOcean", dns_settings_url="https://cloud.digitalocean.com/networking/domains")
CLOUDFLARE = DnsHost(name="Cloudflare", dns_settings_url="https://dash.cloudflare.com/?to=/:account/:zone/dns/records")
VERCEL = DnsHost(name="Vercel", dns_settings_url="https://vercel.com/dashboard/domains")

# Each marker is matched against "." + the nameserver hostname, so a leading dot anchors it to a
# label boundary. Route 53 nameservers look like ns-1234.awsdns-56.org, so its marker has no dot.
_DNS_HOSTS_BY_NAMESERVER_MARKER: tuple[tuple[str, DnsHost], ...] = (
    (".awsdns-", ROUTE_53),
    (".domaincontrol.com", GODADDY),
    (".registrar-servers.com", NAMECHEAP),
    (".squarespacedns.com", SQUARESPACE),
    (".dns-parking.com", HOSTINGER),
    (".hostinger.", HOSTINGER),
    (".ui-dns.", IONOS),
    (".digitalocean.com", DIGITALOCEAN),
    (".ns.cloudflare.com", CLOUDFLARE),
    (".vercel-dns.com", VERCEL),
)


def detect_dns_host(nameservers: list[str]) -> DnsHost | None:
    for nameserver in nameservers:
        anchored = "." + nameserver.lower().rstrip(".")
        for marker, host in _DNS_HOSTS_BY_NAMESERVER_MARKER:
            if marker in anchored:
                return host
    return None


def lookup_dns_host(root_domain: str) -> DnsHost | None:
    cache_key = f"dns_host:{root_domain}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached or None

    nameservers = _nameservers(root_domain)
    if nameservers is None:
        return None
    host = detect_dns_host(nameservers)
    cache.set(cache_key, host or False, CACHE_SECONDS)
    return host


def _nameservers(root_domain: str) -> list[str] | None:
    resolver = dns.resolver.Resolver()
    resolver.lifetime = LOOKUP_TIMEOUT_SECONDS
    try:
        answers = resolver.resolve(root_domain, "NS")
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return []
    except dns.exception.DNSException:
        logger.info("Could not resolve nameservers for %s", root_domain, exc_info=True)
        return None
    return [rdata.target.to_text() for rdata in answers if isinstance(rdata, NS)]
