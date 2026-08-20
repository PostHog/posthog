import re

from django.db import models

from posthog.models import Organization
from posthog.models.utils import UUIDTModel

MAX_PROXY_DOMAIN_LENGTH = 253
MAX_PROXY_DOMAIN_LABEL_LENGTH = 63

_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
_PROXY_DOMAIN_RE = re.compile(rf"{_LABEL}(?:\.{_LABEL})*")


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


class ProxyRecord(UUIDTModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="proxy_records")
    domain = models.CharField(max_length=64, unique=True)
    target_cname = models.CharField(max_length=256, null=False)
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
