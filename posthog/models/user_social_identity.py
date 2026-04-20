from typing import TYPE_CHECKING

from django.db import models

from posthog.models.organization_domain import OrganizationDomain
from posthog.utils import get_instance_available_sso_providers

if TYPE_CHECKING:
    from posthog.models.user import User


GITHUB_PROVIDER = "github"
# Providers whose rows the user can remove; SAML is managed by the IdP side.
_DISCONNECTABLE_PROVIDERS = {"github", "google-oauth2", "gitlab"}


class UserSocialIdentity(models.Model):
    """Identity-only link between a PostHog user and a third-party account.

    Decoupled from ``UserSocialAuth`` (python-social-auth) which controls *login*.
    A user with login enabled has both a ``UserSocialAuth`` row and a
    ``UserSocialIdentity`` row. Identity-only users have only the latter.

    For backward compatibility, a ``UserSocialAuth`` row without a matching
    ``UserSocialIdentity`` is treated as if the identity exists. The identity
    row is backfilled lazily when the user toggles off login.

    Unlike ``UserSocialAuth`` (unique on provider+uid), multiple PostHog users
    may hold a ``UserSocialIdentity`` for the same provider+uid — that's
    intentional so several team members can map to the same external identity
    for attribution purposes.
    """

    user = models.ForeignKey(
        "posthog.User",
        on_delete=models.CASCADE,
        related_name="social_identities",
    )
    provider = models.CharField(max_length=32)
    uid = models.CharField(max_length=255)
    extra_data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_user_social_identity"
        unique_together = [("user", "provider")]


def sso_enforcement_for(user: "User") -> str | None:
    if not user.email:
        return None
    return OrganizationDomain.objects.get_sso_enforcement_for_email_address(user.email)


def can_user_enable_login_for(user: "User", provider: str) -> bool:
    """Whether the Settings UI toggle should be clickable for this (user, provider).

    SSO enforcement blocks enabling login for any provider other than the enforced one.
    """
    enforcement = sso_enforcement_for(user)
    return enforcement is None or enforcement == provider


def available_providers_for_user(user: "User") -> list[str]:
    """Ordered list of providers to show in the user's Linked accounts section.

    When SSO is enforced, the enforced provider is always shown. GitHub is also
    always included when available, because its link flow bypasses social-auth
    entirely and can be used for identity-only linking regardless of SSO policy.
    """
    enforcement = sso_enforcement_for(user)
    if enforcement is not None:
        providers = [enforcement]
        if enforcement != GITHUB_PROVIDER:
            all_available = get_instance_available_sso_providers()
            if all_available.get(GITHUB_PROVIDER):
                providers.append(GITHUB_PROVIDER)
        return providers
    return [name for name, available in get_instance_available_sso_providers().items() if available]


def can_disconnect_provider(user: "User", provider: str) -> bool:
    """Whether the given provider can be disconnected by the user.

    Disallowed when:
    - the provider is the enforced SSO method, or
    - the provider isn't one whose row users manage directly (e.g. SAML, managed by IdP).
    """
    if provider not in _DISCONNECTABLE_PROVIDERS:
        return False
    return sso_enforcement_for(user) != provider
