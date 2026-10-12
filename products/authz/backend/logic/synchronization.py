from itertools import batched
from uuid import UUID

from openfga_sdk import ReadRequestTupleKey
from openfga_sdk.client.models import ClientTuple, ClientWriteRequest
from openfga_sdk.sync import OpenFgaClient

from posthog import redis
from posthog.constants import AvailableFeature
from posthog.dataclasses import frozen
from posthog.models import Organization, OrganizationMembership, Team

from products.access_control.backend.facade.authorization import authorization_roles, authorization_rules
from products.dashboards.backend.facade.authorization import authorization_dashboards

from ..client import get_openfga_client
from . import sync_state


@frozen
class Relationship:
    user: str
    relation: str
    object: str

    def to_tuple(self) -> ClientTuple:
        return ClientTuple(user=self.user, relation=self.relation, object=self.object)


class OrganizationProjection:
    def __init__(self, organization_id: UUID) -> None:
        self.organization_id = organization_id
        self.organization_key = f"organization:{organization_id}"
        self.relationships: set[Relationship] = set()

    def key(self, type_name: str, id: str | int) -> str:
        return f"{type_name}:{self.organization_id}/{id}"

    def add(self, user: str, relation: str, object: str) -> None:
        self.relationships.add(Relationship(user=user, relation=relation, object=object))

    def build(self) -> set[Relationship]:
        organization = Organization.objects.filter(id=self.organization_id).first()
        if organization is None:
            return self.relationships

        for relation, enabled in (
            ("access_control_enabled", organization.is_feature_available(AvailableFeature.ACCESS_CONTROL)),
            ("role_based_access_enabled", organization.is_feature_available(AvailableFeature.ROLE_BASED_ACCESS)),
            ("members_can_invite", organization.members_can_invite),
            ("members_can_create_projects", organization.members_can_create_projects),
            ("members_can_see_members", organization.members_can_see_org_members),
        ):
            if enabled:
                self.add("user:*", relation, self.organization_key)

        memberships = list(OrganizationMembership.objects.filter(organization_id=self.organization_id))
        membership_by_user = {membership.user_id: membership for membership in memberships}
        for membership in memberships:
            member_key = self.key("organization_member", str(membership.id))
            user = f"user:{membership.user_id}"
            self.add(user, "user", member_key)
            self.add(self.organization_key, "organization", member_key)
            self.add(self.organization_key, "organization", user)
            level = (
                "owner"
                if membership.level >= OrganizationMembership.Level.OWNER
                else "admin"
                if membership.level >= OrganizationMembership.Level.ADMIN
                else "member"
            )
            self.add(f"{member_key}#user", level, self.organization_key)
            if level == "owner":
                self.add("user:*", "is_owner", member_key)

        for role in authorization_roles(self.organization_id):
            role_key = self.key("role", str(role.id))
            self.add(self.organization_key, "organization", role_key)
            for user_id in role.user_ids:
                role_member = membership_by_user.get(user_id)
                if role_member is not None:
                    self.add(f"{self.key('organization_member', str(role_member.id))}#user", "assignee", role_key)

        for team in Team.objects.filter(organization_id=self.organization_id):
            project_key = self.key("project", team.id)
            category_key = self.key("resource_category", f"{team.id}/dashboard")
            category_policy_key = self.key("access_policy", f"{team.id}/dashboard/default")
            self.add(self.organization_key, "organization", project_key)
            self.add(project_key, "project", category_key)
            self.add(category_policy_key, "policy", category_key)
            self.add(self.organization_key, "organization", category_policy_key)

            dashboards = authorization_dashboards(team.id)
            dashboard_ids = {str(dashboard.id) for dashboard in dashboards}
            for dashboard in dashboards:
                object_key = self.key("dashboard", f"{team.id}/{dashboard.id}")
                policy_key = self.key("access_policy", f"{team.id}/dashboard/{dashboard.id}")
                self.add(project_key, "project", object_key)
                self.add(category_key, "category", object_key)
                self.add(policy_key, "policy", object_key)
                self.add(self.organization_key, "organization", policy_key)
                creator_membership = (
                    membership_by_user.get(dashboard.created_by_id) if dashboard.created_by_id is not None else None
                )
                if creator_membership is not None:
                    self.add(
                        f"{self.key('organization_member', str(creator_membership.id))}#user", "creator", object_key
                    )
                if dashboard.restricted:
                    self.add("user:*", "restricted", object_key)
                for user_id in dashboard.collaborator_user_ids:
                    collaborator = membership_by_user.get(user_id)
                    if collaborator is not None:
                        self.add(
                            f"{self.key('organization_member', str(collaborator.id))}#user", "collaborator", object_key
                        )

            for rule in authorization_rules(team.id, self.organization_id):
                if rule.resource == "project":
                    if rule.resource_id != str(team.id):
                        continue
                    policy_key = project_key
                    levels = {"none", "member", "admin"}
                else:
                    if rule.resource_id is not None and rule.resource_id not in dashboard_ids:
                        continue
                    policy_key = self.key("access_policy", f"{team.id}/dashboard/{rule.resource_id or 'default'}")
                    levels = {"none", "viewer", "editor", "manager"}
                if rule.access_level not in levels:
                    raise ValueError("Cannot mirror an unsupported access level")
                if rule.organization_member_id is not None:
                    user = f"{self.key('organization_member', str(rule.organization_member_id))}#user"
                    subject = "member"
                elif rule.role_id is not None:
                    user = f"{self.key('role', str(rule.role_id))}#member"
                    subject = "role"
                else:
                    user = "user:*"
                    subject = "default"
                self.add(user, f"{subject}_{rule.access_level}", policy_key)
        return self.relationships

    def owns(self, relationship: Relationship) -> bool:
        return (
            relationship.object == self.organization_key
            or relationship.object.partition(":")[2].startswith(f"{self.organization_id}/")
            or (relationship.object.startswith("user:") and relationship.user == self.organization_key)
        )


