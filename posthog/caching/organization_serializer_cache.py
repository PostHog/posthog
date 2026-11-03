"""Org-serializer cache versioning and its invalidation receivers.

The OrganizationSerializer caches expensive per-org fields (teams, projects, member count)
under a per-organization version number; writes to any membership-shaped model bump the
version. The receivers must connect at django.setup() — background writes (celery, temporal,
migrate) invalidate too, not just API mutations — so this lives in its own import-light
module wired from PostHogConfig.ready(), not in the API module whose import the lazy router
no longer triggers at setup.
"""

from collections.abc import Callable
from typing import Any

from django.db import transaction
from django.db.models import Model
from django.db.models.signals import post_delete, post_save

from posthog.caching.cache_version import bump_cache_version, read_cache_version
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.project import Project
from posthog.models.team import Team

from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.role import RoleMembership

from ee.models.explicit_team_membership import ExplicitTeamMembership

ORG_SERIALIZER_CACHE_TTL_SECONDS = 60 * 60
ORG_SERIALIZER_VERSION_TTL_SECONDS = 7 * 24 * 60 * 60
_ORG_SERIALIZER_VERSION_KEY_PREFIX = "org_serializer_version:"


def _org_serializer_version_key(organization_id: str) -> str:
    return f"{_ORG_SERIALIZER_VERSION_KEY_PREFIX}{organization_id}"


def _org_serializer_cache_version(organization_id: str) -> int:
    return read_cache_version(_org_serializer_version_key(organization_id), ORG_SERIALIZER_VERSION_TTL_SECONDS)


def _bump_org_serializer_cache_version(organization_id: str) -> None:
    bump_cache_version(_org_serializer_version_key(organization_id), ORG_SERIALIZER_VERSION_TTL_SECONDS)


def _instance_org_id(instance: Any) -> str | None:
    organization_id = getattr(instance, "organization_id", None)
    return str(organization_id) if organization_id is not None else None


def _team_id_to_org_id(instance: Any) -> str | None:
    team_id = getattr(instance, "team_id", None)
    if team_id is None:
        return None
    organization_id = Team.objects.filter(id=team_id).values_list("organization_id", flat=True).first()
    return str(organization_id) if organization_id is not None else None


def _role_id_to_org_id(instance: Any) -> str | None:
    role = getattr(instance, "role", None)
    if role is None:
        return None
    organization_id = getattr(role, "organization_id", None)
    return str(organization_id) if organization_id is not None else None


_VISIBILITY_RESOURCES = {"project", "organization"}


def _access_control_to_org_id(instance: Any) -> str | None:
    if getattr(instance, "resource", None) not in _VISIBILITY_RESOURCES:
        return None
    return _team_id_to_org_id(instance)


_INVALIDATION_SOURCES: list[tuple[type[Model], Callable[[Any], str | None]]] = [
    (Organization, lambda instance: str(instance.pk)),
    (Team, _instance_org_id),
    (Project, _instance_org_id),
    (OrganizationMembership, _instance_org_id),
    (AccessControl, _access_control_to_org_id),
    (ExplicitTeamMembership, _team_id_to_org_id),
    (RoleMembership, _role_id_to_org_id),
]


def _connect_invalidation(model: type[Model], get_org_id: Callable[[Any], str | None]) -> None:
    def receiver_fn(sender: type[Model], instance: Any, **kwargs: Any) -> None:
        organization_id = get_org_id(instance)
        if organization_id is None:
            return
        _bump_org_serializer_cache_version(organization_id)
        transaction.on_commit(lambda: _bump_org_serializer_cache_version(organization_id))

    post_save.connect(receiver_fn, sender=model, weak=False)
    post_delete.connect(receiver_fn, sender=model, weak=False)


for _model, _resolver in _INVALIDATION_SOURCES:
    _connect_invalidation(_model, _resolver)
