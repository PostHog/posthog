import json
from collections.abc import Mapping, Sequence
from functools import cache
from pathlib import Path
from uuid import UUID

from openfga_sdk.client.models import ClientCheckRequest, ClientListObjectsRequest
from openfga_sdk.sync import OpenFgaClient

from posthog.models import Team

from products.access_control.backend.facade.user_access_control import (
    ACCESS_CONTROL_RESOURCES,
    RESOURCE_INHERITANCE_MAP,
)
from products.dashboards.backend.facade.authorization import active_authorization_dashboard_ids

from ..client import Consistency, pooled_openfga_client
from ..facade.contracts import CheckRequest, Context, ObjectIds, Resource, Subject
from ..facade.enums import Action, Level, ResourceType
from . import request_context, sync_state

RESOURCE_CATEGORIES = {ResourceType(child): ResourceType(parent) for child, parent in RESOURCE_INHERITANCE_MAP.items()}


def ready_state(organization_id: UUID) -> bytes | None:
    state = sync_state.current_state(organization_id)
    return state if state is not None and state.startswith(b"ready:") else None


@cache
def model_relations() -> dict[str, frozenset[str]]:
    model = json.loads((Path(__file__).resolve().parents[2] / "generated" / "openfga_model.json").read_text())
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
        cached_projects = request_context.project_organizations.get() if projects is None else None
        if cached_projects is not None:
            if team_id not in cached_projects:
                cached_org_id = Team.objects.filter(id=team_id).values_list("organization_id", flat=True).first()
                if cached_org_id is not None:
                    cached_projects[team_id] = cached_org_id
            projects = cached_projects
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


def resource_category(resource_type: ResourceType) -> ResourceType:
    return RESOURCE_CATEGORIES.get(resource_type, resource_type)


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
    if resource.id is None:
        category = resource_category(resource.type)
        if category not in ACCESS_CONTROL_RESOURCES:
            raise NotImplementedError(f"OpenFGA synchronization does not yet support {resource.type}")
        if resource.project_id is None:
            raise ValueError(f"Provide a project id for {resource.type} authorization")
        return f"resource:{org_id}/{resource.project_id}/{category}"
    if resource.type not in (
        ResourceType.DASHBOARD,
        ResourceType.INSIGHT,
        ResourceType.NOTEBOOK,
        ResourceType.SESSION_RECORDING,
    ):
        raise NotImplementedError(f"OpenFGA synchronization does not yet support {resource.type}")
    if resource.project_id is None:
        raise ValueError(f"Provide a project id for {resource.type} authorization")
    if resource.type == ResourceType.NOTEBOOK:
        id = str(UUID(resource.id))
    elif resource.type == ResourceType.SESSION_RECORDING:
        if not resource.id or len(resource.id) > 200 or any(c.isspace() or c in "#:" for c in resource.id):
            raise ValueError("Provide a valid session recording id")
        id = resource.id
    else:
        if not resource.id.isdecimal() or int(resource.id) <= 0:
            raise ValueError(f"Provide the {resource.type}'s numeric id")
        id = str(int(resource.id))
    return f"{resource.type}:{org_id}/{resource.project_id}/{id}"


def actor_key(subject: Subject | None) -> str:
    if subject is None:
        raise ValueError("Pass an explicit subject until request-context authorization is wired")
    if subject.share_link_id is not None:
        if subject.share_link_id <= 0:
            raise ValueError("Provide a positive share link id")
        return f"share_link:{subject.share_link_id}"
    if subject.user_id is None:
        raise NotImplementedError("OpenFGA checks currently support user and share link subjects only")
    return f"user:{subject.user_id}"


def validate_context(context: Context | None) -> None:
    if context is not None and context != Context():
        raise NotImplementedError("Request-context overrides are not yet supported by this authorization model")


def action_relation(object: str, action: Action) -> str:
    relation = f"can_{action}"
    if relation not in model_relations().get(object.partition(":")[0], ()):
        raise ValueError(f"{action} is not supported for this resource")
    return relation


def check(
    requests: Sequence[CheckRequest], context: Context | None, *, consistency: Consistency = "HIGHER_CONSISTENCY"
) -> list[bool]:
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
    # Enforcement must observe revocations even when a previous revision populated the server caches.
    with pooled_openfga_client() as client:
        if client.get_store_id() is None:
            raise RuntimeError("Bootstrap the OpenFGA store before checking authorization")
        # SDK-side batching also works with OpenFGA versions without the BatchCheck endpoint.
        results = client.client_batch_check(checks, {"consistency": consistency})
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


