from collections.abc import Callable, Iterable
from ipaddress import ip_address, ip_network
from typing import TYPE_CHECKING, Any, ParamSpec, Protocol, TypeVar, cast
from uuid import UUID, uuid4

from django.core.cache import caches
from django.db import DEFAULT_DB_ALIAS
from django.http import HttpRequest

import structlog
from loginas.utils import is_impersonated_session
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from posthog.models.activity_logging.utils import DeclaredCredentialType
from posthog.models.organization import Organization
from posthog.models.organization_ip_restrictions import MAX_IP_RESTRICTIONS, OrganizationIPRestrictions
from posthog.models.team import Team

if TYPE_CHECKING:
    from rest_framework.request import Request

    from posthog.models.user import User

    class _OrganizationScopedView(Protocol):
        kwargs: dict[str, Any]
        basename: str | None
        action: str

        @property
        def _is_team_view(self) -> bool: ...

        @property
        def _is_project_view(self) -> bool: ...

        @property
        def team(self) -> Team: ...

        @property
        def organization(self) -> Organization: ...


__all__ = [
    "IPRestrictionsPermission",
    "MAX_IP_RESTRICTIONS",
    "enforce_ip_restrictions",
    "enforce_credential_ip_restrictions",
    "get_ip_restriction_denial",
    "get_ip_blocked_organization_ids",
    "get_restriction_client_ip",
    "is_ip_allowed",
    "is_ip_restriction_exempt",
    "ip_restrictions_exempt",
    "ip_restrictions_exempt_for_secret_keys",
    "validate_ip_restrictions",
]

_CACHE_KEY_PREFIX = "ip_restrictions:v2:principal"
_CACHE_TTL_SECONDS = 60 * 5
_CACHE_MISS = object()
cache = caches["organization_access"]
logger = structlog.get_logger(__name__)
P = ParamSpec("P")
R = TypeVar("R")


def ip_restrictions_exempt(view: Callable[P, R]) -> Callable[P, R]:
    """Exempt a public endpoint for every credential, including sessions."""
    setattr(view, "ip_restrictions_exempt", True)  # noqa: B010 - Callable does not declare view metadata
    return view


def ip_restrictions_exempt_for_secret_keys(view: Callable[P, R]) -> Callable[P, R]:
    """Exempt SDK secret keys while enforcing session and personal-key policies."""
    credential_types: frozenset[DeclaredCredentialType] = frozenset({"project_secret_key", "team_secret_token"})
    setattr(view, "ip_restrictions_exempt", credential_types)  # noqa: B010
    return view


def is_ip_restriction_exempt(request: HttpRequest, credential_type: str | None = None) -> bool:
    match = request.resolver_match
    if match is None:
        return False
    callback = match.func
    exemption = getattr(callback, "ip_restrictions_exempt", False)
    if not exemption:
        method = "get" if request.method == "HEAD" else (request.method or "").lower()
        action = getattr(callback, "actions", {}).get(method)
        handler = getattr(getattr(callback, "cls", None), action, None) if action else None
        exemption = getattr(handler, "ip_restrictions_exempt", False)
    if isinstance(exemption, frozenset):
        # Middleware defers to DRF so a blocked session cookie cannot prevent SDK authentication.
        return credential_type is None or credential_type in exemption
    return bool(exemption)


# Credentials PostHog's own infrastructure uses to serve a request on the user's behalf. They
# originate from our network, not the member's, so an organization's allowlist cannot judge them and
# blocking them would break the feature without adding security. Delegated credentials still
# enforce the policy, using the signed end-user IP when MCP forwards it.
_INTERNAL_CREDENTIAL_TYPES: frozenset[DeclaredCredentialType] = frozenset(
    {
        "internal_jwt",
        "export_renderer",
        "service_jwt",
        "internal_api_secret",
        "billing_service",
        "gateway_agent",
        "cross_region_signature",
        "webhook",
    }
)


