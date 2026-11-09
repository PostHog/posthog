"""Filters a QuerySet to the rows a subject may view, through the authorization SDK.

It lives outside the facade because it takes a QuerySet, which the facade must not accept.
The filters give the same SQL as the current access rules' own filters.
"""

from typing import TYPE_CHECKING, TypeVar

from django.db.models import Model, Q, QuerySet

from posthog.models import Team, User

from products.access_control.backend.facade.user_access_control import (
    RESOURCE_FALLBACK_MAP,
    UserAccessControl,
    model_to_resource,
)

from ..facade import api
from ..facade.contracts import Resource, Subject
from ..facade.enums import Action, ResourceType

if TYPE_CHECKING:
    from posthog.models.file_system.file_system import FileSystem

M = TypeVar("M", bound=Model)

_RESOURCE_TYPES = frozenset(resource_type.value for resource_type in ResourceType)
# `list_objects` lists no membership types and refuses types whose objects fall back to a parent.
_UNFILTERED_RESOURCES = frozenset({"organization", "project", "role", *RESOURCE_FALLBACK_MAP})


def can_filter_queryset(model: type[Model]) -> bool:
    """Whether `filter_queryset` can filter rows of `model`. A caller keeps the other models on the current filter."""
    resource = model_to_resource(model)
    return resource in _RESOURCE_TYPES and resource not in _UNFILTERED_RESOURCES


def filter_queryset(
    queryset: QuerySet[M],
    *,
    resource: Resource,
    subject: Subject | None = None,
    include_all_if_admin: bool = False,
) -> QuerySet[M]:
    """Keep the rows of `queryset` that the subject may view.

    `resource` names the type and the project whose rules apply, without an `id`. The filter applies that
    project's rules but does not scope rows to it, so `queryset` must hold only rows of that project, as
    a project view's queryset does. A creator keeps their own rows when the model has `created_by`. `include_all_if_admin` keeps every row for an org admin, so pass it only
    where the call site passes it today. `subject=None` means the request's user.
    """
    if resource.type == ResourceType.PROJECT:
        raise ValueError("A project list also reads memberships, so use `list_objects` for projects.")
    # QUERY is the list filter with every row for an org admin, which is what `include_all_if_admin` asks for.
    result = api.list_objects(
        resource=resource,
        action=Action.QUERY if include_all_if_admin else Action.VIEW,
        subject=subject,
        creator_exempt=hasattr(queryset.model, "created_by"),
    )
    if not result.complete:
        return queryset.none()
    # The same conditions that `filter_queryset_by_access_level` builds from the same object ids.
    creator = (
        Q(created_by=result.creator_user_id) if result.creator_exempt and result.creator_user_id is not None else None
    )
    if result.excluded:
        if not result.ids:
            return queryset
        if creator is not None:
            return queryset.exclude(Q(id__in=result.ids) & ~creator)
        return queryset.exclude(id__in=result.ids)
    if creator is not None:
        return queryset.filter(Q(id__in=result.ids) | creator)
    return queryset.filter(id__in=result.ids)


def filter_file_system_queryset(
    queryset: "QuerySet[FileSystem]",
    *,
    project_id: int,
    subject: Subject | None = None,
    extra_denied_refs: dict[tuple[str, int], list[str]] | None = None,
) -> "QuerySet[FileSystem]":
    """Keep the file system entries that the subject may view, and annotate each with its access level.

    `project_id` is the team whose rules apply. `extra_denied_refs` maps a (file system type, team id)
    pair to refs that a grant denies, where the ref is not the object's primary key.
    """
    # The v1 filter leaves a non-member's queryset unfiltered, because the view's permission class
    # rejected non-members before it ran.
    if not api.check(
        resource=Resource(type=ResourceType.PROJECT, id=str(project_id)), action=Action.VIEW, subject=subject
    ):
        return queryset.none()
    user_id = api.principal_user_id(subject=subject)
    user = User.objects.filter(pk=user_id).first() if user_id is not None else None
    team = Team.objects.filter(pk=project_id).first()
    if user is None or team is None:
        return queryset.none()
    # The file system filter reads its own rule, which object ids cannot carry, so it runs as it is.
    return UserAccessControl(user=user, team=team).filter_and_annotate_file_system_queryset(queryset, extra_denied_refs)
