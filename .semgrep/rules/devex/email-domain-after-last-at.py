# Test cases for email-domain-after-last-at.
# ruff: noqa
from urllib.parse import urlparse

from posthog.helpers.email_utils import email_domain


def first_at_slices(email: str) -> list[str]:
    return [
        # ruleid: email-domain-after-last-at
        email[email.index("@") + 1 :],
        # ruleid: email-domain-after-last-at
        email[email.find("@") + 1 :].lower(),
    ]


def first_at_splits(email: str, config: dict) -> list[str]:
    return [
        # ruleid: email-domain-after-last-at
        email.split("@")[1],
        # ruleid: email-domain-after-last-at
        email.split("@", 1)[1],
        # ruleid: email-domain-after-last-at
        email.split("@", maxsplit=1)[1],
        # ruleid: email-domain-after-last-at
        email.partition("@")[2],
        # ruleid: email-domain-after-last-at
        (config.get("email") or "").partition("@")[2].lower(),
    ]


def first_at_unpacks(email: str, address: str) -> tuple[str, str]:
    # ruleid: email-domain-after-last-at
    local_part, separator, domain = address.strip().lower().partition("@")
    # ruleid: email-domain-after-last-at
    user, host = email.split("@", 1)
    # ruleid: email-domain-after-last-at
    name, server = email.split("@")
    return domain, host + server


def last_at_is_fine(email: str, url: str) -> list[object]:
    _, _, unpacked = email.rpartition("@")
    return [
        # ok: email-domain-after-last-at
        email_domain(email),
        # ok: email-domain-after-last-at
        email.rpartition("@")[2],
        # ok: email-domain-after-last-at
        email.rsplit("@", 1)[-1],
        # ok: email-domain-after-last-at
        email.split("@")[-1],
        # ok: email-domain-after-last-at
        urlparse(url).netloc.rpartition("@")[2],
        unpacked,
    ]


def not_a_domain_read(email: str) -> list[object]:
    return [
        # ok: email-domain-after-last-at
        "@" in email,
        # ok: email-domain-after-last-at
        len(email.split("@")) == 2,
        # ok: email-domain-after-last-at
        email.split("@")[0],
        # ok: email-domain-after-last-at
        email.index("@"),
    ]
