import structlog
from loginas.utils import is_impersonated_session
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request

from posthog.models.organization_domain import OrganizationDomain
from posthog.models.user import User

logger = structlog.get_logger(__name__)

VERIFIED_DOMAIN_REQUIRED_ERROR = (
    "Your organization only allows members with a verified email domain. Contact your organization's admin for access."
)

# Paths a blocked member must still reach, so they can be told what happened, log out, and pick
# another organization instead of facing a dead app.
WHITELISTED_PATHS = [
    "/logout/",
    "/api/logout/",
    "/api/login/",
    "/api/users/@me/",
    "/_health/",
]

WHITELISTED_PREFIXES = [
    "/static/",
    "/uploaded_media/",
    "/api/signup",
    "/api/social_signup",
    "/login/",
    "/complete/",
]


def _is_path_whitelisted(path: str) -> bool:
    return path in WHITELISTED_PATHS or any(path.startswith(prefix) for prefix in WHITELISTED_PREFIXES)


def enforce_verified_domain(request: Request, user: User) -> None:
    """
    Deny requests from members whose email is outside their current organization's verified domains.

    Re-checked per request, like 2FA enforcement, so enabling the setting takes effect on sessions
    that are already live and switching current organization can't walk around the login-time check.
    Costs nothing for the vast majority of organizations: the predicate short-circuits on the
    organization's own flag before touching the domains table.
    """
    if _is_path_whitelisted(request.path):
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
