from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid4

from django.apps import apps
from django.conf import settings
from django.core.cache import caches
from django.db import transaction
from django.db.models.signals import post_delete, post_save

import structlog

if TYPE_CHECKING:
    from posthog.models.organization import Organization, OrganizationMembership
    from posthog.models.user import User


logger = structlog.get_logger(__name__)

access_cache = caches["organization_access"]

ORGANIZATION_ACCESS_CACHE_TTL_SECONDS = 60
_ORGANIZATION_ACCESS_CACHE_MISS = "missing"


def _organization_model() -> type[Organization]:
    return cast("type[Organization]", apps.get_model("posthog", "Organization"))


def _organization_membership_model() -> type[OrganizationMembership]:
    return cast("type[OrganizationMembership]", apps.get_model("posthog", "OrganizationMembership"))


def _organization_cache_key(organization_id: str | UUID) -> str:
    return f"organization_access:organization:{organization_id}"


def _organization_membership_cache_key(organization_id: str | UUID, user_id: int) -> str:
    return f"organization_access:membership:{organization_id}:{user_id}"


def _user_organization_memberships_cache_key(user_id: int) -> str:
    return f"organization_access:user_memberships:{user_id}"


def _access_cache_version_key(key: str) -> str:
    return f"{key}:version"


def _get_access_cache_value(key: str) -> Any:
    try:
        return access_cache.get(key)
    except Exception:
        logger.warning("organization_access_cache_get_failure", cache_key=key, exc_info=True)
        return None


def _set_access_cache_value(key: str, value: Any) -> None:
    try:
        access_cache.set(key, value, timeout=ORGANIZATION_ACCESS_CACHE_TTL_SECONDS)
    except Exception:
        logger.warning("organization_access_cache_set_failure", cache_key=key, exc_info=True)


def _delete_access_cache_value(key: str) -> None:
    try:
        access_cache.delete(key)
    except Exception:
        logger.warning("organization_access_cache_delete_failure", cache_key=key, exc_info=True)


def _get_cache_version(key: str) -> str | None:
    value = _get_access_cache_value(_access_cache_version_key(key))
    return value if isinstance(value, str) else None


def _set_versioned_access_cache_value(key: str, value: Any, version: str | None) -> None:
    _set_access_cache_value(key, (version, value))


def _get_versioned_access_cache_value(key: str, version: str | None = None) -> Any | None:
    cached = _get_access_cache_value(key)
    if not isinstance(cached, tuple) or len(cached) != 2:
        return None
    cached_version, value = cached
    if cached_version != _get_cache_version(key) or (version is not None and cached_version != version):
        return None
    return value


def _cache_organization(organization: Organization, version: str | None) -> None:
    _set_versioned_access_cache_value(_organization_cache_key(organization.id), organization, version)


def get_cached_organization(organization_id: str | UUID) -> Organization | None:
    organization_model = _organization_model()
    if not settings.ORGANIZATION_ACCESS_CACHE_ENABLED:
        try:
            return organization_model.objects.get(id=organization_id)
        except (organization_model.DoesNotExist, ValueError):
            return None

    key = _organization_cache_key(organization_id)
    version = _get_cache_version(key)
    cached = _get_versioned_access_cache_value(key, version)
    if cached == _ORGANIZATION_ACCESS_CACHE_MISS:
        return None
    if isinstance(cached, organization_model):
        return cached

    try:
        organization = organization_model.objects.get(id=organization_id)
    except (organization_model.DoesNotExist, ValueError):
        _set_versioned_access_cache_value(key, _ORGANIZATION_ACCESS_CACHE_MISS, version)
        return None

    _set_versioned_access_cache_value(key, organization, version)
    return organization


def _prepare_cached_membership(membership: OrganizationMembership, user: User) -> OrganizationMembership:
    membership._state.fields_cache["user"] = user
    organization = membership._state.fields_cache.get("organization") or get_cached_organization(
        membership.organization_id
    )
    if organization is not None:
        membership._state.fields_cache["organization"] = organization
    return membership