def list_objects(
    resource: Resource,
    action: Action,
    subject: Subject | None,
    context: Context | None,
    limit: int | None,
    *,
    consistency: Consistency = "HIGHER_CONSISTENCY",
) -> ObjectIds:
    if action in (Action.VIEW, Action.QUERY):
        return _read_object_filter(resource, action, subject, context, limit, consistency=consistency)
    validate_context(context)
    if resource.id is not None or resource.type not in (ResourceType.DASHBOARD, ResourceType.INSIGHT):
        raise ValueError("List resources requires a supported resource type")
    if resource.project_id is None:
        raise ValueError("List resources requires a project")
    if limit is not None and limit < 1:
        raise ValueError("Resource limit must be positive")
    org_id = organization_id(resource)
    prefix = f"{resource.type}:{org_id}/{resource.project_id}/"
    relation = action_relation(f"{prefix}0", action)
    user = actor_key(subject)
    revision = ready_state(org_id)
    if revision is None:
        return ObjectIds(ids=frozenset(), complete=False)
    with pooled_openfga_client() as client:
        if client.get_store_id() is None:
            raise RuntimeError("Bootstrap the OpenFGA store before listing authorized resources")
        ids: set[str] = set()
        stream = client.streamed_list_objects(
            ClientListObjectsRequest(user=user, type=str(resource.type), relation=relation),
            {"consistency": consistency},
        )
        try:
            for result in stream:
                if result.object.startswith(prefix):
                    ids.add(result.object.removeprefix(prefix))
                    if limit is not None and len(ids) > limit:
                        if resource.type == ResourceType.DASHBOARD:
                            active_ids = active_authorization_dashboard_ids(resource.project_id, ids)
                        else:
                            from products.product_analytics.backend.facade.api import (  # noqa: PLC0415 -- keep product analytics models off the authorization import path
                                active_authorization_insight_ids,
                            )

                            active_ids = active_authorization_insight_ids(resource.project_id, ids)
                        ids = set(active_ids)
                        if len(ids) > limit:
                            return ObjectIds(ids=frozenset(), complete=False)
        finally:
            stream.close()
        if resource.type == ResourceType.DASHBOARD:
            active_ids = active_authorization_dashboard_ids(resource.project_id, ids)
        else:
            from products.product_analytics.backend.facade.api import (  # noqa: PLC0415 -- keep product analytics models off the authorization import path
                active_authorization_insight_ids,
            )

            active_ids = active_authorization_insight_ids(resource.project_id, ids)
        if limit is not None and len(active_ids) > limit:
            return ObjectIds(ids=frozenset(), complete=False)
        if ready_state(org_id) != revision:
            return ObjectIds(ids=frozenset(), complete=False)
        return ObjectIds(ids=active_ids, complete=True)


MAX_IDS = 1000


def _read_object_filter(
    resource: Resource,
    action: Action,
    subject: Subject | None,
    context: Context | None,
    limit: int | None,
    *,
    consistency: Consistency = "HIGHER_CONSISTENCY",
) -> ObjectIds:
    """The resources that differ from the project default for this subject.

    The lists stay small because the model marks the objects a user has a rule on (`has_rule`). With
    access at the category, only those objects can be denied, so they are listed and checked, and the
    result excludes the denied ones. Without it, only explicit grants and the user's own objects are
    visible, so the permission lists just those.
    """
    validate_context(context)
    if resource.id is not None or resource.project_id is None:
        raise ValueError("List resources requires a resource category scoped to a project")
    if limit is not None and limit < 1:
        raise ValueError("Resource limit must be positive")
    cap = limit if limit is not None else MAX_IDS
    org_id = organization_id(resource)
    type_name = resource.type.value
    prefix = f"{type_name}:{org_id}/{resource.project_id}/"
    # Querying dashboard/insight system rows uses their view permission; warehouse data has can_query.
    permission = (
        Action.VIEW
        if action == Action.QUERY and resource.type in (ResourceType.DASHBOARD, ResourceType.INSIGHT)
        else action
    )
    relation = action_relation(f"{prefix}0", permission)
    category_key = object_key(resource, org_id=org_id)
    user = actor_key(subject)
    capped = ObjectIds(ids=frozenset(), complete=False)

    def build(ids: frozenset[str], *, excluded: bool) -> ObjectIds:
        # OpenFGA already includes creators after applying project membership and action-specific gates.
        return ObjectIds(ids=ids, complete=True, excluded=excluded)

    revision = ready_state(org_id)
    if revision is None:
        return capped
    with pooled_openfga_client() as client:
        if client.get_store_id() is None:
            raise RuntimeError("Bootstrap the OpenFGA store before listing authorized resources")
        reader = _Reader(client, user, type_name, prefix, cap, consistency, resource.project_id)
        if permission == Action.VIEW and reader.allowed(category_key, "can_view"):
            with_rule = reader.list_ids("has_rule")
            if with_rule is None:
                return capped
            result = build(reader.denied_among(with_rule, relation), excluded=True)
        else:
            granted = reader.list_ids(relation)
            if granted is None:
                return capped
            result = build(granted, excluded=False)
    if ready_state(org_id) != revision:
        # A sync landed while we read, so the answer may mix two generations of tuples.
        return capped
    return result


