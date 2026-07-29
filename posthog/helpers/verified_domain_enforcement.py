import structlog
from loginas.utils import is_impersonated_session
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request

from posthog.helpers.two_factor_session import is_path_whitelisted
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.user import User

logger = structlog.get_logger(__name__)

VERIFIED_DOMAIN_REQUIRED_ERROR = (
    "Your organization only allows members with a verified email domain. Contact your organization's admin for access."
)


def enforce_verified_domain(request: Request, user: User) -> None:
    """
    Deny requests from members whose email is outside their current organization's verified domains.

    Re-checked per request, like 2FA enforcement, so enabling the setting takes effect on sessions
    that are already live and switching current organization can't walk around the login-time check.

    Adds no query while the setting is off: `enforce_verified_domains` comes down the same SELECT as
    `enforce_2fa` (Django fetches the whole row), `user.organization` is a cached property that any
    request touching a team or organization resolves anyway, and the domains table is only read once
    the flag is on. Sharing the 2FA whitelist rather than keeping a second one keeps this check from
    becoming the one that resolves the organization on paths 2FA skips, and keeps the paths a
    half-authenticated user needs (login completion, logout, `@me`) identical between the two gates.

    Unlike 2FA this does not exempt SSO sessions — the IdP can handle a second factor, but it has no
    say in which organizations may admit an email domain.
    """
    if is_path_whitelisted(request.path):
        return

    if is_impersonated_session(request._request):
        return

    if OrganizationDomain.objects.is_access_blocked_by_domain_enforcement(user):
        raise PermissionDenied(detail=VERIFIED_DOMAIN_REQUIRED_ERROR, code="verified_domain_required")


def resolve_login_organization(user: User) -> bool:
    """
    Settle which organization `user` lands in, and return whether they may log in at all.

    Login is only refused when no organization admits their email domain — otherwise one
    organization enabling enforcement would lock a member out of the others, with no way back in
    once the blocked organization is the current one. When the current organization no longer
    admits them, they're moved to one that does.
    """
    if not OrganizationDomain.objects.is_access_blocked_by_domain_enforcement(user):
        return True

    permitted_organization = next(
        (
            organization
            for organization in user.organizations.all()
            if not OrganizationDomain.objects.is_email_blocked_by_domain_enforcement(user.email, organization)
        ),
        None,
    )
    if permitted_organization is None:
        return False

    logger.info(
        "domain_enforcement_moved_user_to_permitted_organization",
        user_id=user.pk,
        organization=str(permitted_organization.id),
    )
    user.current_organization = permitted_organization
    user.current_team = permitted_organization.teams.first()
    user.save(update_fields=["current_organization", "current_team"])
    # `organization` and `team` are cached properties still holding the organization we just left.
    user.__dict__.pop("organization", None)
    user.__dict__.pop("team", None)
    return True
