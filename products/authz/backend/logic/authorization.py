import json
from collections.abc import Mapping, Sequence
from functools import cache
from pathlib import Path
from uuid import UUID

from openfga_sdk.client.models import ClientCheckRequest, ClientListObjectsRequest

from posthog.models import Team

from ..client import get_openfga_client
from ..facade.contracts import CheckRequest, Context, Resource, ResourceIds, Subject
from ..facade.enums import Action, Level, ResourceType
from . import sync_state


def ready_state(organization_id: UUID) -> bytes | None:
    state = sync_state.current_state(organization_id)
    return state if state is not None and state.startswith(b"ready:") else None


@cache
def model_relations() -> dict[str, frozenset[str]]:
    model = json.loads((Path(__file__).resolve().parents[2] / "openfga_model.json").read_text())
    return {definition["type"]: frozenset(definition.get("relations", {})) for definition in model["type_definitions"]}


def project_id(resource: Resource) -> int | None:
    id = resource.project_id
    if resource.type == ResourceType.PROJECT and resource.id is not None:
        explicit_id = int(resource.id)
        if id is not None and id != explicit_id:
            raise ValueError("Project id does not match the resource scope")
        id = explicit_id
    if id is not None and id <= 0:
        raise ValueError("Provide a positive project id")
    return id


def organization_id(resource: Resource, *, projects: Mapping[int, UUID] | None = None) -> UUID:
    if resource.type == ResourceType.ORGANIZATION:
        org_id = UUID(resource.id) if resource.id is not None else resource.organization_id
        if org_id is None or (resource.organization_id is not None and resource.organization_id != org_id):
            raise ValueError("Provide a matching organization id")
        return org_id
    team_id = project_id(resource)
    if team_id is not None:
        org_id = (
            projects.get(team_id)
            if projects is not None
            else Team.objects.filter(id=team_id).values_list("organization_id", flat=True).first()
        )
        if org_id is None or (resource.organization_id is not None and resource.organization_id != org_id):
            raise ValueError("Project does not belong to the resource's organization")
        return org_id
    if resource.organization_id is None:
        raise ValueError("Provide the resource's project or organization id")
    return resource.organization_id


def object_key(resource: Resource, *, org_id: UUID | None = None) -> str:
    org_id = org_id or organization_id(resource)
    if resource.type == ResourceType.ORGANIZATION:
        return f"organization:{org_id}"
    if resource.type == ResourceType.PROJECT:
        project_id = resource.project_id or (int(resource.id) if resource.id is not None else None)
        if project_id is None:
            raise ValueError("Provide a project id")
        return f"project:{org_id}/{project_id}"
    if resource.type == ResourceType.ROLE:
        if resource.id is None:
            raise ValueError("Provide a role id")
        return f"role:{org_id}/{UUID(resource.id)}"
    if resource.type != ResourceType.DASHBOARD:
        raise NotImplementedError(f"OpenFGA synchronization does not yet support {resource.type}")
    if resource.project_id is None:
        raise ValueError("Provide a project id for dashboard authorization")
    if resource.id is None:
        return f"resource_category:{org_id}/{resource.project_id}/dashboard"
    if not resource.id.isdecimal() or int(resource.id) <= 0:
        raise ValueError("Provide the dashboard's numeric id")
    return f"dashboard:{org_id}/{resource.project_id}/{int(resource.id)}"


def actor_key(subject: Subject | None) -> str:
    if subject is None:
        raise ValueError("Pass an explicit subject until request-context authorization is wired")
    if subject.user_id is None:
        raise NotImplementedError("OpenFGA checks currently support user subjects only")
    return f"user:{subject.user_id}"


def validate_context(context: Context | None) -> None:
    if context is not None and context != Context():
        raise NotImplementedError("Request-context overrides are not yet supported by this authorization model")


def action_relation(object: str, action: Action) -> str:
    relation = f"can_{action}"
    if relation not in model_relations().get(object.partition(":")[0], ()):
        raise ValueError(f"{action} is not supported for this resource")
    return relation


