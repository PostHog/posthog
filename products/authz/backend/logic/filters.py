"""Derive an `AccessFilter` from the OpenFGA graph.

Same inputs and same outcome as `legacy_filters.filters`, so the rollout can run either one
and the enforcement adapters never know which.

The lists stay small because the model marks the objects a user has a rule on (`has_rule`). With
resource-level access, only those objects can be denied, so they are listed and checked (EXCEPT).
Without it, only explicit grants and the user's own objects are visible, so the permission lists
just those (ONLY). Listing every visible object, which `list_resources` does, scales with the project.
"""

from collections.abc import Sequence

from openfga_sdk.client.models import ClientCheckRequest, ClientListObjectsRequest
from openfga_sdk.sync import OpenFgaClient

from ..client import get_openfga_client
from ..facade.contracts import AccessFilter, Resource, Subject
from ..facade.enums import Action, FilterKind
from . import authorization

# Above this many ids the filter is not worth inlining into a query, so the subject fails closed.
MAX_IDS = 1000

CONSISTENCY: dict[str, int | str | dict[str, int | str]] = {"consistency": "HIGHER_CONSISTENCY"}

# Listing and querying rows gate on the same permission as viewing one row.
READ_ACTIONS = {Action.LIST: Action.VIEW, Action.QUERY: Action.VIEW}


def filters(
    resources: Sequence[Resource], action: Action, subject: Subject | None, creator_exempt: bool
) -> list[AccessFilter]:
    """One filter per resource, in order, over one client connection."""
    client = get_openfga_client()
    try:
        return [_filter(client, resource, action, subject, creator_exempt) for resource in resources]
    finally:
        client.close()


def _filter(
    client: OpenFgaClient, resource: Resource, action: Action, subject: Subject | None, creator_exempt: bool
) -> AccessFilter:
    user = authorization.actor_key(subject)
    project_id = authorization.project_id(resource)
    if project_id is None:
        raise ValueError("A filter is scoped to a project; set resource.project_id.")
    category = Resource(type=resource.type, project_id=project_id)
    org_id = authorization.organization_id(category)
    category_key = authorization.object_key(category, org_id=org_id)
    relation = authorization.action_relation(f"{resource.type.value}:0", READ_ACTIONS.get(action, action))
    object_prefix = f"{resource.type.value}:{org_id}/{project_id}/"

    def build(kind: FilterKind, ids: frozenset[str] = frozenset(), *, complete: bool = True) -> AccessFilter:
        return AccessFilter(
            resource_type=resource.type,
            action=action,
            kind=kind,
            ids=ids,
            creator_exempt=creator_exempt and kind != FilterKind.ALL,
            complete=complete,
        )

    revision = authorization.ready_state(org_id)
    if revision is None:
        # The graph for this organization is not synchronized, so no answer is trustworthy.
        return build(FilterKind.NONE, complete=False)

    engine = _Engine(client, user, resource.type.value, object_prefix)
    if engine.allowed(f"organization:{org_id}", "admin"):
        result = build(FilterKind.ALL)
    elif engine.allowed(category_key, relation):
        with_rule = engine.list_ids("has_rule")
        if with_rule is None:
            return build(FilterKind.NONE, complete=False)
        denied = engine.denied_among(with_rule, relation)
        result = build(FilterKind.EXCEPT, denied) if denied else build(FilterKind.ALL)
    else:
        granted = engine.list_ids(relation)
        if granted is None:
            return build(FilterKind.NONE, complete=False)
        result = build(FilterKind.ONLY, granted) if granted else build(FilterKind.NONE)

    if authorization.ready_state(org_id) != revision:
        # A sync landed while we read, so the answer may mix two generations of tuples.
        return build(FilterKind.NONE, complete=False)
    return result


class _Engine:
    """The three OpenFGA calls a filter is made of, for one user and one object type."""

    def __init__(self, client: OpenFgaClient, user: str, type_name: str, object_prefix: str) -> None:
        self.client = client
        self.user = user
        self.type_name = type_name
        self.object_prefix = object_prefix

    def allowed(self, object_key: str, relation: str) -> bool:
        request = ClientCheckRequest(user=self.user, relation=relation, object=object_key)
        return self.client.check(request, CONSISTENCY).allowed is True

    def denied_among(self, ids: frozenset[str], relation: str) -> frozenset[str]:
        if not ids:
            return frozenset()
        ordered = sorted(ids)
        requests = [
            ClientCheckRequest(user=self.user, relation=relation, object=f"{self.object_prefix}{id}") for id in ordered
        ]
        results = self.client.client_batch_check(requests, CONSISTENCY)
        denied: set[str] = set()
        for id, result in zip(ordered, results, strict=True):
            if result.error is not None:
                raise result.error
            if result.allowed is not True:
                denied.add(id)
        return frozenset(denied)

    def list_ids(self, relation: str) -> frozenset[str] | None:
        """Ids of this project's objects that hold `relation` for the user, or None past the cap."""
        ids: set[str] = set()
        request = ClientListObjectsRequest(user=self.user, relation=relation, type=self.type_name)
        stream = self.client.streamed_list_objects(request, CONSISTENCY)
        try:
            for result in stream:
                if result.object.startswith(self.object_prefix):
                    ids.add(result.object.removeprefix(self.object_prefix))
                    if len(ids) > MAX_IDS:
                        return None
        finally:
            stream.close()
        return frozenset(ids)
