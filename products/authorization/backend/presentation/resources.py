"""Builds an authorization `Resource` from a model, with the facts the access rules read from it.

It lives outside the facade because it takes a Django model, which the facade must not accept.
"""

from django.db.models import Model

from posthog.models import Team

from products.access_control.backend.facade.user_access_control import (
    RESOURCE_FALLBACK_MAP,
    fallback_parent_object_id,
    model_to_resource,
)

from ..facade.contracts import Parent, Resource
from ..facade.enums import ResourceType

MEMBERSHIP_RESOURCES = frozenset({ResourceType.ORGANIZATION, ResourceType.PROJECT, ResourceType.ROLE})


def resource_for_object(obj: Model, *, team: Team | None = None) -> Resource:
    """The `Resource` for one object, with its creator and the parent it falls back to.

    `project_id` is the object's team id, because access rules are scoped to a team. Pass `team`
    only where today's check reads another team's rules for this object, such as the view's team.
    Never for dashboards: v1 always reads a dashboard's own team.
    """
    scope = model_to_resource(obj)
    if scope is None:
        raise ValueError(f"{type(obj).__name__} has no access control resource.")
    resource_type = ResourceType(scope)
    if resource_type in MEMBERSHIP_RESOURCES:
        raise NotImplementedError(f"Building a {resource_type} resource from a model is not supported yet.")
    if team is not None and resource_type == ResourceType.DASHBOARD:
        raise ValueError("A dashboard always uses its own team's rules, so do not pass `team`.")
    team_id = team.id if team is not None else getattr(obj, "team_id", None)
    if team_id is None:
        raise ValueError(f"{type(obj).__name__} has no team, so its access rules cannot be resolved.")
    parent = RESOURCE_FALLBACK_MAP.get(scope)
    return Resource(
        type=resource_type,
        id=str(obj.pk),
        project_id=team_id,
        created_by_id=getattr(obj, "created_by_id", None),
        parent=Parent(type=ResourceType(parent), id=fallback_parent_object_id(obj, parent)) if parent else None,
    )
