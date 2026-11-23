from enum import StrEnum

from two_factor.utils import default_device

from posthog.helpers.two_factor_session import has_passkeys
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.user import User


class NormalLoginRequiredReason(StrEnum):
    TWO_FACTOR_REQUIRED = "two_factor_required"
    SSO_ENFORCED = "sso_enforced"


def normal_login_required_reason(user: User) -> NormalLoginRequiredReason | None:
    """
    Return why `user` must sign in through the login page, or None when a login that skips it may proceed.

    Logins that create a session without the login page, such as partner deep links and partner SSO, call this
    before `login()`. They cannot ask for the second factor the user enrolled, and they do not use the identity
    provider that the user's email domain enforces.
    """
    if default_device(user) or (user.passkeys_enabled_for_2fa and has_passkeys(user)):
        return NormalLoginRequiredReason.TWO_FACTOR_REQUIRED

    if OrganizationDomain.objects.get_sso_enforcement_for_email_address(user.email):
        return NormalLoginRequiredReason.SSO_ENFORCED

    return None
