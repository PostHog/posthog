from collections import defaultdict
from collections.abc import Sequence
from typing import Literal
from uuid import UUID

import structlog

from posthog.ph_client import get_feature_flag_or_none

from products.access_control.backend.facade.user_access_control import UserAccessControl

from ..facade.contracts import CheckRequest, Context, Resource, ResourceIds, Subject
from ..facade.enums import Action, ResourceType
from . import authorization, legacy_authorization

logger = structlog.get_logger(__name__)
ROLLOUT_FLAG = "authz-rebac"
RolloutMode = Literal["v1", "v1-shadow-log", "v2"]


V2_RESOURCES = frozenset({ResourceType.DASHBOARD})


def mode(organization_id: UUID, resource_type: ResourceType) -> RolloutMode:
    if resource_type not in V2_RESOURCES:
        return "v1"
    id = str(organization_id)
    variant = get_feature_flag_or_none(
        ROLLOUT_FLAG,
        id,
        groups={"organization": id},
        group_properties={"organization": {"id": id}},
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )
    if variant == "v2":
        return "v2"
    if variant == "v1-shadow-log":
        return "v1-shadow-log"
    return "v1"


def check(requests: Sequence[CheckRequest], context: Context | None) -> list[bool]:
    authorization.validate_context(context)
    grouped: dict[tuple[UUID, ResourceType], list[tuple[int, CheckRequest]]] = defaultdict(list)
    for index, request in enumerate(requests):
        authorization.actor_key(request.subject)
        grouped[(authorization.organization_id(request.resource), request.resource.type)].append((index, request))
    decisions = [False] * len(requests)
    for (org_id, resource_type), entries in grouped.items():
        rollout_mode = mode(org_id, resource_type)
        batch = [request for _, request in entries]
        primary = authorization if rollout_mode == "v2" else legacy_authorization
        results = primary.check(batch, context)
        comparison: list[bool] | None = None
        if rollout_mode != "v1":
            secondary = legacy_authorization if rollout_mode == "v2" else authorization
            try:
                comparison = secondary.check(batch, context)
                if len(comparison) != len(results):
                    raise RuntimeError("Shadow authorization returned an incomplete batch")
            except Exception as error:
                comparison = None
                logger.warning(
                    "authz_shadow_check_failed",
                    mode=rollout_mode,
                    organization_id=str(org_id),
                    error_type=type(error).__name__,
                )
        for offset, ((index, request), allowed) in enumerate(zip(entries, results, strict=True)):
            decisions[index] = allowed
            if rollout_mode == "v1":
                continue
            shadow = comparison[offset] if comparison is not None else None
            logger.info(
                "authz_decision_comparison",
                mode=rollout_mode,
                organization_id=str(org_id),
                project_id=request.resource.project_id,
                resource_type=str(request.resource.type),
                resource_id=request.resource.id,
                user_id=request.subject.user_id if request.subject is not None else None,
                action=str(request.action),
                v1_allowed=shadow if rollout_mode == "v2" else allowed,
                v2_allowed=allowed if rollout_mode == "v2" else shadow,
                matches=allowed == shadow if shadow is not None else None,
            )
    return decisions


def permissions(resource: Resource, subject: Subject | None, context: Context | None) -> frozenset[Action]:
    object = authorization.object_key(resource)
    actions = [
        action for action in Action if f"can_{action}" in authorization.model_relations()[object.partition(":")[0]]
    ]
    results = check([CheckRequest(resource=resource, action=action, subject=subject) for action in actions], context)
    return frozenset(action for action, allowed in zip(actions, results, strict=True) if allowed)


def list_resources(
    resource: Resource,
    action: Action,
    subject: Subject | None,
    context: Context | None,
    limit: int | None,
    creator_exempt: bool = False,
    user_access_control: UserAccessControl | None = None,
) -> ResourceIds:
    authorization.validate_context(context)
    authorization.actor_key(subject)
    org_id = _organization_id(resource, user_access_control)
    rollout_mode = mode(org_id, resource.type)
    primary = authorization if rollout_mode == "v2" else legacy_authorization
    result = primary.list_resources(resource, action, subject, context, limit, creator_exempt, user_access_control)
    if rollout_mode == "v1":
        return result
    secondary = legacy_authorization if rollout_mode == "v2" else authorization
    comparison: ResourceIds | None = None
    try:
        comparison = secondary.list_resources(
            resource, action, subject, context, limit, creator_exempt, user_access_control
        )
    except Exception as error:
        logger.warning(
            "authz_shadow_list_failed", mode=rollout_mode, organization_id=str(org_id), error_type=type(error).__name__
        )
    v1, v2 = (comparison, result) if rollout_mode == "v2" else (result, comparison)
    logger.info(
        "authz_resource_list_comparison",
        mode=rollout_mode,
        organization_id=str(org_id),
        project_id=resource.project_id,
        resource_type=str(resource.type),
        user_id=subject.user_id if subject is not None else None,
        action=str(action),
        v1_count=len(v1.ids) if v1 is not None else None,
        v2_count=len(v2.ids) if v2 is not None else None,
        v1_complete=v1.complete if v1 is not None else None,
        v2_complete=v2.complete if v2 is not None else None,
        matches=result == comparison if comparison is not None else None,
    )
    return result


def _organization_id(resource: Resource, user_access_control: UserAccessControl | None) -> UUID:
    """The resource's organization, from the caller's preload when it names the project, else looked up."""
    projects = None
    if user_access_control is not None and user_access_control.team is not None:
        projects = {user_access_control.team.id: user_access_control.team.organization_id}
    return authorization.organization_id(resource, projects=projects)