class _Reader:
    """The three OpenFGA calls a resource list is made of, for one user and one object type."""

    def __init__(
        self,
        client: OpenFgaClient,
        user: str,
        type_name: str,
        prefix: str,
        cap: int,
        consistency: Consistency,
        project_id: int,
    ) -> None:
        self.client = client
        self.user = user
        self.project_id = project_id
        self.type_name = type_name
        self.prefix = prefix
        self.cap = cap
        self.options: dict[str, int | str | dict[str, int | str]] = {"consistency": consistency}

    def allowed(self, object_key: str, relation: str) -> bool:
        request = ClientCheckRequest(user=self.user, relation=relation, object=object_key)
        return self.client.check(request, self.options).allowed is True

    def denied_among(self, ids: frozenset[str], relation: str) -> frozenset[str]:
        if not ids:
            return frozenset()
        ordered = sorted(ids)
        requests = [
            ClientCheckRequest(user=self.user, relation=relation, object=f"{self.prefix}{id}") for id in ordered
        ]
        results = self.client.client_batch_check(requests, self.options)
        denied: set[str] = set()
        for id, result in zip(ordered, results, strict=True):
            if result.error is not None:
                raise result.error
            if result.allowed is not True:
                denied.add(id)
        return frozenset(denied)

    def active_ids(self, ids: set[str]) -> frozenset[str]:
        if not ids:
            return frozenset()
        if self.type_name == ResourceType.DASHBOARD:
            return active_authorization_dashboard_ids(self.project_id, ids)
        if self.type_name == ResourceType.INSIGHT:
            from products.product_analytics.backend.facade.api import (  # noqa: PLC0415 -- keep product analytics models off the authorization import path
                active_authorization_insight_ids,
            )

            return active_authorization_insight_ids(self.project_id, ids)
        return frozenset(ids)

    def list_ids(self, relation: str) -> frozenset[str] | None:
        """Active IDs holding `relation` in this project, or None past the cap."""
        ids: set[str] = set()
        pending: set[str] = set()
        request = ClientListObjectsRequest(user=self.user, relation=relation, type=self.type_name)
        stream = self.client.streamed_list_objects(request, self.options)
        try:
            for result in stream:
                if result.object.startswith(self.prefix):
                    pending.add(result.object.removeprefix(self.prefix))
                    # Sync retains deleted objects; only active IDs consume the result cap.
                    if len(pending) >= min(100, self.cap + 1):
                        ids.update(self.active_ids(pending))
                        pending.clear()
                        if len(ids) > self.cap:
                            return None
            ids.update(self.active_ids(pending))
            return None if len(ids) > self.cap else frozenset(ids)
        finally:
            stream.close()


def query_relation(
    resource: Resource, subject: Subject, level: Level, *, consistency: Consistency = "HIGHER_CONSISTENCY"
) -> bool:
    object = object_key(resource)
    if level not in model_relations().get(object.partition(":")[0], ()):
        raise ValueError("This level is not a queryable relation on the resource")
    user = actor_key(subject)
    org_id = organization_id(resource)
    revision = ready_state(org_id)
    if revision is None:
        return False
    with pooled_openfga_client() as client:
        allowed = (
            client.check(
                ClientCheckRequest(user=user, object=object, relation=str(level)), {"consistency": consistency}
            ).allowed
            is True
        )
        return allowed and ready_state(org_id) == revision
