from collections import defaultdict
from collections.abc import Sequence
from typing import Literal
from uuid import UUID

import structlog

from posthog.models import Team
from posthog.ph_client import get_feature_flag_or_none

from products.access_control.backend.facade.user_access_control import UserAccessControl

from ..facade.contracts import AccessFilter, CheckRequest, Context, Resource, ResourceIds, Subject
from ..facade.enums import Action
from . import (
    authorization,
    filters as filters_logic,
    legacy_authorization,
    legacy_filters,
)

logger = structlog.get_logger(__name__)
ROLLOUT_FLAG = "authz-rebac"
RolloutMode = Literal["v1", "v1-shadow-log", "v2"]


def mode(organization_id: UUID) -> RolloutMode:
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
    grouped: dict[UUID, list[tuple[int, CheckRequest]]] = defaultdict(list)
    for index, request in enumerate(requests):
        authorization.actor_key(request.subject)
        grouped[authorization.organization_id(request.resource)].append((index, request))
    decisions = [False] * len(requests)
    for org_id, entries in grouped.items():
        rollout_mode = mode(org_id)
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
    resource: Resource, action: Action, subject: Subject | None, context: Context | None, limit: int | None
) -> ResourceIds:
    authorization.validate_context(context)
    authorization.actor_key(subject)
    org_id = authorization.organization_id(resource)
    rollout_mode = mode(org_id)
    primary = authorization if rollout_mode == "v2" else legacy_authorization
    result = primary.list_resources(resource, action, subject, context, limit)
    if rollout_mode == "v1":
        return result
    secondary = legacy_authorization if rollout_mode == "v2" else authorization
    comparison: ResourceIds | None = None
    try:
        comparison = secondary.list_resources(resource, action, subject, context, limit)
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


def filters(
    resources: Sequence[Resource],
    action: Action,
    subject: Subject | None,
    context: Context | None,
    creator_exempt: bool,
    user_access_control: UserAccessControl | None = None,
) -> list[AccessFilter]:
    authorization.validate_context(context)
    authorization.actor_key(subject)
    # One lookup for every project, and none when the caller's preload already names it.
    projects: dict[int, UUID] = {}
    if user_access_control is not None and user_access_control.team is not None:
        projects[user_access_control.team.id] = user_access_control.team.organization_id
    unknown = {pid for pid in (authorization.project_id(r) for r in resources) if pid is not None} - set(projects)
    if unknown:
        projects.update(Team.objects.filter(id__in=unknown).values_list("id", "organization_id"))
    grouped: dict[UUID, list[tuple[int, Resource]]] = defaultdict(list)
    for index, resource in enumerate(resources):
        grouped[authorization.organization_id(resource, projects=projects)].append((index, resource))
    results: list[AccessFilter | None] = [None] * len(resources)
    for org_id, entries in grouped.items():
        rollout_mode = mode(org_id)
        # The OpenFGA model covers some resource types. The legacy rules cover all of them.
        modelled = [(index, resource) for index, resource in entries if resource.type.value in model_types()]
        legacy = [(index, resource) for index, resource in entries if resource.type.value not in model_types()]
        primary_v2 = rollout_mode == "v2"
        for batch, use_v2 in ((modelled, primary_v2), (legacy, False)):
            if not batch:
                continue
            batch_resources = [resource for _, resource in batch]
            derived = (
                filters_logic.filters(batch_resources, action, subject, creator_exempt)
                if use_v2
                else legacy_filters.filters(batch_resources, action, subject, creator_exempt, user_access_control)
            )
            for (index, _), result in zip(batch, derived, strict=True):
                results[index] = result
        if rollout_mode == "v1" or not modelled:
            continue
        _log_shadow_filters(org_id, rollout_mode, modelled, results, action, subject, creator_exempt)
    return [result for result in results if result is not None]


def _log_shadow_filters(
    org_id: UUID,
    rollout_mode: RolloutMode,
    entries: list[tuple[int, Resource]],
    results: list[AccessFilter | None],
    action: Action,
    subject: Subject | None,
    creator_exempt: bool,
) -> None:
    secondary = legacy_filters if rollout_mode == "v2" else filters_logic
    comparison: list[AccessFilter] | None = None
    try:
        comparison = secondary.filters([resource for _, resource in entries], action, subject, creator_exempt)
    except Exception as error:
        logger.warning(
            "authz_shadow_filter_failed",
            mode=rollout_mode,
            organization_id=str(org_id),
            error_type=type(error).__name__,
        )
    for offset, (index, resource) in enumerate(entries):
        result = results[index]
        shadow = comparison[offset] if comparison is not None else None
        v1, v2 = (shadow, result) if rollout_mode == "v2" else (result, shadow)
        logger.info(
            "authz_filter_comparison",
            mode=rollout_mode,
            organization_id=str(org_id),
            project_id=resource.project_id,
            resource_type=str(resource.type),
            user_id=subject.user_id if subject is not None else None,
            action=str(action),
            v1_kind=str(v1.kind) if v1 is not None else None,
            v2_kind=str(v2.kind) if v2 is not None else None,
            matches=result == shadow if shadow is not None else None,
        )


def model_types() -> frozenset[str]:
    return frozenset(authorization.model_relations())
