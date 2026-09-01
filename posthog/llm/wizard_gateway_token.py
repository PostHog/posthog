"""Mint a wizard-run scoped gateway token.

Django mints a `phe_` off the PostHog-owned wizard team's `phs_`
(WIZARD_GATEWAY_MINT_KEY) rather than sending the user's OAuth token to the
gateway. The mint pins what the caller must not control (product=wizard, obo=the
customer organization, the acting user) plus a per-run cap and an expiry, and the
debit lands on the wizard team, never the customer's wallet. Kept separate from
products/tasks' sandbox mint (ai_gateway_token.py): the wizard needs
`expires_at` back for CLI-side refresh, and an interactive mint answers one
attempt fast instead of retrying into the CLI's timeout.
"""

from decimal import Decimal, InvalidOperation
from typing import Any

from django.conf import settings

import requests
import structlog
from prometheus_client import Counter

logger = structlog.get_logger(__name__)

_MINT_TIMEOUT_SECONDS = 10

# The gateway refuses a TTL outside these bounds with a 400, so clamp locally: a
# misconfigured setting should not turn every mint into a 503.
# Far above the gateway's own 60s floor: a run's holders capture the bearer once
# and cannot re-resolve, so a token must outlive the whole run. Clamping to that
# floor would turn a misconfigured knob into mid-run 401s.
_MIN_TTL_SECONDS = 3600
_MAX_TTL_SECONDS = 86400

# The gateway 400s a cap that is non-positive, over 6dp, or above its top-up
# ceiling, so a bad knob falls back locally instead of 503ing every mint.
_DEFAULT_CAP_USD = Decimal("20")
_MAX_CAP_USD = Decimal("10000")
_CAP_QUANTUM = Decimal("0.000001")

WIZARD_PRODUCT = "wizard"


def wizard_product_node(program: str | None) -> str | None:
    """The product node to pin for a run, or None when this is not a program
    Django knows.

    The setting is authoritative: an unrecognized program is refused rather than
    folded into a generic node. Gateway budgets match a node value exactly, so
    folding would report a new program's spend as plain wizard spend and leave the
    program itself with no budget of its own, and the drift would be silent.
    A refusal is visible in the mint outcome counter, and the endpoint answers it
    with a 404, the one status the CLI falls back on: a program this deploy has
    not been told about keeps running on the legacy gateway rather than having
    its run killed, while still being unable to mint.
    """
    # isinstance first: the value is caller JSON, and an unhashable one (a list
    # or object) raises on the set membership below, inside a throttle that runs
    # before authentication.
    if isinstance(program, str) and program in set(settings.WIZARD_GATEWAY_PROGRAM_IDS):
        return f"{WIZARD_PRODUCT}:{program}"
    return None


WIZARD_GATEWAY_MINTS = Counter(
    "posthog_wizard_gateway_token_mints_total",
    "Wizard gateway token mints, by outcome (ok/refused/unreachable/malformed)",
    labelnames=["outcome"],
)


class WizardGatewayMintError(Exception):
    """The gateway refused or failed the mint; the caller answers 503.

    token_may_exist is False only when the failure proves no token was issued,
    so the caller can return the daily mint slot. It defaults True: refunding a
    slot for a token the gateway did mint would let the ceiling be exceeded.
    """

    def __init__(self, message: str, *, token_may_exist: bool = True) -> None:
        super().__init__(message)
        self.token_may_exist = token_may_exist


def wizard_gateway_configured() -> bool:
    """Every one of the four is required; any missing piece answers 404.

    The program list is a hard requirement, not a refinement: an empty one
    refuses every program, so without it the deploy would report itself
    configured and 400 every request as though the callers were at fault.
    """
    return bool(
        settings.WIZARD_GATEWAY_MINT_KEY
        and settings.WIZARD_GATEWAY_URL
        and settings.WIZARD_GATEWAY_CLIENT_IDS
        and settings.WIZARD_GATEWAY_PROGRAM_IDS
    )


def wizard_gateway_base_url() -> str:
    """The gateway base without the version segment. The CLI gets the same string,
    so both sides read one normalization of the setting."""
    return settings.WIZARD_GATEWAY_URL.rstrip("/").removesuffix("/v1")


def mint_wizard_gateway_token(*, obo: str, user: str, product: str = WIZARD_PRODUCT) -> dict[str, Any]:
    """Mint one run's token; returns {token, expires_at, cap_usd}. Raises
    WizardGatewayMintError on any refusal or transport failure; the bearer never
    appears in logs or exception text.
    """
    base_url = wizard_gateway_base_url()
    body = {
        "cap_usd": _cap_usd(),
        "ttl_seconds": _ttl_seconds(),
        "product": product,
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
        # Only a failure after the request was transmitted can leave a token behind.
        # URL and schema errors raise before any byte is sent, and a connect-level
        # failure never established the session; ConnectTimeout subclasses
        # ConnectionError, while a ReadTimeout's request may have landed.
        #
        # Not a clean split: requests re-raises a body-phase read timeout as
        # ConnectionError, so that case refunds despite the request landing. The
        # token it may leave behind is never delivered, and a cap is a ceiling
        # rather than a reservation, so an unheld token spends nothing.
        never_sent = isinstance(
            e,
            (
                requests.exceptions.ConnectionError,
                requests.exceptions.URLRequired,
                requests.exceptions.MissingSchema,
                requests.exceptions.InvalidSchema,
                requests.exceptions.InvalidURL,
            ),
        )
        raise WizardGatewayMintError("gateway unreachable", token_may_exist=not never_sent) from e

    if response.status_code != 201:
        WIZARD_GATEWAY_MINTS.labels(outcome="refused").inc()
        logger.warning("wizard_gateway_token: mint refused", status=response.status_code)
        # The gateway answered and refused, so no token was issued.
        raise WizardGatewayMintError(f"mint refused with HTTP {response.status_code}", token_may_exist=False)
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


def _cap_usd() -> str:
    """The per-token cap as a fixed-point string the gateway accepts. An
    unparseable, non-positive, or over-ceiling setting falls back to the default
    rather than making every mint a 503.
    """
    raw = str(settings.WIZARD_GATEWAY_TOKEN_CAP_USD)
    try:
        cap = Decimal(raw)
    except (InvalidOperation, ValueError):
        logger.warning("wizard_gateway_token: cap_usd is not a decimal, using the default", cap=raw)
        cap = _DEFAULT_CAP_USD
    # Quantize before the range check: a positive value below a microdollar
    # rounds to 0.000000, which the gateway rejects as non-positive. Guarded
    # because quantize raises once the result needs more digits than the decimal
    # context allows, and this function's contract is to fall back, never raise.
    if cap.is_finite():
        try:
            cap = cap.quantize(_CAP_QUANTUM)
        except InvalidOperation:
            logger.warning("wizard_gateway_token: cap_usd is out of representable range, using the default", cap=raw)
            cap = _DEFAULT_CAP_USD.quantize(_CAP_QUANTUM)
    if not cap.is_finite() or cap <= 0 or cap > _MAX_CAP_USD:
        logger.warning("wizard_gateway_token: cap_usd out of range, using the default", cap=raw)
        cap = _DEFAULT_CAP_USD.quantize(_CAP_QUANTUM)
    return f"{cap:f}"
