from typing import TYPE_CHECKING, TypeVar, cast

from django.apps import apps
from django.contrib.auth.models import AnonymousUser
from django.db.models import Model, Q, QuerySet

from posthog.models import Team, User
from posthog.models.access_filter import filter_q
from posthog.shared_link_user import SharedLinkUser
from posthog.synthetic_user import SyntheticUser

from products.access_control.backend.facade.contracts import ObjectAccessRef
from products.access_control.backend.facade.user_access_control import UserAccessControl, model_to_resource
from products.authz.backend.facade import api
from products.authz.backend.facade.contracts import Resource, Subject
from products.authz.backend.facade.enums import Action, ResourceType

if TYPE_CHECKING:
    from posthog.models import SessionRecording

    from products.dashboards.backend.models.dashboard import Dashboard

M = TypeVar("M", bound=Model)
RESOURCE_ACTIONS = {"viewer": Action.VIEW, "editor": Action.EDIT, "manager": Action.MANAGE_ACCESS}


def resource_list_cache_key(access: UserAccessControl, scopes: set[str] | None) -> dict[str, object]:
    assert access.team is not None
    resources = [resource_type for resource_type in ResourceType if scopes is None or resource_type.value in scopes]
    filters: dict[str, object] = {}
    for resource_type in resources:
        if resource_type in (ResourceType.ORGANIZATION, ResourceType.PROJECT, ResourceType.ROLE):
            continue
        result = api.list_objects(
            resource=Resource(type=resource_type, project_id=access.team.id),
            action=Action.VIEW,
            subject=Subject(user_id=access.user.pk),
            creator_exempt=True,
            user_access_control=access,
        )
        if result.complete and not result.restricts:
            continue
        filters[resource_type.value] = {
            "ids": sorted(result.ids),
            "excluded": result.excluded,
            "complete": result.complete,
            "creator": access.user.pk if result.creator_exempt and result.restricts else None,
        }
    return filters


def resource_for_object(obj: Model | ObjectAccessRef) -> Resource:
    if isinstance(obj, ObjectAccessRef):
        return Resource(type=ResourceType(obj.resource), id=obj.id, project_id=obj.team_id)
    resource_type = model_to_resource(obj)
    if resource_type is None:
        raise ValueError("Object has no authorization resource type")
    if resource_type == "project":
        return Resource(type=ResourceType.PROJECT, id=str(obj.pk), organization_id=cast(Team, obj).organization_id)
    id = str(cast("SessionRecording", obj).session_id) if resource_type == "session_recording" else str(obj.pk)
    return Resource(type=ResourceType(resource_type), id=id, project_id=cast("Dashboard", obj).team_id)


def subject_for_user(user: User | SyntheticUser | AnonymousUser) -> Subject | None:
    if isinstance(user, SharedLinkUser):
        id = user.sharing_configuration.pk
        return Subject(share_link_id=id) if id is not None else None
    return Subject(user_id=user.pk) if user.is_authenticated and not isinstance(user, SyntheticUser) else None


def check_object_access(
    user: User | SyntheticUser | AnonymousUser, obj: Model | ObjectAccessRef, action: Action
) -> bool:
    if isinstance(user, SyntheticUser):
        # API scopes and project membership gate service credentials; authz has no service principals yet.
        return True
    subject = subject_for_user(user)
    if subject is None:
        return False
    return api.check(resource=resource_for_object(obj), action=action, subject=subject)


def check_shared_link_access(user: SharedLinkUser) -> bool:
    targets = [
        target
        for field in ("dashboard", "insight", "notebook", "recording")
        if (target := getattr(user.sharing_configuration, field)) is not None
    ]
    return bool(targets) and all(check_object_access(user, target, Action.VIEW) for target in targets)


def object_access_level(user: User | SyntheticUser | AnonymousUser, obj: Model | ObjectAccessRef) -> str | None:
    if isinstance(user, SyntheticUser) or not user.is_authenticated:
        return None
    permissions = api.permissions(resource=resource_for_object(obj), subject=Subject(user_id=user.pk))
    if Action.VIEW not in permissions:
        return "none"
    if Action.EDIT not in permissions:
        return "viewer"
    return "manager" if Action.MANAGE_ACCESS in permissions else "editor"


def filter_resource_queryset(
    user: User | SyntheticUser | AnonymousUser, queryset: QuerySet[M], resource_type: ResourceType
) -> QuerySet[M]:
    if isinstance(user, SyntheticUser):
        return queryset
    subject = subject_for_user(user)
    if subject is None:
        return queryset.none()
    allowed = Q(pk__in=[])
    for team_id in queryset.order_by().values_list("team_id", flat=True).distinct():
        result = api.list_objects(
            resource=Resource(type=resource_type, project_id=team_id),
            action=Action.VIEW,
            subject=subject,
            creator_exempt=hasattr(queryset.model, "created_by"),
        )
        if result.complete:
            allowed |= Q(team_id=team_id) & filter_q(result, id_field="pk", subject_user_id=user.pk)
    return queryset.filter(allowed)


def filter_dashboard_queryset(user: User | SyntheticUser | AnonymousUser, queryset: QuerySet[M]) -> QuerySet[M]:
    return filter_resource_queryset(user, queryset, ResourceType.DASHBOARD)


def check_resource_category_access(
    user: User,
    team: Team,
    resource_type: ResourceType,
    action: Action,
    *,
    require_category: bool,
) -> bool:
    subject = Subject(user_id=user.pk)
    category_action = Action.CREATE if action in (Action.EDIT, Action.DELETE, Action.SHARE) else action
    resource = Resource(type=resource_type, project_id=team.pk)
    if api.check(resource=resource, action=category_action, subject=subject):
        return True
    if require_category:
        return False
    if action == Action.VIEW:
        model_name = {
            ResourceType.DASHBOARD: "dashboards.Dashboard",
            ResourceType.INSIGHT: "product_analytics.Insight",
        }[resource_type]
        model = apps.get_model(model_name)
        return filter_resource_queryset(user, model.objects.filter(team_id=team.pk), resource_type).exists()
    result = api.list_objects(resource=resource, action=action, subject=subject)
    return result.complete and bool(result.ids or result.excluded)


def check_dashboard_category_access(user: User, team: Team, action: Action, *, require_category: bool) -> bool:
    return check_resource_category_access(user, team, ResourceType.DASHBOARD, action, require_category=require_category)
