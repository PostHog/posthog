"""Refuse the AI gateway to an identity that never verified its email address.

Every other gateway limit is priced per account, so a free account is the hole
underneath all of them. Checked at the same surfaces as the abuse blocklist,
because a credential minted before the check reaches inference without passing
it again.

Allows whenever verification was never asked of the user: an instance with no
email service, an organization that switched verification off, and demo mode all
leave `is_email_verified` unset on legitimate accounts. Every lookup fails open,
since losing the check must not refuse every wizard run.
"""

from typing import TYPE_CHECKING

from django.conf import settings

import structlog
from prometheus_client import Counter

from posthog.email import is_email_available
from posthog.helpers.email_verification_state import is_email_verification_disabled

if TYPE_CHECKING:
    from posthog.models.user import User

logger = structlog.get_logger(__name__)

# The wizard shows this verbatim, so it reads the same at consent, at the mint,
# and on a query.
WIZARD_EMAIL_UNVERIFIED_DETAIL = (
    "Verify your email address to use the PostHog AI gateway. Open PostHog to finish verifying, then try again."
)

# `not_applicable` keeps an instance that cannot verify from reading as a fleet
# of refusals.
WIZARD_EMAIL_VERIFICATION_CHECKS = Counter(
    "posthog_wizard_email_verification_checks_total",
    "Gateway email verification checks, by surface and outcome (verified/unverified/not_applicable)",
    labelnames=["surface", "outcome"],
)


def wizard_email_unverified(*, user: "User | None", surface: str) -> bool:
    """True when this identity must verify its address before reaching the gateway.

    Answers False for every other case, including each way the question cannot be
    asked.
    """
    if user is None:
        # A caller that proved a distinct_id rather than a user has no address to
        # judge, the same reading the blocklist takes.
        _record(surface, "not_applicable")
        return False

    # None marks an account from before verification existed, which the login flow
    # already trusts as verified, so only an explicit False is unverified. Free, and
    # first, so a verified user reaches the gateway without the two lookups below.
    if user.is_email_verified is not False:
        _record(surface, "verified")
        return False

    if settings.DEMO:
        _record(surface, "not_applicable")
        return False

    try:
        if not is_email_available() or is_email_verification_disabled(user):
            _record(surface, "not_applicable")
            return False
    except Exception as e:
        logger.warning("wizard_email_verification: verification state unavailable", error=str(e), surface=surface)
        _record(surface, "not_applicable")
        return False

    # The domain rather than the address, to keep mailboxes out of the logs.
    logger.info(
        "wizard_email_verification: unverified identity refused",
        surface=surface,
        email_domain=(user.email or "").rpartition("@")[2],
    )
    _record(surface, "unverified")
    return True


def _record(surface: str, outcome: str) -> None:
    WIZARD_EMAIL_VERIFICATION_CHECKS.labels(surface=surface, outcome=outcome).inc()