def check(requests: Sequence[CheckRequest], context: Context | None) -> list[bool]:
    validate_context(context)
    team_ids = {
        id
        for request in requests
        if request.resource.type != ResourceType.ORGANIZATION and (id := project_id(request.resource)) is not None
    }
    projects = dict(Team.objects.filter(id__in=team_ids).values_list("id", "organization_id")) if team_ids else {}
    organizations = [organization_id(request.resource, projects=projects) for request in requests]
    checks: list[ClientCheckRequest] = []
    for request, org_id in zip(requests, organizations, strict=True):
        object = object_key(request.resource, org_id=org_id)
        checks.append(
            ClientCheckRequest(
                user=actor_key(request.subject), object=object, relation=action_relation(object, request.action)
            )
        )
    if not checks:
        return []
    revisions = {id: ready_state(id) for id in set(organizations)}
    if not any(revisions.values()):
        return [False] * len(checks)
    client = get_openfga_client()
    try:
        if client.get_store_id() is None:
            raise RuntimeError("Bootstrap the OpenFGA store before checking authorization")
        # SDK-side batching also works with OpenFGA versions without the BatchCheck endpoint.
        results = client.client_batch_check(checks, {"consistency": "HIGHER_CONSISTENCY"})
        decisions = []
        for result in results:
            if result.error is not None:
                raise result.error
            if result.allowed is None:
                raise RuntimeError("OpenFGA returned no authorization decision")
            decisions.append(result.allowed)
        current_revisions = {id: ready_state(id) for id in revisions}
        return [
            allowed and revisions[id] is not None and revisions[id] == current_revisions[id]
            for id, allowed in zip(organizations, decisions, strict=True)
        ]
    finally:
        client.close()


def permissions(resource: Resource, subject: Subject | None, context: Context | None) -> frozenset[Action]:
    object = object_key(resource)
    actions = [action for action in Action if f"can_{action}" in model_relations()[object.partition(":")[0]]]
    results = check([CheckRequest(resource=resource, action=action, subject=subject) for action in actions], context)
    return frozenset(action for action, allowed in zip(actions, results, strict=True) if allowed)


def list_resources(
    resource: Resource, action: Action, subject: Subject | None, context: Context | None, limit: int | None
) -> ResourceIds:
    validate_context(context)
    if resource.id is not None or resource.type != ResourceType.DASHBOARD or resource.project_id is None:
        raise ValueError("List resources requires a dashboard category scoped to a project")
    if limit is not None and limit < 1:
        raise ValueError("Resource limit must be positive")
    org_id = organization_id(resource)
    prefix = f"dashboard:{org_id}/{resource.project_id}/"
    relation = action_relation(f"{prefix}0", action)
    user = actor_key(subject)
    revision = ready_state(org_id)
    if revision is None:
        return ResourceIds(ids=frozenset(), complete=False)
    client = get_openfga_client()
    try:
        if client.get_store_id() is None:
            raise RuntimeError("Bootstrap the OpenFGA store before listing authorized resources")
        ids: set[str] = set()
        stream = client.streamed_list_objects(
            ClientListObjectsRequest(user=user, type="dashboard", relation=relation),
            {"consistency": "HIGHER_CONSISTENCY"},
        )
        try:
            for result in stream:
                if result.object.startswith(prefix):
                    ids.add(result.object.removeprefix(prefix))
                    if limit is not None and len(ids) > limit:
                        return ResourceIds(ids=frozenset(), complete=False)
        finally:
            stream.close()
        if ready_state(org_id) != revision:
            return ResourceIds(ids=frozenset(), complete=False)
        return ResourceIds(ids=frozenset(ids), complete=True)
    finally:
        client.close()


def query_relation(resource: Resource, subject: Subject, level: Level) -> bool:
    object = object_key(resource)
    if level not in model_relations().get(object.partition(":")[0], ()):
        raise ValueError("This level is not a queryable relation on the resource")
    user = actor_key(subject)
    org_id = organization_id(resource)
    revision = ready_state(org_id)
    if revision is None:
        return False
    client = get_openfga_client()
    try:
        allowed = (
            client.check(
                ClientCheckRequest(user=user, object=object, relation=str(level)), {"consistency": "HIGHER_CONSISTENCY"}
            ).allowed
            is True
        )
        return allowed and ready_state(org_id) == revision
    finally:
        client.close()
