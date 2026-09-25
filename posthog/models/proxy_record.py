import re
from uuid import UUID

from django.conf import settings
from django.db import models

from posthog.models import Organization
from posthog.models.utils import UUIDTModel

MAX_PROXY_DOMAIN_LENGTH = 253
MAX_PROXY_DOMAIN_LABEL_LENGTH = 63

_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
_PROXY_DOMAIN_RE = re.compile(rf"{_LABEL}(?:\.{_LABEL})*")

# Every apex domain PostHog itself registers or serves production traffic on: the
# Route53 zones in posthog-cloud-infra's terraform/environments/aws-accnt-root/route53-zones.tf,
# plus postwh.com, posthogusercontent.com, and the literal CLOUDFLARE_PROXY_BASE_CNAME /
# PROXY_BASE_CNAME targets from charts' shared/posthog-django/common.<env>.yaml (europehog.com,
# proxyhog.com, livehog.com are the Cloudflare/legacy CNAME targets that every other tenant's
# proxy domain already points to).
RESERVED_PROXY_DOMAINS = frozenset(
    {
        "posthog.com",
        "posthog.dev",
        "posthog.net",
        "posthog.io",
        "posthog.eu",
        "posthog.click",
        "posthog.lol",
        "posthog.biz",
        "posthog.cc",
        "hog.dev",
        "deskhog.com",
        "posthug.com",
        "productforengineers.com",
        "hedgehog.vc",
        "postvar.com",
        "productautonomy.com",
        "producthog.com",
        "phog.gg",
        "prehog.net",
        "ph-proxy.com",
        "livehog.com",
        "warmhog.com",
        "postwh.com",
        "posthogusercontent.com",
        "europehog.com",
        "proxyhog.com",
    }
)


def is_valid_proxy_domain(domain: str) -> bool:
    """Whether `domain` is a bare hostname that means the same thing to a DNS resolver
    and to a URL parser.

    `domain` reaches two grammars: dnspython parses it as a DNS query name, and
    `requests`/`urlparse` parse it as a URL authority. Those grammars disagree, and the
    disagreement is exploitable. dnspython's all-ASCII path copies every byte except `.`
    and `\\` into a label, so `169.254.169.254:80/pad.attacker.example` is a legal query
    name that a nameserver can answer however it likes, while `urlparse` reads the same
    string as the authority `169.254.169.254:80` with the rest demoted to the path. A
    check that resolves the name therefore says nothing about where a request built from
    it will connect.

    Restricting the value to letter-digit-hyphen labels removes every byte the two
    grammars read differently, so passing here means both parse it identically. A final
    label of only digits is rejected because that is an IPv4 literal rather than a
    hostname, which keeps address literals out of the DNS path entirely.
    """
    if not domain or len(domain) > MAX_PROXY_DOMAIN_LENGTH:
        return False
    if not _PROXY_DOMAIN_RE.fullmatch(domain):
        return False
    labels = domain.split(".")
    if len(labels) < 2:
        return False
    if any(len(label) > MAX_PROXY_DOMAIN_LABEL_LENGTH for label in labels):
        return False
    return not labels[-1].isdigit()


def is_reserved_proxy_domain(domain: str) -> bool:
    """Whether `domain` is, or is a subdomain of, a domain PostHog itself owns.

    A registered `domain` is the Host this system will route through PostHog's shared
    reverse-proxy ingress (Cloudflare custom hostnames, or the legacy Caddy CNAME target)
    once the CNAME is verified. Letting an org claim one of PostHog's own domains would
    hand them routing, SNI matching, or certificate issuance for a hostname other
    tenants', or PostHog's own, traffic depends on. See `RESERVED_PROXY_DOMAINS` for the
    source of the list.
    """
    domain = domain.lower()
    return any(domain == reserved or domain.endswith(f".{reserved}") for reserved in RESERVED_PROXY_DOMAINS)


# The only reserved apex an allowlisted org may still register under: PostHog's own
# customer-facing domain, for internal proxies such as internal-*.posthog.com. Every other
# reserved entry (the shared Cloudflare/legacy CNAME targets other tenants already point at,
# and PostHog's other apexes) stays unclaimable by everyone, so an allowlisted org cannot grab
# a shared proxy hostname.
RESERVED_PROXY_DOMAIN_EXCEPTION_APEXES = frozenset({"posthog.com"})


def org_may_register_reserved_domain(organization_id: str | UUID, domain: str) -> bool:
    """Whether `organization_id` may register the reserved `domain`.

    `is_reserved_proxy_domain` keeps every org from claiming a PostHog-owned hostname. This is
    its only exception: an org listed in `POSTHOG_INTERNAL_ORG_IDS` (PostHog's
    own org, set per environment) may register a domain under
    `RESERVED_PROXY_DOMAIN_EXCEPTION_APEXES` — i.e. a posthog.com subdomain, for internal
    proxies. A domain under any other reserved apex, and every non-allowlisted org, is still
    refused. The allowlist is empty by default, so the guard stays fully on everywhere unless a
    deployment opts a specific org in.
    """
    domain = domain.lower()
    if not any(domain.endswith(f".{apex}") for apex in RESERVED_PROXY_DOMAIN_EXCEPTION_APEXES):
        return False
    return str(organization_id) in settings.POSTHOG_INTERNAL_ORG_IDS


class ProxyRecord(UUIDTModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="proxy_records")
    domain = models.CharField(max_length=64, unique=True)
    target_cname = models.CharField(max_length=256, null=False)
    root_redirect_url = models.URLField(max_length=1024, null=True, blank=True)
    message = models.CharField(max_length=1024, null=True)

    class Status(models.TextChoices):
        WAITING = "waiting"
        ISSUING = "issuing"
        VALID = "valid"
        WARNING = "warning"
        ERRORING = "erroring"
        DELETING = "deleting"
        TIMED_OUT = "timed_out"

    status = models.CharField(
        choices=Status,
        default=Status.WAITING,
    )

    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
