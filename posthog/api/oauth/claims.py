"""The OIDC claims this server asserts about a user.

Kept apart from the validator that produces the values and the discovery documents that advertise
the names, so neither imports the other.
"""

from collections.abc import Callable
from typing import Protocol

from posthog.models.user import User


class ClaimRequest(Protocol):
    """The part of the oauthlib request a claim callable reads."""

    user: User


# Claim name to a callable taking the oauthlib request. django-oauth-toolkit reads this through
# `OAuthValidator.get_additional_claims` for both `claims_supported` and the claim values, and
# filters it by granted scope through `OAuth2Validator.oidc_claim_scope`.
OIDC_CLAIMS: dict[str, Callable[[ClaimRequest], str | bool]] = {
    # Overrides django-oauth-toolkit's primary-key default. Changing `sub` would re-identify
    # every user at every relying party.
    "sub": lambda request: str(request.user.uuid),
    "given_name": lambda request: request.user.first_name,
    "family_name": lambda request: request.user.last_name,
    "email": lambda request: request.user.email,
    # A null `is_email_verified` means the account predates email verification, not that the
    # address was checked, so only an explicit True can be reported as verified.
    "email_verified": lambda request: request.user.is_email_verified is True,
}
