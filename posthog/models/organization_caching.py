from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.core.cache import cache
from django.db import transaction

import structlog

if TYPE_CHECKING:
    from posthog.models.organization import Organization, OrganizationMembership
    from posthog.models.user import User


logger = structlog.get_logger(__name__)

ORGANIZATION_ACCESS_CACHE_TTL_SECONDS = 60
_ORGANIZATION_ACCESS_CACHE_MISS = "missing"


def _organization_cache_key(organization_id: str | UUID) -> str:
    return f"organization_access:organization:{organization_id}"


def _organization_membership_cache_key(organization_id: str | UUID, user_id: int) -> str:
    return f"organization_access:membership:{organization_id}:{user_id}"


def _user_organization_memberships_cache_key(user_id: int) -> str:
    return f"organization_access:user_memberships:{user_id}"


def _get_access_cache_value(key: str) -> Any:
    try:
        return cache.get(key)
    except Exception:
        logger.warning("organization_access_cache_get_failure", cache_key=key, exc_info=True)
        return None


def _set_access_cache_value(key: str, value: Any) -> None:
    try:
        cache.set(key, value, timeout=ORGANIZATION_ACCESS_CACHE_TTL_SECONDS)
    except Exception:
        logger.warning("organization_access_cache_set_failure", cache_key=key, exc_info=True)


def _delete_access_cache_value(key: str) -> None:
    try:
        cache.delete(key)
    except Exception:
        logger.warning("organization_access_cache_delete_failure", cache_key=key, exc_info=True)


def _cache_organization(organization: "Organization") -> None:
    _set_access_cache_value(_organization_cache_key(organization.id), organization)


def get_cached_organization(organization_id: str | UUID) -> "Organization | None":
    from posthog.models.organization import Organization  # noqa: PLC0415 -- avoids a model import cycle

    key = _organization_cache_key(organization_id)
    cached = _get_access_cache_value(key)
    if cached == _ORGANIZATION_ACCESS_CACHE_MISS:
        return None
    if isinstance(cached, Organization):
        return cached

    try:
        organization = Organization.objects.get(id=organization_id)
    except (Organization.DoesNotExist, ValueError):
        _set_access_cache_value(key, _ORGANIZATION_ACCESS_CACHE_MISS)
        return None

    _cache_organization(organization)
    return organization


def _prepare_cached_membership(membership: "OrganizationMembership", user: "User") -> "OrganizationMembership":
    membership._state.fields_cache["user"] = user
    organization = get_cached_organization(membership.organization_id)
    if organization is not None:
        membership._state.fields_cache["organization"] = organization
    return membership


def _cache_membership(membership: "OrganizationMembership") -> None:
    organization = membership._state.fields_cache.pop("organization", None)
    user = membership._state.fields_cache.pop("user", None)
    _set_access_cache_value(
        _organization_membership_cache_key(membership.organization_id, membership.user_id), membership
    )
    if organization is not None:
        membership._state.fields_cache["organization"] = organization
    if user is not None:
        membership._state.fields_cache["user"] = user


def get_cached_organization_membership(organization_id: str | UUID, user: "User") -> "OrganizationMembership | None":
    from posthog.models.organization import OrganizationMembership  # noqa: PLC0415 -- avoids a model import cycle

    key = _organization_membership_cache_key(organization_id, user.id)
    cached = _get_access_cache_value(key)
    if cached == _ORGANIZATION_ACCESS_CACHE_MISS:
        return None
    if isinstance(cached, OrganizationMembership):
        return _prepare_cached_membership(cached, user)

    try:
        membership = OrganizationMembership.objects.select_related("organization").get(
            organization_id=organization_id, user_id=user.id
        )
    except (OrganizationMembership.DoesNotExist, ValueError):
        _set_access_cache_value(key, _ORGANIZATION_ACCESS_CACHE_MISS)
        return None

    _cache_organization(membership.organization)
    _cache_membership(membership)
    return _prepare_cached_membership(membership, user)


def get_cached_organization_memberships(user: "User") -> list["OrganizationMembership"]:
    from posthog.models.organization import OrganizationMembership  # noqa: PLC0415 -- avoids a model import cycle

    key = _user_organization_memberships_cache_key(user.id)
    cached = _get_access_cache_value(key)
    if isinstance(cached, list):
        return [_prepare_cached_membership(membership, user) for membership in cached]

    memberships = list(OrganizationMembership.objects.filter(user_id=user.id).select_related("organization"))
    for membership in memberships:
        _cache_organization(membership.organization)
        _cache_membership(membership)
        membership._state.fields_cache.pop("organization", None)
        membership._state.fields_cache.pop("user", None)
    _set_access_cache_value(key, memberships)
    return [_prepare_cached_membership(membership, user) for membership in memberships]


def invalidate_organization_access_cache(organization_id: str | UUID) -> None:
    _delete_access_cache_value(_organization_cache_key(organization_id))


def invalidate_organization_membership_access_cache(organization_id: str | UUID, user_id: int) -> None:
    keys = (
        _organization_membership_cache_key(organization_id, user_id),
        _user_organization_memberships_cache_key(user_id),
    )
    for key in keys:
        _delete_access_cache_value(key)

    def invalidate_after_commit() -> None:
        for key in keys:
            _delete_access_cache_value(key)

    transaction.on_commit(invalidate_after_commit)
