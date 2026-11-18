"""Recorded transport for the Have I Been Pwned Pwned Passwords range API.

The API takes no credential and publishes no rate limit, so these calls are recorded but not gated.
"""

import requests

from posthog.egress.pwned_passwords.observability import pwned_passwords_egress
from posthog.egress.transport.transport import RecordedEgressClient


class PwnedPasswordsClient(RecordedEgressClient):
    observability = pwned_passwords_egress
    egress_domain = "pwned_passwords"

    def _standard_headers(self) -> dict[str, str]:
        # Padding gives every response 800 to 1,000 rows, so the response size does not show the prefix.
        return {"Add-Padding": "true"}


_pwned_passwords_client = PwnedPasswordsClient()


def pwned_passwords_request(
    url: str,
    *,
    source: str,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
) -> requests.Response:
    # The URL ends in a hash prefix that is different for each password, so the endpoint label is fixed.
    return _pwned_passwords_client.request(
        "GET",
        url,
        source=source,
        scope="public",
        endpoint="range/{prefix}",
        headers=headers,
        timeout=timeout,
    )
