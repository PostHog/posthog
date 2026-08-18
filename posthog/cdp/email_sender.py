import re
from typing import Any, Optional

# Kept in sync with FROM_OVERRIDE_EMAIL_REGEX in
# nodejs/src/cdp/services/messaging/email.service.ts. The runtime rejects any override that
# does not match this shape, so authoring-time validation must judge it the same way.
FROM_OVERRIDE_EMAIL_REGEX = re.compile(r'^[^\s@"<>,;]+@[^\s@"<>,;]+\.[^\s@"<>,;]+$')


def from_email_integration_ids(from_value: dict[str, Any]) -> list[int]:
    """Return the selected email sender integration ids, newest picker shape first.

    A single-sender step stores `integrationId`; a rotation stores `integrationIds`.
    """
    ids = from_value.get("integrationIds") or ([from_value["integrationId"]] if from_value.get("integrationId") else [])
    return [i for i in ids if isinstance(i, int) and not isinstance(i, bool)]


def email_integration_domain(config: dict[str, Any]) -> str:
    """Return the verified domain of an email integration, lower-cased.

    Verification is domain-level, so any address on this domain is as verified as the
    integration's own address. Mirrors the runtime's `resolveFromEmailAddress`.
    """
    domain = config.get("domain")
    if not domain:
        email = config.get("email") or ""
        _, _, domain = email.partition("@")
    return (domain or "").lower()


def override_off_domain_reason(config: dict[str, Any], override_email: str) -> Optional[str]:
    """Return why a sender override will be ignored at send time, or None when it is honored.

    The runtime discards an override that is not a valid address or that sits outside the
    integration's verified domain, then sends from the integration's own address instead.
    """
    override_email = override_email.strip()
    if not FROM_OVERRIDE_EMAIL_REGEX.match(override_email):
        return "it is not a valid email address"

    integration_domain = email_integration_domain(config)
    override_domain = override_email.rsplit("@", 1)[-1].lower()
    if not integration_domain or override_domain != integration_domain:
        return f'it is not on the verified domain "{integration_domain}" of the selected sender'

    return None
