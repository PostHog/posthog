from typing import TYPE_CHECKING, TypeVar, cast

from django.contrib.auth.models import AnonymousUser
from django.db.models import Model, Q, QuerySet

from posthog.models import Team, User
from posthog.models.access_filter import filter_q
from posthog.synthetic_user import SyntheticUser

from products.access_control.backend.facade.contracts import ObjectAccessRef
from products.access_control.backend.facade.user_access_control import model_to_resource
from products.authz.backend.facade import api
from products.authz.backend.facade.contracts import Resource, Subject
from products.authz.backend.facade.enums import Action, ResourceType

if TYPE_CHECKING:
    from products.dashboards.backend.models.dashboard import Dashboard

M = TypeVar("M", bound=Model)
RESOURCE_ACTIONS = {"viewer": Action.VIEW, "editor": Action.EDIT, "manager": Action.MANAGE_ACCESS}


def resource_for_object(obj: Model | ObjectAccessRef) -> Resource:
    if isinstance(obj, ObjectAccessRef):
        return Resource(type=ResourceType(obj.resource), id=obj.id, project_id=obj.team_id)
    resource_type = model_to_resource(obj)
    if resource_type is None:
        raise ValueError("Object has no authorization resource type")
    if resource_type == "project":
        return Resource(type=ResourceType.PROJECT, id=str(obj.pk), organization_id=cast(Team, obj).organization_id)
    return Resource(type=ResourceType(resource_type), id=str(obj.pk), project_id=cast("Dashboard", obj).team_id)


def check_object_access(
    user: User | SyntheticUser | AnonymousUser, obj: Model | ObjectAccessRef, action: Action
) -> bool:
    if isinstance(user, SyntheticUser):
        # API scopes and project membership gate service credentials; authz has no service principals yet.
        return True
    if not user.is_authenticated:
        return False
    return api.check(resource=resource_for_object(obj), action=action, subject=Subject(user_id=user.pk))


def object_access_level(user: User | SyntheticUser | AnonymousUser, obj: Model | ObjectAccessRef) -> str | None:
    if isinstance(user, SyntheticUser) or not user.is_authenticated:
        return None
    permissions = api.permissions(resource=resource_for_object(obj), subject=Subject(user_id=user.pk))
    if Action.VIEW not in permissions:
        return "none"
    if Action.EDIT not in permissions:
        return "viewer"
    return "manager" if Action.MANAGE_ACCESS in permissions else "editor"


def filter_dashboard_queryset(user: User | SyntheticUser | AnonymousUser, queryset: QuerySet[M]) -> QuerySet[M]:
    if isinstance(user, SyntheticUser):
        return queryset
    if not user.is_authenticated:
        return queryset.none()
    allowed = Q(pk__in=[])
    for team_id in queryset.order_by().values_list("team_id", flat=True).distinct():
        result = api.list_resources(
            resource=Resource(type=ResourceType.DASHBOARD, project_id=team_id),
            action=Action.VIEW,
            subject=Subject(user_id=user.pk),
        )
        if result.complete:
            allowed |= Q(team_id=team_id) & filter_q(result, id_field="pk", creator_field=None)
    return queryset.filter(allowed)


def check_dashboard_category_access(user: User, team: Team, action: Action, *, require_category: bool) -> bool:
    resource = Resource(type=ResourceType.DASHBOARD, project_id=team.pk)
    subject = Subject(user_id=user.pk)
    category_action = Action.CREATE if action in (Action.EDIT, Action.DELETE, Action.SHARE) else action
    if api.check(resource=resource, action=category_action, subject=subject):
        return True
    if require_category:
        return False
    result = api.list_resources(resource=resource, action=action, subject=subject)
    return result.complete and bool(result.ids)