def _cache_membership(membership: OrganizationMembership, version: str | None = None) -> None:
    organization = membership._state.fields_cache.pop("organization", None)
    user = membership._state.fields_cache.pop("user", None)
    key = _organization_membership_cache_key(membership.organization_id, membership.user_id)
    _set_versioned_access_cache_value(key, membership, _get_cache_version(key) if version is None else version)
    if organization is not None:
        membership._state.fields_cache["organization"] = organization
    if user is not None:
        membership._state.fields_cache["user"] = user


def get_cached_organization_membership(organization_id: str | UUID, user: User) -> OrganizationMembership | None:
    organization_membership_model = _organization_membership_model()
    if not settings.ORGANIZATION_ACCESS_CACHE_ENABLED:
        try:
            return organization_membership_model.objects.select_related("organization").get(
                organization_id=organization_id, user_id=user.id
            )
        except (organization_membership_model.DoesNotExist, ValueError):
            return None

    key = _organization_membership_cache_key(organization_id, user.id)
    version = _get_cache_version(key)
    organization_version = _get_cache_version(_organization_cache_key(organization_id))
    cached = _get_versioned_access_cache_value(key, version)
    if cached == _ORGANIZATION_ACCESS_CACHE_MISS:
        return None
    if isinstance(cached, organization_membership_model):
        return _prepare_cached_membership(cached, user)

    try:
        membership = organization_membership_model.objects.select_related("organization").get(
            organization_id=organization_id, user_id=user.id
        )
    except (organization_membership_model.DoesNotExist, ValueError):
        _set_versioned_access_cache_value(key, _ORGANIZATION_ACCESS_CACHE_MISS, version)
        return None

    _cache_organization(membership.organization, organization_version)
    _cache_membership(membership, version)
    return _prepare_cached_membership(membership, user)


def get_cached_organization_memberships(user: User) -> list[OrganizationMembership]:
    organization_membership_model = _organization_membership_model()
    if not settings.ORGANIZATION_ACCESS_CACHE_ENABLED:
        return list(organization_membership_model.objects.filter(user_id=user.id).select_related("organization"))

    key = _user_organization_memberships_cache_key(user.id)
    version = _get_cache_version(key)
    cached = _get_versioned_access_cache_value(key, version)
    if isinstance(cached, list):
        return [_prepare_cached_membership(membership, user) for membership in cached]

    memberships = list(organization_membership_model.objects.filter(user_id=user.id).select_related("organization"))
    for membership in memberships:
        get_cached_organization(membership.organization_id)
        membership._state.fields_cache.pop("organization", None)
        membership._state.fields_cache.pop("user", None)
    _set_versioned_access_cache_value(key, memberships, version)
    return [_prepare_cached_membership(membership, user) for membership in memberships]


def invalidate_organization_access_cache(organization_id: str | UUID) -> None:
    if not settings.ORGANIZATION_ACCESS_CACHE_ENABLED:
        return

    key = _organization_cache_key(organization_id)
    _set_access_cache_value(_access_cache_version_key(key), uuid4().hex)
    _delete_access_cache_value(key)


def invalidate_organization_membership_access_cache(organization_id: str | UUID, user_id: int) -> None:
    if not settings.ORGANIZATION_ACCESS_CACHE_ENABLED:
        return

    keys = (
        _organization_membership_cache_key(organization_id, user_id),
        _user_organization_memberships_cache_key(user_id),
    )

    def invalidate_after_commit() -> None:
        for key in keys:
            _set_access_cache_value(_access_cache_version_key(key), uuid4().hex)
            _delete_access_cache_value(key)

    transaction.on_commit(invalidate_after_commit)


def clear_organization_access_cache(sender: Any, instance: Organization, **kwargs: Any) -> None:
    invalidate_organization_access_cache(instance.id)
    transaction.on_commit(lambda: invalidate_organization_access_cache(instance.id))


def clear_organization_membership_access_cache(sender: Any, instance: OrganizationMembership, **kwargs: Any) -> None:
    invalidate_organization_membership_access_cache(instance.organization_id, instance.user_id)


def connect_signal_handlers() -> None:
    post_save.connect(clear_organization_access_cache, sender=_organization_model())
    post_delete.connect(clear_organization_access_cache, sender=_organization_model())
    post_save.connect(clear_organization_membership_access_cache, sender=_organization_membership_model())
    post_delete.connect(clear_organization_membership_access_cache, sender=_organization_membership_model())