def validate_ip_restrictions(values: Iterable[str]) -> list[str]:
    """Return the entries as entered, stripped, deduplicated, and verified as IPs or CIDR blocks."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        entry = value.strip()
        if entry in seen:
            continue
        if len(cleaned) >= MAX_IP_RESTRICTIONS:
            raise ValueError(f"You can add at most {MAX_IP_RESTRICTIONS} IP addresses or CIDR blocks.")
        try:
            ip_network(entry, strict=False)
        except (TypeError, ValueError) as error:
            raise ValueError(f"'{entry}' is not a valid IP address or CIDR block.") from error
        seen.add(entry)
        cleaned.append(entry)

    return cleaned


def is_ip_allowed(ip: str, restrictions: Iterable[str]) -> bool:
    """Whether `ip` falls inside any of the allowlisted addresses or CIDR blocks."""
    try:
        parsed_ip = ip_address(ip)
    except (TypeError, ValueError):
        return False

    for restriction in restrictions:
        try:
            if parsed_ip in ip_network(restriction, strict=False):
                return True
        except (TypeError, ValueError):
            continue
    return False


def _user_cache_key(user_id: int) -> str:
    return f"{_CACHE_KEY_PREFIX}:user:{user_id}"


def _team_cache_key(team_id: int, organization_id: str) -> str:
    return f"{_CACHE_KEY_PREFIX}:team:{team_id}:organization:{organization_id}"


def _internal_org_cache_key(organization_id: Any) -> str:
    return f"{_CACHE_KEY_PREFIX}:internal:{organization_id}"


def _principal_cache_key(user: Any) -> str | None:
    if hasattr(user, "organization_memberships"):
        user_id = getattr(user, "pk", None)
        return _user_cache_key(user_id) if user_id else None
    team = getattr(user, "team", None)
    if team is not None:
        return _team_cache_key(team.id, str(team.organization_id))
    organization_id = getattr(user, "current_organization_id", None)
    return _internal_org_cache_key(organization_id) if organization_id else None


def _organization_ids_for_principal(user: Any) -> list[str]:
    if hasattr(user, "organization_memberships"):
        return [
            str(organization_id)
            for organization_id in user.organization_memberships.using(DEFAULT_DB_ALIAS).values_list(
                "organization_id", flat=True
            )
        ]
    team = getattr(user, "team", None)
    if team is not None:
        return [str(team.organization_id)]
    organization_id = getattr(user, "current_organization_id", None)
    return [str(organization_id)] if organization_id else []


def _load_ip_restrictions_for_principal(user: Any) -> list[tuple[str, list[str]]]:
    organization_ids = _organization_ids_for_principal(user)
    if not organization_ids:
        return []
    rows = (
        OrganizationIPRestrictions.objects.using(DEFAULT_DB_ALIAS)
        .filter(
            organization_id__in=organization_ids,
            enabled=True,
        )
        .values_list("organization_id", "ip_restrictions")
    )
    return [(str(organization_id), ip_restrictions) for organization_id, ip_restrictions in rows if ip_restrictions]


def get_ip_restrictions_for_principal(user: Any) -> list[tuple[str, list[str]]]:
    cache_key = _principal_cache_key(user)
    if cache_key is not None:
        # Invalidation removes the generation, so readers spanning a commit can only populate
        # an obsolete key. Random generations also prevent reuse after cache eviction.
        try:
            generation = cache.get_or_set(cache_key, str(uuid4()), _CACHE_TTL_SECONDS)
            cache_key = f"{cache_key}:{generation}"
            cached = cache.get(cache_key, _CACHE_MISS)
            if cached is not _CACHE_MISS:
                return [(row["organization_id"], row["ip_restrictions"]) for row in cached]
        except Exception:
            logger.warning("ip_restrictions_cache_read_failed", exc_info=True)
            cache_key = None

    restrictions = _load_ip_restrictions_for_principal(user)
    if cache_key is not None:
        try:
            cache.set(
                cache_key,
                [
                    {"organization_id": organization_id, "ip_restrictions": ip_restrictions}
                    for organization_id, ip_restrictions in restrictions
                ],
                _CACHE_TTL_SECONDS,
            )
        except Exception:
            logger.warning("ip_restrictions_cache_write_failed", exc_info=True)
    return restrictions


def _ip_restriction_denial(policies: list[tuple[str, list[str]]], ip: str | None, organization_id: str) -> str | None:
    restrictions = [rules for org_id, rules in policies if org_id == organization_id]
    if not restrictions:
        return None
    if ip is not None and all(is_ip_allowed(ip, rules) for rules in restrictions):
        return None
    return (
        f"Your IP address ({ip or 'unknown'}) is not allowed to access this organization. "
        "Ask an organization admin to add it to the IP restrictions list."
    )


def get_ip_restriction_denial(user: Any, ip: str | None, organization_id: str | None = None) -> str | None:
    """Return the error detail when the target organization blocks `ip`."""
    if organization_id is None:
        team = getattr(user, "team", None)
        organization_id = str(team.organization_id) if team is not None else str(user.current_organization_id)
    return _ip_restriction_denial(get_ip_restrictions_for_principal(user), ip, organization_id)


def _invalidate_cache_keys(cache_keys: list[str]) -> None:
    try:
        cache.delete_many(cache_keys)
    except Exception:
        logger.warning("ip_restrictions_cache_invalidation_failed", exc_info=True)
        try:
            # Keep Celery task imports off the auth startup path.
            from posthog.tasks.ip_restrictions import retry_ip_restrictions_invalidation  # noqa: PLC0415

            retry_ip_restrictions_invalidation.delay(cache_keys)
        except Exception:
            logger.warning("ip_restrictions_cache_invalidation_retry_failed", exc_info=True)


def invalidate_ip_restrictions_for_organization(organization_id: Any) -> None:
    from posthog.models.organization import OrganizationMembership
    from posthog.models.team import Team

    cache_keys = [_internal_org_cache_key(organization_id)]
    cache_keys.extend(
        _user_cache_key(user_id)
        for user_id in OrganizationMembership.objects.using(DEFAULT_DB_ALIAS)
        .filter(organization_id=organization_id)
        .values_list("user_id", flat=True)
    )
    cache_keys.extend(
        _team_cache_key(team_id, str(organization_id))
        for team_id in Team.objects.using(DEFAULT_DB_ALIAS)
        .filter(organization_id=organization_id)
        .values_list("id", flat=True)
    )
    _invalidate_cache_keys(cache_keys)


def invalidate_ip_restrictions_for_user(user_id: int) -> None:
    _invalidate_cache_keys([_user_cache_key(user_id)])


def get_restriction_client_ip(request: Any) -> str | None:
    """The IP an IP restriction decision judges for this request.

    `ActivityLoggingMiddleware` verifies and removes the MCP server's signed end-user IP before this
    runs. Prefer that verified value so an MCP call is judged as the person, not the pod address.
    """
    from posthog.utils import get_trusted_client_ip

    verified_mcp_ip = getattr(request, "verified_mcp_client_ip", None)
    if verified_mcp_ip:
        return verified_mcp_ip
    return get_trusted_client_ip(request)


def _team_organization_id(team_id: int | str | None) -> str | None:
    if team_id is None:
        return None
    try:
        organization_id = (
            Team.objects.using(DEFAULT_DB_ALIAS)
            .filter(id=int(team_id))
            .values_list("organization_id", flat=True)
            .first()
        )
    except (TypeError, ValueError):
        return None
    return str(organization_id) if organization_id else None


def _is_account_recovery_request(request: HttpRequest, user: Any, basename: str | None, kwargs: dict[str, Any]) -> bool:
    if basename == "users":
        return True
    if basename == "organization_members" and request.method == "DELETE":
        member = kwargs.get("user__uuid")
        return member in ("@me", str(getattr(user, "uuid", "")))
    # Listing and creating organizations must stay available for account recovery.
    return basename == "organizations" and "id" not in kwargs


def _view_organization_id(view: "_OrganizationScopedView") -> str:
    # Legacy views can resolve .project from the current selection while .team follows the token.
    if view._is_team_view or view._is_project_view:
        return str(view.team.organization_id)
    return str(view.organization.id)


def _route_organization_id(request: HttpRequest, user: Any, kwargs: dict[str, Any], basename: str | None) -> str | None:
    match = request.resolver_match
    view_class = getattr(match.func, "cls", None) if match else None
    organization_id = kwargs.get("parent_lookup_organization_id", kwargs.get("organization_id"))
    team_id = kwargs.get(
        "parent_lookup_team_id", kwargs.get("parent_lookup_project_id", kwargs.get("team_id", kwargs.get("project_id")))
    )
    if basename == "organizations":
        organization_id = kwargs.get("id")
    if basename in ("projects", "organization_projects"):
        team_id = kwargs.get("id")
    if team_id is None and getattr(view_class, "param_derived_from_user_current_team", None):
        team_id = getattr(user, "current_team_id", None)
    if team_id is not None:
        if team_id == "@current":
            team_id = getattr(user, "current_team_id", None)
        return _team_organization_id(team_id)
    if organization_id == "@current":
        organization_id = getattr(user, "current_organization_id", None)
    elif organization_id is None:
        organization_id = getattr(getattr(user, "team", None), "organization_id", None) or getattr(
            user, "current_organization_id", None
        )
    try:
        return str(UUID(str(organization_id))) if organization_id else None
    except ValueError:
        return None


def _request_organization_id(
    request: HttpRequest, user: Any, view: "_OrganizationScopedView | None" = None
) -> str | None:
    if view is not None:
        kwargs = view.kwargs
        basename = view.basename
    else:
        match = request.resolver_match
        kwargs = match.kwargs if match else {}
        basename = getattr(match.func, "initkwargs", {}).get("basename") if match else None
    if _is_account_recovery_request(request, user, basename, kwargs):
        return None
    # The flat project list spans organizations and filters their policies in its queryset.
    if view is not None and basename == "projects" and view.action == "list":
        return None
    if view is not None and basename not in ("projects", "organization_projects"):
        return _view_organization_id(view)
    return _route_organization_id(request, user, kwargs, basename)


def _uses_view_scope(request: HttpRequest) -> bool:
    match = request.resolver_match
    view_class = getattr(match.func, "cls", None) if match else None
    scope = getattr(view_class, "_ip_restrictions_use_view_scope", False)
    if isinstance(scope, frozenset) and match is not None:
        method = "get" if request.method == "HEAD" else (request.method or "").lower()
        return getattr(match.func, "actions", {}).get(method) in scope
    return bool(scope)


def _request_policies(request: Any, user: Any) -> list[tuple[str, list[str]]]:
    policies: list[tuple[str, list[str]]] | None = getattr(request, "_ip_restrictions_policies", None)
    if getattr(request, "_ip_restrictions_policies_principal", None) is user and policies is not None:
        return policies
    policies = get_ip_restrictions_for_principal(user)
    request._ip_restrictions_policies = policies
    request._ip_restrictions_policies_principal = user
    return policies


def _is_impersonated_request(request: HttpRequest, authenticator: Any) -> bool:
    if is_impersonated_session(request):
        return True
    # Authenticators call before DRF sets successful_authenticator on the request.
    access_token = getattr(authenticator, "access_token", None)
    return access_token is not None and access_token.impersonated_by_id is not None


def _is_enforcement_exempt(request: Any, user: Any, authenticator: Any) -> bool:
    credential_type = getattr(authenticator, "activity_credential_type", None)
    return (
        is_ip_restriction_exempt(request, credential_type)
        or user is None
        or not getattr(user, "is_authenticated", False)
        or credential_type in _INTERNAL_CREDENTIAL_TYPES
        or _is_impersonated_request(request, authenticator)
    )


def enforce_credential_ip_restrictions(
    request: "Request", scoped_organization_ids: list[str] | None, scoped_team_ids: list[int] | None
) -> None:
    user = cast("User", request.user)
    organization_ids = {str(UUID(str(org_id))) for org_id in scoped_organization_ids or []}
    if scoped_team_ids:
        organization_ids.update(
            str(org_id)
            for org_id in Team.objects.filter(pk__in=scoped_team_ids).values_list("organization_id", flat=True)
        )
    if not scoped_organization_ids and not scoped_team_ids:
        organization_ids = {str(org_id) for org_id in user.organizations.values_list("id", flat=True)}
    blocked_organizations = organization_ids & get_ip_blocked_organization_ids(request)
    if blocked_organizations:
        enforce_ip_restrictions(
            request, user, request.successful_authenticator, organization_id=next(iter(blocked_organizations))
        )


def enforce_ip_restrictions(
    request: Any,
    user: Any,
    authenticator: Any = None,
    *,
    view: "_OrganizationScopedView | None" = None,
    organization_id: str | None = None,
) -> None:
    """Raise `PermissionDenied` when the target organization's allowlist blocks the request.

    Scoped views defer until their target is resolved. Routed viewsets use permissions, while
    custom endpoints pass the organization resolved by their own tenant guards.
    """
    django_request = getattr(request, "_request", request)
    if _is_enforcement_exempt(django_request, user, authenticator):
        return

    if view is None and organization_id is None and _uses_view_scope(django_request):
        return

    checked_principal = getattr(django_request, "_ip_restrictions_checked_principal", None)
    if checked_principal is user and view is None and organization_id is None:
        return

    policies = _request_policies(django_request, user)
    if not policies:
        django_request._ip_restrictions_checked_principal = user
        return

    if organization_id is None:
        organization_id = _request_organization_id(django_request, user, view)
    if organization_id is None:
        return
    denial = _ip_restriction_denial(policies, get_restriction_client_ip(django_request), organization_id)
    if denial is not None:
        raise PermissionDenied(detail=denial, code="ip_not_allowed")
    django_request._ip_restrictions_checked_principal = user


def get_ip_blocked_organization_ids(request: "Request") -> frozenset[str]:
    user = request.user
    django_request: Any = getattr(request, "_request", request)
    if _is_enforcement_exempt(django_request, user, getattr(request, "successful_authenticator", None)):
        return frozenset()
    policies = _request_policies(django_request, user)
    ip = get_restriction_client_ip(django_request)
    cached: tuple[Any, list[tuple[str, list[str]]], str | None, frozenset[str]] | None = getattr(
        django_request, "_ip_restrictions_blocked_organizations", None
    )
    if cached is not None and cached[0] is user and cached[1] is policies and cached[2] == ip:
        return cached[3]
    blocked = frozenset(org_id for org_id, rules in policies if ip is None or not is_ip_allowed(ip, rules))
    django_request._ip_restrictions_blocked_organizations = (user, policies, ip, blocked)
    return blocked


class IPRestrictionsPermission(BasePermission):
    """Deny requests when the target organization blocks their IP.

    Routed viewsets always include this permission, which uses their resolved organization.
    Middleware and bearer authenticators cover endpoints outside that routing mixin.
    """

    def has_permission(self, request, view) -> bool:
        enforce_ip_restrictions(
            request,
            getattr(request, "user", None),
            getattr(request, "successful_authenticator", None),
            view=view if getattr(view, "_ip_restrictions_use_view_scope", False) else None,
        )
        return True

    def has_object_permission(self, request: "Request", view: object, obj: object) -> bool:
        if isinstance(obj, Organization):
            enforce_ip_restrictions(
                request,
                request.user,
                request.successful_authenticator,
                organization_id=str(obj.id),
            )
        return True
