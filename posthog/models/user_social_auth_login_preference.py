from typing import TYPE_CHECKING

from django.db import models

from social_django.models import UserSocialAuth

from posthog.models.organization_domain import OrganizationDomain
from posthog.utils import get_instance_available_sso_providers

if TYPE_CHECKING:
    from posthog.models.user import User


GITHUB_PROVIDER = "github"
# Providers whose rows the user can remove; SAML is managed by the IdP side.
_DISCONNECTABLE_PROVIDERS = {"github", "google-oauth2", "gitlab"}


class UserSocialAuthLoginPreference(models.Model):
    """Per-`UserSocialAuth` override for whether the provider may be used to sign in.

    The row's presence signals that the user expressed a non-default preference.
    When absent, callers fall back to :func:`default_login_enabled_for`, which
    encodes product policy (GitHub is identity-only by default) plus SSO
    enforcement (sign-in via a non-enforced provider is blocked).
    """

    social_auth = models.OneToOneField(
        UserSocialAuth,
        on_delete=models.CASCADE,
        related_name="login_preference",
        primary_key=True,
    )
    login_enabled = models.BooleanField()
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_user_social_auth_login_preference"


def sso_enforcement_for(user: "User") -> str | None:
    if not user.email:
        return None
    return OrganizationDomain.objects.get_sso_enforcement_for_email_address(user.email)


def default_login_enabled_for(user: "User", provider: str) -> bool:
    """The fallback when there is no :class:`UserSocialAuthLoginPreference` row.

    Row absence means the user has never expressed a preference, so we let sign-in
    through. Product policies that *deny* sign-in (e.g. GitHub being identity-only by
    default) are enforced at *write time* by creating an explicit preference row with
    ``login_enabled=False``, not at read time. This way pre-existing rows from before
    the feature shipped continue to work without a backfill.

    SSO enforcement is the only read-time gate left here: if the org enforces SSO via
    a different provider, sign-in via this one is impossible anyway.
    """
    enforcement = sso_enforcement_for(user)
    if enforcement is not None:
        return enforcement == provider
    return True


def can_user_enable_login_for(user: "User", provider: str) -> bool:
    """Whether the Settings UI toggle should be clickable for this (user, provider).

    Distinct from :func:`default_login_enabled_for`: the GitHub product default is
    off but *overridable*; SSO enforcement is off and *not* overridable.
    """
    enforcement = sso_enforcement_for(user)
    return enforcement is None or enforcement == provider


def available_providers_for_user(user: "User") -> list[str]:
    """Ordered list of providers to show in the user's Linked accounts section.

    When SSO is enforced for the user's domain, only the enforced provider is shown — every
    other sign-in option is hidden because it's non-functional for this user.
    Otherwise, all SSO providers that are properly configured instance-wide are shown.
    """
    enforcement = sso_enforcement_for(user)
    if enforcement is not None:
        return [enforcement]
    return [name for name, available in get_instance_available_sso_providers().items() if available]


def can_disconnect_provider(user: "User", provider: str) -> bool:
    """Whether the given provider can be disconnected by the user.

    Disallowed when:
    - the provider is the enforced SSO method (disconnecting would lock the user out of their org), or
    - the provider isn't one whose row users are expected to manage directly (e.g. SAML, managed by IdP).
    """
    if provider not in _DISCONNECTABLE_PROVIDERS:
        return False
    return sso_enforcement_for(user) != provider


def effective_login_enabled(social_auth: UserSocialAuth) -> bool:
    """Whether sign-in is currently allowed for this UserSocialAuth row.

    Reads the preference row when present; falls back to
    :func:`default_login_enabled_for`. Callers should prefetch
    ``login_preference`` to avoid an extra query per row.
    """
    try:
        pref = social_auth.login_preference
    except UserSocialAuthLoginPreference.DoesNotExist:
        return default_login_enabled_for(social_auth.user, social_auth.provider)
    return pref.login_enabled