def read_relationships(client: OpenFgaClient) -> set[Relationship]:
    relationships: set[Relationship] = set()
    token = ""
    while True:
        response = client.read(
            ReadRequestTupleKey(), {"page_size": 100, "continuation_token": token, "consistency": "HIGHER_CONSISTENCY"}
        )
        relationships.update(
            Relationship(user=tuple.key.user, relation=tuple.key.relation, object=tuple.key.object)
            for tuple in response.tuples or []
        )
        token = response.continuation_token
        if not token:
            return relationships


def synchronize_organization(organization_id: UUID) -> None:
    # ponytail: full reconciliation scans the store; use per-object projections before a broad rollout.
    lock = redis.get_client().lock(f"authz:sync:{organization_id}", timeout=300, blocking_timeout=5)
    with lock:
        pending = sync_state.current_state(organization_id)
        if pending is None or not pending.startswith(b"pending:"):
            pending = sync_state.mark_pending(organization_id)
        projection = OrganizationProjection(organization_id)
        desired = projection.build()
        client = get_openfga_client()
        try:
            if client.get_store_id() is None:
                raise RuntimeError("Bootstrap the OpenFGA store before synchronizing authorization")
            current = {relationship for relationship in read_relationships(client) if projection.owns(relationship)}
            # Remove obsolete grants before adding replacements so partial writes cannot preserve revoked access.
            for batch in batched(current - desired, 100, strict=False):
                lock.extend(300, replace_ttl=True)
                client.write(ClientWriteRequest(deletes=[relationship.to_tuple() for relationship in batch]))
            for batch in batched(desired - current, 100, strict=False):
                lock.extend(300, replace_ttl=True)
                client.write(ClientWriteRequest(writes=[relationship.to_tuple() for relationship in batch]))
            lock.extend(300, replace_ttl=True)
            sync_state.mark_ready(organization_id, pending)
        finally:
            client.close()
