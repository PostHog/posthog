import re
from typing import Optional

from django.db.models import Q

import structlog
from loginas.utils import is_impersonated_session
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request

from posthog.helpers.two_factor_session import is_path_whitelisted
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.user import User

logger = structlog.get_logger(__name__)

VERIFIED_DOMAIN_REQUIRED_ERROR = (
    "Your organization only allows members with a verified email domain. Contact your organization's admin for access."
)

_ORGANIZATION_DETAIL_PATH = re.compile(r"^/api/organizations/[^/]+/?$")


def is_enforcement_disable_request(request: Request) -> bool:
    """
    The escape hatch, mirroring 2FA's whitelisted `two_factor_disable`: a PATCH to the organization
    itself passes the domain gates so a blocked admin can turn `enforce_verified_domains` off.
    `OrganizationSerializer.validate` rejects every other field change from a blocked admin, and the
    standard admin-write permission still applies.
    """
    return request.method == "PATCH" and bool(_ORGANIZATION_DETAIL_PATH.match(request.path))


def verified_domain_email_q(organization: Organization) -> Optional[Q]:
    """
    Q matching `OrganizationMembership` rows whose user's email is on one of the organization's
    verified domains, or None when the organization has no verified domains (every membership is
    then outside them). Independent of `enforce_verified_domains`, so callers can preview the
    impact of enabling it.
    """
    domains = list(
        OrganizationDomain.objects.verified_domains().filter(organization=organization).values_list("domain", flat=True)
    )
    if not domains:
        return None
    admitted = Q()
    for domain in domains:
        admitted |= Q(user__email__iendswith=f"@{domain}")
    return admitted


def enforce_verified_domain(request: Request, user: User) -> None:
    """
    Deny requests from members whose email is outside their current organization's verified domains,
    so enabling the setting cuts off sessions that are already live. The authoritative boundary is
    `VerifiedDomainEnforcementPermission`, which checks the URL-resolved organization and covers
    non-session authenticators too.

    Unlike the 2FA check next to this one, SSO sessions are not exempt: an IdP login proves who the
    user is, not that the organization admits their email domain.
    """
    if is_path_whitelisted(request.path):
        return

    if is_enforcement_disable_request(request):
        return

    if is_impersonated_session(request._request):
        return

    if OrganizationDomain.objects.is_access_blocked_by_domain_enforcement(user):
        raise PermissionDenied(detail=VERIFIED_DOMAIN_REQUIRED_ERROR, code="verified_domain_required")


def resolve_login_organization(user: User) -> bool:
    """
    Settle which organization `user` lands in at login, and return whether login may proceed.

    When the current organization no longer admits their email, they're moved to one that does.
    When no organization admits them, only admins may still log in — the per-request gate then
    denies everything except the whitelist and the enforcement escape hatch, so they can disable
    the setting after their session expired. Members have no recovery action a session would
    enable, so they're refused outright with a clear error instead of a fully gated app.
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
        return user.organization_memberships.filter(level__gte=OrganizationMembership.Level.ADMIN).exists()

    logger.info(
        "domain_enforcement_moved_user_to_permitted_organization",
        user_id=user.pk,
        organization=str(permitted_organization.id),
    )
    user.current_organization = permitted_organization
    user.current_team = permitted_organization.teams.first()
    user.save(update_fields=["current_organization", "current_team"])
    # `user.organization` / `user.team` are cached properties, already read above with the blocked
    # organization; drop the cached values so later code in this request sees the new one.
    user.__dict__.pop("organization", None)
    user.__dict__.pop("team", None)
    return True
