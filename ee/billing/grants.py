"""What a caller may read from billing, computed once on PostHog's side.

PostHog holds the users, memberships, key scopes, organization settings and access flags, so it
works out the answer here and billing checks it. The answer travels in the access token as
three claims. `scope` is what the credential holds. `roles` is who the person is in the
organization. `entitlements` is the access level the role and the two flags add up to.
`projects` is the list a project-scoped credential may see, or None for the whole organization.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from posthog.auth import ProjectSecretAPIKeyAuthentication
from posthog.exceptions_capture import capture_exception
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.permissions import (
    get_authenticator_scoped_team_ids,
    get_authenticator_scopes,
    get_authenticator_user_credential,
    posthog_feature_flag_enabled,
)
from posthog.user_permissions import UserPermissions

from products.access_control.backend.facade.user_access_control import UserAccessControl, visible_teams_for_user

BILLING_READ_SCOPE = "billing:read"
BILLING_WRITE_SCOPE = "billing:write"

OWNER_ONLY_BILLING_FLAG = "owner-only-billing"
MEMBER_BILLING_USAGE_SPEND_READ_ACCESS_FLAG = "member-billing-usage-spend-read-access"
BILLING_LIMIT_TODAYS_USAGE_FLAG = "billing-limit-todays-usage"
BILLING_LIMIT_TODAYS_USAGE_KEYS = ("posthog_code_credits",)


def _owner_only_billing_enabled(user: User, organization: Organization) -> Optional[bool]:
    if not user.distinct_id:
        return None

    try:
        return posthog_feature_flag_enabled(
            OWNER_ONLY_BILLING_FLAG,
            str(user.distinct_id),
            organization_id=organization.id,
        )
    except Exception as e:
        capture_exception(e, {"organization_id": organization.id, "flag": OWNER_ONLY_BILLING_FLAG})
        return None


def _member_billing_usage_spend_read_access_enabled(user: User, organization: Organization) -> bool:
    if not user.distinct_id:
        return False

    try:
        return (
            posthog_feature_flag_enabled(
                MEMBER_BILLING_USAGE_SPEND_READ_ACCESS_FLAG,
                str(user.distinct_id),
                organization_id=organization.id,
            )
            is True
        )
    except Exception as e:
        capture_exception(e, {"organization_id": organization.id, "flag": MEMBER_BILLING_USAGE_SPEND_READ_ACCESS_FLAG})
        return False


def _billing_limit_todays_usage_enabled(user: User, organization: Organization) -> bool:
    if not user.distinct_id:
        return False

    try:
        return (
            posthog_feature_flag_enabled(
                BILLING_LIMIT_TODAYS_USAGE_FLAG,
                str(user.distinct_id),
                organization_id=organization.id,
            )
            is True
        )
    except Exception as e:
        capture_exception(e, {"organization_id": organization.id, "flag": BILLING_LIMIT_TODAYS_USAGE_FLAG})
        return False


class BillingEntitlement(str, Enum):
    """The three access levels of the public billing API. Each covers the ones below it."""

    MEMBER = "billing:member"
    USAGE_READ = "billing:usage_read"
    FULL_ACCESS = "billing:full_access"


@dataclass(frozen=True)
class EffectiveBillingGrants:
    sub: str
    scope: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    entitlements: list[str] = field(default_factory=list)
    projects: Optional[list[int]] = None

    @property
    def grants_anything(self) -> bool:
        return bool(self.entitlements)


NO_GRANTS = EffectiveBillingGrants(sub="anonymous")


def _role_name(level: int) -> str:
    if level >= OrganizationMembership.Level.OWNER:
        return "owner"
    if level >= OrganizationMembership.Level.ADMIN:
        return "admin"
    return "member"


def _entitlement_for_role(user: User, organization: Organization, level: int) -> BillingEntitlement:
    """The access level the role and the two organization flags add up to, the way the flags gate
    the app today. Owners always get full access. Admins get full access unless owner-only billing
    is on, and an unknown flag state counts as on. Members get the usage read level when the member
    read flag is on and owner-only billing is confirmed off."""
    if level >= OrganizationMembership.Level.OWNER:
        return BillingEntitlement.FULL_ACCESS
    owner_only_off = _owner_only_billing_enabled(user, organization) is False
    if level >= OrganizationMembership.Level.ADMIN:
        return BillingEntitlement.FULL_ACCESS if owner_only_off else BillingEntitlement.MEMBER
    if owner_only_off and _member_billing_usage_spend_read_access_enabled(user, organization):
        return BillingEntitlement.USAGE_READ
    return BillingEntitlement.MEMBER


def _billing_scope_from_credential(scopes: Optional[Sequence[str]]) -> list[str]:
    """The billing scopes a credential holds. Session auth acts with the user's full access, so it
    holds `billing:read`. A write scope or `*` implies read, the way APIScopePermission treats
    them."""
    if scopes is None:
        return [BILLING_READ_SCOPE]
    scope_set = set(scopes)
    if "*" in scope_set or BILLING_WRITE_SCOPE in scope_set:
        return [BILLING_READ_SCOPE, BILLING_WRITE_SCOPE]
    if BILLING_READ_SCOPE in scope_set:
        return [BILLING_READ_SCOPE]
    return []


def visible_team_ids(user: User, organization: Organization) -> list[int]:
    return list(
        visible_teams_for_user(
            organization,
            UserAccessControl(user=user, organization_id=str(organization.id)),
            UserPermissions(user=user),
        )
        .order_by("id")
        .values_list("id", flat=True)
    )


def _projects_for_credential(organization: Organization, authenticator: Any) -> tuple[Optional[list[int]], bool]:
    """The projects the credential is scoped to, and whether that is anything at all.

    A credential scoped to teams is clipped to the ones in this organization, whatever the role.
    None means the credential is not scoped. What the user can see is a separate question that
    the series reads answer per request, so a member's visibility never widens or shrinks a
    token, and an organization with thousands of projects never lists them in one.
    """
    scoped = get_authenticator_scoped_team_ids(authenticator)
    if scoped is None:
        return None, True
    organization_team_ids = set(Team.objects.filter(organization=organization).values_list("id", flat=True))
    projects = set(scoped) & organization_team_ids
    if not projects:
        return None, False
    return sorted(projects), True


def _credential_may_act_for(authenticator: Any, organization: Organization) -> bool:
    credential = get_authenticator_user_credential(authenticator)
    if credential is None:
        return True
    scoped_organizations = credential.scoped_organizations or []
    if scoped_organizations and str(organization.id) not in scoped_organizations:
        return False
    return True


def _grants_for_project_secret_key(authenticator: ProjectSecretAPIKeyAuthentication, organization: Organization):
    key = authenticator.project_secret_api_key
    sub = f"project_key:{key.id}"
    if key.team.organization_id != organization.id:
        return EffectiveBillingGrants(sub=sub)
    scope = [BILLING_READ_SCOPE] if BILLING_READ_SCOPE in (key.scopes or []) else []
    if not scope:
        return EffectiveBillingGrants(sub=sub)
    return EffectiveBillingGrants(
        sub=sub,
        scope=scope,
        entitlements=[BillingEntitlement.USAGE_READ.value],
        projects=[key.team_id],
    )


def effective_billing_grants(
    *, organization: Organization, user: Optional[User] = None, authenticator: Any = None
) -> EffectiveBillingGrants:
    """The grants for one request against one organization.

    `authenticator` is `request.successful_authenticator`. It is None for session auth, and the
    personal key, OAuth or project secret key authenticator otherwise. A project secret key is its
    own principal and has no role. Everything else is a user acting through a credential, and the
    credential can only narrow what the user could see."""
    if isinstance(authenticator, ProjectSecretAPIKeyAuthentication):
        return _grants_for_project_secret_key(authenticator, organization)
    if user is None or not isinstance(user, User):
        return NO_GRANTS
    sub = f"user:{user.distinct_id}"
    membership = OrganizationMembership.objects.filter(user=user, organization=organization).only("level").first()
    if membership is None:
        return EffectiveBillingGrants(sub=sub)
    roles = [_role_name(membership.level)]
    if not _credential_may_act_for(authenticator, organization):
        return EffectiveBillingGrants(sub=sub, roles=roles)
    scope = _billing_scope_from_credential(get_authenticator_scopes(authenticator))
    if BILLING_READ_SCOPE not in scope:
        return EffectiveBillingGrants(sub=sub, roles=roles)
    entitlement = _entitlement_for_role(user, organization, membership.level)
    projects, anything = _projects_for_credential(organization, authenticator)
    if not anything:
        return EffectiveBillingGrants(sub=sub, roles=roles, scope=scope)
    return EffectiveBillingGrants(
        sub=sub, scope=scope, roles=roles, entitlements=[entitlement.value], projects=projects
    )
