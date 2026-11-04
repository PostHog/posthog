from collections.abc import Callable, Iterable
from ipaddress import ip_address, ip_network
from typing import Any, ParamSpec, TypeVar
from uuid import uuid4

from django.core.cache import caches
from django.db import DEFAULT_DB_ALIAS
from django.http import HttpRequest

import structlog
from celery import shared_task
from loginas.utils import is_impersonated_session
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from posthog.models.activity_logging.utils import DeclaredCredentialType
from posthog.models.organization_ip_restrictions import MAX_IP_RESTRICTIONS, OrganizationIPRestrictions

__all__ = [
    "IPRestrictionsPermission",
    "MAX_IP_RESTRICTIONS",
    "enforce_ip_restrictions",
    "get_ip_restriction_denial",
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
# blocking them would break the feature without adding security. A delegated credential is handled separately: it
# only represents a person when the MCP server forwards the signed end-user IP.
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


def get_ip_restriction_denial(user: Any, ip: str | None) -> str | None:
    """Return the error detail when any organization this principal belongs to blocks `ip`."""
    restrictions = get_ip_restrictions_for_principal(user)
    if not restrictions:
        return None
    if ip is not None and all(is_ip_allowed(ip, rules) for _, rules in restrictions):
        return None
    return (
        f"Your IP address ({ip or 'unknown'}) is not allowed to access PostHog for one of your organizations. "
        "Ask an organization admin to add it to the IP restrictions list."
    )


@shared_task(autoretry_for=(Exception,), retry_backoff=True, max_retries=6, ignore_result=True)
def retry_ip_restrictions_invalidation(cache_keys: list[str]) -> None:
    cache.delete_many(cache_keys)


def _invalidate_cache_keys(cache_keys: list[str]) -> None:
    try:
        cache.delete_many(cache_keys)
    except Exception:
        logger.warning("ip_restrictions_cache_invalidation_failed", exc_info=True)
        try:
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


def enforce_ip_restrictions(request: Any, user: Any, authenticator: Any = None) -> None:
    """Raise `PermissionDenied` when the request's IP is not in one of the user's allowlists.

    Session requests are checked by `IPRestrictionsMiddleware`. Bearer credentials authenticate
    inside DRF, and a view that overrides `permission_classes` may omit `IPRestrictionsPermission`,
    so bearer authenticators call this after resolving the principal. It applies to every
    organization the principal belongs to, not only the current one.
    """
    django_request = getattr(request, "_request", request)
    credential_type = getattr(authenticator, "activity_credential_type", None)
    if is_ip_restriction_exempt(django_request, credential_type):
        return

    if user is None or not getattr(user, "is_authenticated", False):
        return

    if credential_type in _INTERNAL_CREDENTIAL_TYPES:
        return

    if is_impersonated_session(django_request):
        return
    access_token = getattr(authenticator, "access_token", None)
    if access_token is not None and access_token.impersonated_by_id is not None:
        return

    checked_principal = getattr(django_request, "_ip_restrictions_checked_principal", None)
    if checked_principal is user:
        return

    denial = get_ip_restriction_denial(user, get_restriction_client_ip(django_request))
    if denial is not None:
        raise PermissionDenied(detail=denial, code="ip_not_allowed")
    django_request._ip_restrictions_checked_principal = user


class IPRestrictionsPermission(BasePermission):
    """Deny token-authenticated requests when any organization the principal belongs to blocks its IP.

    Session-auth requests are handled by `IPRestrictionsMiddleware` before the view runs. Bearer
    credentials authenticate inside DRF, so this permission checks them after the principal is
    resolved. `enforce_ip_restrictions` holds the shared rules; bearer authenticators call it too so
    a view that overrides `permission_classes` cannot skip the check.
    """

    def has_permission(self, request, view) -> bool:
        enforce_ip_restrictions(
            request,
            getattr(request, "user", None),
            getattr(request, "successful_authenticator", None),
        )
        return True
