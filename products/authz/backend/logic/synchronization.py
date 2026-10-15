from itertools import batched
from uuid import UUID

from openfga_sdk import ReadRequestTupleKey
from openfga_sdk.client.models import ClientTuple, ClientWriteRequest
from openfga_sdk.sync import OpenFgaClient

from posthog import redis
from posthog.constants import AvailableFeature
from posthog.dataclasses import frozen
from posthog.models import Organization, OrganizationMembership, SharingConfiguration, Team

from products.access_control.backend.facade.authorization import authorization_roles, authorization_rules
from products.access_control.backend.facade.user_access_control import ACCESS_CONTROL_RESOURCES
from products.dashboards.backend.facade.authorization import authorization_dashboards

from ..client import pooled_openfga_client
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

    def add_shares(self, team: Team, active_insight_ids: set[str]) -> None:
        shares = SharingConfiguration.objects.filter(
            SharingConfiguration.tokens_active_q(),
            SharingConfiguration.without_retired_resources_q(),
            team_id=team.id,
        ).select_related("dashboard", "insight", "notebook", "recording")
        for share in shares:
            principal = f"share_link:{share.pk}"
            self.add(principal, "shared_viewer", self.key("project", team.id))
            has_target = False
            for field, resource_type in (
                ("dashboard", "dashboard"),
                ("insight", "insight"),
                ("notebook", "notebook"),
                ("recording", "session_recording"),
            ):
                target = getattr(share, field)
                if target is None or target.team_id != team.id or target.deleted:
                    continue
                id = target.session_id if field == "recording" else target.pk
                self.add(principal, "shared_viewer", self.key(resource_type, f"{team.id}/{id}"))
                has_target = True
            if not has_target:
                continue
            for id in share.get_connected_insight_ids():
                if str(id) in active_insight_ids:
                    self.add(principal, "shared_viewer", self.key("insight", f"{team.id}/{id}"))

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

        from products.product_analytics.backend.facade.api import (  # noqa: PLC0415 -- defer product analytics models
            authorization_insights,
        )

        for team in Team.objects.filter(organization_id=self.organization_id):
            project_key = self.key("project", team.id)
            self.add(self.organization_key, "organization", project_key)
            resource_keys = {}
            for category in ACCESS_CONTROL_RESOURCES:
                resource_key = self.key("resource", f"{team.id}/{category}")
                resource_policy_key = self.key("access_policy", f"{team.id}/{category}/default")
                resource_keys[category] = resource_key
                self.add(project_key, "project", resource_key)
                self.add(resource_policy_key, "policy", resource_key)
                self.add(self.organization_key, "organization", resource_policy_key)

            dashboards = authorization_dashboards(team.id)
            dashboard_ids = {str(dashboard.id) for dashboard in dashboards}
            for dashboard in dashboards:
                object_key = self.key("dashboard", f"{team.id}/{dashboard.id}")
                policy_key = self.key("access_policy", f"{team.id}/dashboard/{dashboard.id}")
                self.add(project_key, "project", object_key)
                self.add(resource_keys["dashboard"], "resource", object_key)
                self.add(policy_key, "policy", object_key)
                self.add(self.organization_key, "organization", policy_key)
                creator_membership = (
                    membership_by_user.get(dashboard.created_by_id) if dashboard.created_by_id is not None else None
                )
                if creator_membership is not None:
                    self.add(
                        f"{self.key('organization_member', str(creator_membership.id))}#user", "creator", object_key
                    )

            insights = authorization_insights(team.id)
            insight_ids = {str(insight.id) for insight in insights}
            for insight in insights:
                object_key = self.key("insight", f"{team.id}/{insight.id}")
                policy_key = self.key("access_policy", f"{team.id}/insight/{insight.id}")
                self.add(project_key, "project", object_key)
                self.add(resource_keys["insight"], "resource", object_key)
                self.add(policy_key, "policy", object_key)
                self.add(self.organization_key, "organization", policy_key)
                creator_membership = (
                    membership_by_user.get(insight.created_by_id) if insight.created_by_id is not None else None
                )
                if creator_membership is not None:
                    self.add(
                        f"{self.key('organization_member', str(creator_membership.id))}#user", "creator", object_key
                    )

            for rule in authorization_rules(team.id, self.organization_id):
                if rule.resource == "project":
                    if rule.resource_id != str(team.id):
                        continue
                    policy_key = project_key
                    levels = {"none", "member", "admin"}
                else:
                    resource_type = rule.resource
                    if rule.resource_id is not None:
                        resource_ids = {"dashboard": dashboard_ids, "insight": insight_ids}.get(resource_type, set())
                        if rule.resource_id not in resource_ids:
                            continue
                    elif resource_type not in resource_keys:
                        continue
                    policy_key = self.key("access_policy", f"{team.id}/{resource_type}/{rule.resource_id or 'default'}")
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
            if not (
                organization.is_feature_available(AvailableFeature.ORGANIZATION_SECURITY_SETTINGS)
                and not organization.allow_publicly_shared_resources
            ):
                self.add_shares(team, {str(insight.id) for insight in insights if not insight.deleted})
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
        with pooled_openfga_client(consistency="HIGHER_CONSISTENCY") as client:
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
