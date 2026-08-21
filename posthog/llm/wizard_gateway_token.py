"""Mint a wizard-run scoped gateway token.

The wizard CLI's v2 auth: instead of sending the user's OAuth token to the
gateway, Django mints a `phe_` scoped token off the PostHog-owned wizard team's
`phs_` (WIZARD_GATEWAY_MINT_KEY). The mint pins the attribution the caller must
not control: product=wizard, obo=the customer organization the run is for, and
the acting user — plus a per-run spend cap and an expiry. The customer's own
wallet is never involved; the debit lands on the wizard team.

Sibling of products/tasks' sandbox mint (ai_gateway_token.py); separate because
the wizard needs `expires_at` back for CLI-side refresh and runs on its own
settings, and interactive mints answer one attempt fast instead of retrying
into the CLI's timeout.
"""

from typing import Any

from django.conf import settings

import requests
import structlog
from prometheus_client import Counter

logger = structlog.get_logger(__name__)

_MINT_TIMEOUT_SECONDS = 10

# The gateway refuses a TTL outside these bounds with a 400, so clamp locally: a
# misconfigured setting should not turn every mint into a 503.
_MIN_TTL_SECONDS = 60
_MAX_TTL_SECONDS = 86400

WIZARD_GATEWAY_MINTS = Counter(
    "posthog_wizard_gateway_token_mints_total",
    "Wizard gateway token mints, by outcome (ok/refused/unreachable/malformed)",
    labelnames=["outcome"],
)


class WizardGatewayMintError(Exception):
    """The gateway refused or failed the mint; the caller answers 503 and the
    CLI falls back to the legacy gateway posture."""


def wizard_gateway_configured() -> bool:
    """Every one of the three is required; any missing piece answers 404."""
    return bool(settings.WIZARD_GATEWAY_MINT_KEY and settings.WIZARD_GATEWAY_URL and settings.WIZARD_GATEWAY_CLIENT_IDS)


def wizard_gateway_base_url() -> str:
    """The gateway base the mint posts to, without the version segment. Handed to
    the CLI as well, so both sides read one normalization of the setting."""
    return settings.WIZARD_GATEWAY_URL.rstrip("/").removesuffix("/v1")


def mint_wizard_gateway_token(*, obo: str, user: str) -> dict[str, Any]:
    """Mint one run's token; returns {token, expires_at, cap_usd}.

    Raises WizardGatewayMintError on any refusal or transport failure. The
    bearer never appears in logs or exception text.
    """
    base_url = wizard_gateway_base_url()
    body = {
        "cap_usd": str(settings.WIZARD_GATEWAY_TOKEN_CAP_USD),
        "ttl_seconds": _ttl_seconds(),
        "product": "wizard",
        "obo": obo,
        "user": user,
    }
    try:
        response = requests.post(
            f"{base_url}/v1/tokens",
            json=body,
            headers={"Authorization": f"Bearer {settings.WIZARD_GATEWAY_MINT_KEY}"},
            timeout=_MINT_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        WIZARD_GATEWAY_MINTS.labels(outcome="unreachable").inc()
        logger.warning("wizard_gateway_token: mint transport failure", error=str(e))
        raise WizardGatewayMintError("gateway unreachable") from e

    if response.status_code != 201:
        WIZARD_GATEWAY_MINTS.labels(outcome="refused").inc()
        logger.warning("wizard_gateway_token: mint refused", status=response.status_code)
        raise WizardGatewayMintError(f"mint refused with HTTP {response.status_code}")
    try:
        minted = response.json()
    except ValueError as e:
        WIZARD_GATEWAY_MINTS.labels(outcome="malformed").inc()
        raise WizardGatewayMintError("mint response was not JSON") from e
    if not isinstance(minted, dict) or not minted.get("token") or not minted.get("expires_at"):
        WIZARD_GATEWAY_MINTS.labels(outcome="malformed").inc()
        raise WizardGatewayMintError("mint response missing token or expires_at")
    WIZARD_GATEWAY_MINTS.labels(outcome="ok").inc()
    return {
        "token": minted["token"],
        "expires_at": minted["expires_at"],
        "cap_usd": minted.get("cap_usd"),
    }


def _ttl_seconds() -> int:
    """The requested token lifetime, clamped to the gateway's mint bounds."""
    return max(_MIN_TTL_SECONDS, min(int(settings.WIZARD_GATEWAY_TOKEN_TTL_SECONDS), _MAX_TTL_SECONDS))
