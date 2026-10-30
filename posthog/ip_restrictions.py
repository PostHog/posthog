from collections.abc import Iterable
from ipaddress import ip_address, ip_network
from typing import Any

from django.core.cache import cache

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from posthog.models.organization_ip_restrictions import MAX_IP_RESTRICTIONS, OrganizationIPRestrictions

__all__ = [
    "IPRestrictionsPermission",
    "MAX_IP_RESTRICTIONS",
    "get_ip_restriction_denial",
    "is_ip_allowed",
    "validate_ip_restrictions",
]

_CACHE_KEY_PREFIX = "ip_restrictions:principal"
_CACHE_TTL_SECONDS = 60 * 5
_CACHE_MISS = object()


def validate_ip_restrictions(values: Iterable[str]) -> list[str]:
    """Return the entries as entered, stripped, deduplicated, and verified as IPs or CIDR blocks."""
    cleaned: list[str] = []
    for value in values:
        entry = value.strip()
        try:
            ip_network(entry, strict=False)
        except (TypeError, ValueError) as error:
            raise ValueError(f"'{entry}' is not a valid IP address or CIDR block.") from error
        if entry not in cleaned:
            cleaned.append(entry)

    if len(cleaned) > MAX_IP_RESTRICTIONS:
        raise ValueError(f"You can add at most {MAX_IP_RESTRICTIONS} IP addresses or CIDR blocks.")

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
            # A malformed stored entry must not open access for anyone.
            continue
    return False


def _user_cache_key(user_id: int) -> str:
    return f"{_CACHE_KEY_PREFIX}:user:{user_id}"


def _team_cache_key(team_id: int) -> str:
    return f"{_CACHE_KEY_PREFIX}:team:{team_id}"


def _internal_org_cache_key(organization_id: Any) -> str:
    return f"{_CACHE_KEY_PREFIX}:internal:{organization_id}"


def _principal_cache_key(user: Any) -> str | None:
    if hasattr(user, "organization_memberships"):
        user_id = getattr(user, "pk", None)
        return _user_cache_key(user_id) if user_id else None
    team = getattr(user, "team", None)
    if team is not None:
        return _team_cache_key(team.id)
    organization_id = getattr(user, "current_organization_id", None)
    return _internal_org_cache_key(organization_id) if organization_id else None


def _organization_ids_for_principal(user: Any) -> list[str]:
    if hasattr(user, "organization_memberships"):
        return [
            str(organization_id)
            for organization_id in user.organization_memberships.values_list("organization_id", flat=True)
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
    rows = OrganizationIPRestrictions.objects.filter(
        organization_id__in=organization_ids,
        enabled=True,
    ).values_list("organization_id", "ip_restrictions")
    return [(str(organization_id), ip_restrictions) for organization_id, ip_restrictions in rows if ip_restrictions]


def get_ip_restrictions_for_principal(user: Any) -> list[tuple[str, list[str]]]:
    cache_key = _principal_cache_key(user)
    if cache_key is not None:
        cached = cache.get(cache_key, _CACHE_MISS)
        if cached is not _CACHE_MISS:
            return [(row["organization_id"], row["ip_restrictions"]) for row in cached]

    restrictions = _load_ip_restrictions_for_principal(user)
    if cache_key is not None:
        cache.set(
            cache_key,
            [
                {"organization_id": organization_id, "ip_restrictions": ip_restrictions}
                for organization_id, ip_restrictions in restrictions
            ],
            _CACHE_TTL_SECONDS,
        )
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


def invalidate_ip_restrictions_for_organization(organization_id: Any) -> None:
    from posthog.models.organization import OrganizationMembership
    from posthog.models.team import Team

    cache_keys = [_internal_org_cache_key(organization_id)]
    cache_keys.extend(
        _user_cache_key(user_id)
        for user_id in OrganizationMembership.objects.filter(organization_id=organization_id).values_list(
            "user_id", flat=True
        )
    )
    cache_keys.extend(
        _team_cache_key(team_id)
        for team_id in Team.objects.filter(organization_id=organization_id).values_list("id", flat=True)
    )
    cache.delete_many(cache_keys)


def invalidate_ip_restrictions_for_user(user_id: int) -> None:
    cache.delete(_user_cache_key(user_id))


class IPRestrictionsPermission(BasePermission):
    """Deny token-authenticated requests when any organization the principal belongs to blocks its IP.

    Session-auth requests are handled by `IPRestrictionsMiddleware` before the view runs. Bearer
    credentials authenticate inside DRF, so this permission checks them after the principal is
    resolved. It applies to every organization the principal belongs to, not only the current one.
    """

    def has_permission(self, request, view) -> bool:
        from loginas.utils import is_impersonated_session

        from posthog.utils import get_trusted_client_ip

        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return True
        authenticator = getattr(request, "successful_authenticator", None)
        if getattr(authenticator, "activity_credential_type", None) == "session":
            return True

        django_request = getattr(request, "_request", request)
        if is_impersonated_session(django_request):
            return True

        denial = get_ip_restriction_denial(user, get_trusted_client_ip(django_request))
        if denial is not None:
            raise PermissionDenied(detail=denial, code="ip_not_allowed")
        return True
