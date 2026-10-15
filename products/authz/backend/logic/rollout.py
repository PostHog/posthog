from collections import defaultdict
from collections.abc import Sequence
from typing import Literal
from uuid import UUID

import structlog

from posthog.models import OrganizationMembership
from posthog.ph_client import get_feature_flag_or_none

from ..facade.contracts import CheckRequest, Context, Resource, ResourceIds, Subject
from ..facade.enums import Action, ResourceType
from . import authorization, legacy_authorization, request_context

logger = structlog.get_logger(__name__)
ROLLOUT_FLAG = "authz-rebac"
RolloutMode = Literal["v1", "v1-shadow-log", "v2"]


V2_RESOURCES = frozenset({ResourceType.DASHBOARD, ResourceType.INSIGHT})
# The types the guest model covers. v1 has no guest concept, so guest checks on these never run a shadow.
GUEST_V2_RESOURCES = frozenset(
    {
        ResourceType.ORGANIZATION,
        ResourceType.PROJECT,
        ResourceType.DASHBOARD,
        ResourceType.INSIGHT,
        ResourceType.NOTEBOOK,
        ResourceType.SESSION_RECORDING,
    }
)


def organization_variant(organization_id: UUID) -> object:
    id = str(organization_id)
    return get_feature_flag_or_none(
        ROLLOUT_FLAG,
        id,
        groups={"organization": id},
        group_properties={"organization": {"id": id}},
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )


def guest_memberships(organization_ids: set[UUID], user_ids: set[int]) -> set[tuple[UUID, int]]:
    pairs = {(organization_id, user_id) for organization_id in organization_ids for user_id in user_ids}
    cached = request_context.guest_memberships.get()
    known = cached if cached is not None else {}
    missing = pairs - known.keys()
    if missing:
        guests = set(
            OrganizationMembership.objects.filter(
                organization_id__in={organization_id for organization_id, _ in missing},
                user_id__in={user_id for _, user_id in missing},
                level=OrganizationMembership.Level.GUEST,
            ).values_list("organization_id", "user_id")
        )
        known.update({pair: pair in guests for pair in missing})
    return {pair for pair in pairs if known[pair]}


def guest_mode(variant: object, resource_type: ResourceType) -> Literal["v1", "v2", "denied"]:
    """Route a guest's check. Guests act as members when the org is not on v2, and get no access to other types."""
    if variant != "v2":
        return "v1"
    return "v2" if resource_type in GUEST_V2_RESOURCES else "denied"


def mode(organization_id: UUID, resource_type: ResourceType) -> RolloutMode:
    if resource_type not in V2_RESOURCES:
        return "v1"
    return variant_mode(organization_variant(organization_id))


def variant_mode(variant: object) -> RolloutMode:
    if variant == "v2":
        return "v2"
    if variant == "v1-shadow-log":
        return "v1-shadow-log"
    return "v1"


def check(requests: Sequence[CheckRequest], context: Context | None) -> list[bool]:
    authorization.validate_context(context)
    organization_ids = [authorization.organization_id(request.resource) for request in requests]
    variants = {org_id: organization_variant(org_id) for org_id in dict.fromkeys(organization_ids)}
    # Guests act as members outside v2 organizations, so only those need the membership lookup.
    guests = guest_memberships(
        {org_id for org_id, variant in variants.items() if variant == "v2"},
        {request.subject.user_id for request in requests if request.subject is not None and request.subject.user_id},
    )
    grouped: dict[tuple[UUID, ResourceType, bool, bool], list[tuple[int, CheckRequest]]] = defaultdict(list)
    for index, (request, org_id) in enumerate(zip(requests, organization_ids, strict=True)):
        authorization.actor_key(request.subject)
        is_share_link = request.subject is not None and request.subject.share_link_id is not None
        is_guest = request.subject is not None and (org_id, request.subject.user_id) in guests
        grouped[(org_id, request.resource.type, is_share_link, is_guest)].append((index, request))
    decisions = [False] * len(requests)
    for (org_id, resource_type, is_share_link, is_guest), entries in grouped.items():
        batch = [request for _, request in entries]
        if is_guest:
            routed = guest_mode(variants[org_id], resource_type)
            if routed != "denied":
                engine = authorization if routed == "v2" else legacy_authorization
                for (index, _request), allowed in zip(entries, engine.check(batch, context), strict=True):
                    decisions[index] = allowed
            continue
        rollout_mode: RolloutMode = (
            "v2" if is_share_link else variant_mode(variants[org_id]) if resource_type in V2_RESOURCES else "v1"
        )
        primary = authorization if rollout_mode == "v2" else legacy_authorization
        results = primary.check(batch, context)
        comparison: list[bool] | None = None
        if rollout_mode != "v1" and not is_share_link:
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
            if rollout_mode == "v1" or is_share_link:
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
    is_share_link = subject is not None and subject.share_link_id is not None
    variant = organization_variant(org_id)
    if (
        subject is not None
        and subject.user_id is not None
        and variant == "v2"
        and guest_memberships({org_id}, {subject.user_id})
    ):
        routed = guest_mode(variant, resource.type)
        if routed == "denied":
            return ResourceIds(ids=frozenset(), complete=True)
        engine = authorization if routed == "v2" else legacy_authorization
        return engine.list_resources(resource, action, subject, context, limit)
    rollout_mode: RolloutMode = (
        "v2" if is_share_link else variant_mode(variant) if resource.type in V2_RESOURCES else "v1"
    )
    primary = authorization if rollout_mode == "v2" else legacy_authorization
    result = primary.list_resources(resource, action, subject, context, limit)
    if rollout_mode == "v1" or is_share_link:
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
