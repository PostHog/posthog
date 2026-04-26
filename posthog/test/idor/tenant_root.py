"""
Discovery + URL builders for tenant-root viewsets.

A "tenant-root" viewset is one whose detail URL identifies the tenant
itself (organization / project / team) rather than a resource scoped
to a tenant. The standard cross-tenant IDOR test substitutes the
attacker's tenant root into the URL with a victim resource pk; for
tenant-root viewsets the URL *is* the victim, so the test shape is
inverted: hit `/api/<root>/<victim_id>/...` from the attacker's
session and expect 403/404.

Each registered case knows how to build the victim URL given the
victim org/project/team triplet. Permission classes
(OrganizationMemberPermissions, project membership checks, etc.)
should reject every attempt — these tests catch the day a permission
gate gets removed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Optional

from django.db import models


@dataclass(frozen=True)
class TenantRootCase:
    """A viewset whose detail URL is a tenant root (org / project / team)."""

    name: str
    """Viewset class name (matches `cls.__name__`)."""

    model_label: str
    """`app_label.ModelName` for the tenant root model — used for
    documentation / introspection."""

    build_url: Callable[[VictimContext], str]
    """Returns the victim detail URL given the victim's tenant ids."""


@dataclass(frozen=True)
class VictimContext:
    """Identifiers for the victim tenant the test will target."""

    org_uuid: str
    project_pk: int
    team_pk: int


_REGISTRY: dict[str, TenantRootCase] = {}


def register(case: TenantRootCase) -> None:
    _REGISTRY[case.name] = case


def get_case(name: str) -> Optional[TenantRootCase]:
    return _REGISTRY.get(name)


def all_cases() -> list[TenantRootCase]:
    return sorted(_REGISTRY.values(), key=lambda c: c.name)


# ---------------------------------------------------------------------------
# Registered cases — one per tenant-root viewset.
#
# URL builders use the victim's tenant id directly so the request crosses
# the org/project/team boundary. The expected response is a non-2xx denial.
# ---------------------------------------------------------------------------


register(
    TenantRootCase(
        name="OrganizationViewSet",
        model_label="posthog.Organization",
        build_url=lambda v: f"/api/organizations/{v.org_uuid}/",
    )
)


register(
    TenantRootCase(
        name="ProjectViewSet",
        model_label="posthog.Project",
        build_url=lambda v: f"/api/organizations/{v.org_uuid}/projects/{v.project_pk}/",
    )
)


register(
    TenantRootCase(
        name="RootProjectViewSet",
        model_label="posthog.Project",
        build_url=lambda v: f"/api/projects/{v.project_pk}/",
    )
)


register(
    TenantRootCase(
        name="ProjectEnvironmentsViewSet",
        model_label="posthog.Team",
        build_url=lambda v: f"/api/projects/{v.project_pk}/environments/{v.team_pk}/",
    )
)


register(
    TenantRootCase(
        name="RootTeamViewSet",
        model_label="posthog.Team",
        build_url=lambda v: f"/api/environments/{v.team_pk}/",
    )
)


def is_registered_viewset(model_cls: type[models.Model]) -> bool:
    """True if any registered case targets this tenant-root model."""
    label = model_cls._meta.label
    return any(case.model_label == label for case in _REGISTRY.values())
