from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models import OrganizationMembership, User
from posthog.session_recordings.models.session_recording import SessionRecording

from products.access_control.backend.facade import testing as access_control_testing
from products.authz.backend.logic.synchronization import OrganizationProjection, Relationship
from products.dashboards.backend.facade import testing as dashboard_testing
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.notebooks.backend.models import Notebook
from products.product_analytics.backend.facade.models import Insight


class TestOrganizationProjection(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.guest = User.objects.create_and_join(self.organization, "guest@example.com", "test-password")
        self.guest_membership = OrganizationMembership.objects.get(organization=self.organization, user=self.guest)
        self.guest_membership.level = OrganizationMembership.Level.GUEST
        self.guest_membership.save()

    def _key(self, type_name: str, id: object) -> str:
        return f"{type_name}:{self.organization.id}/{id}"

    def _member(self, membership: OrganizationMembership) -> str:
        return f"{self._key('organization_member', membership.id)}#user"

    def test_guests_are_written_as_guests_and_never_as_members(self) -> None:
        relationships = OrganizationProjection(self.organization.id).build()
        organization = f"organization:{self.organization.id}"
        assert (
            Relationship(user=self._member(self.guest_membership), relation="guest", object=organization)
            in relationships
        )
        assert not {
            relationship
            for relationship in relationships
            if relationship.user == self._member(self.guest_membership)
            and relationship.object == organization
            and relationship.relation != "guest"
        }

    def test_notebooks_are_objects_with_their_rules_and_embeds(self) -> None:
        insight = Insight.objects.create(team=self.team, created_by=self.user)
        notebook = Notebook.objects.create(
            team=self.team,
            created_by=self.user,
            content={
                "type": "doc",
                "content": [
                    {"type": "ph-query", "attrs": {"query": {"kind": "SavedInsightNode", "shortId": insight.short_id}}},
                    {"type": "ph-query", "attrs": {"query": {"kind": "SavedInsightNode", "shortId": "missing"}}},
                    {"type": "ph-recording", "attrs": {"id": "session-1"}},
                    {"type": "ph-recording", "attrs": {"id": "bad id#1"}},
                ],
            },
        )
        access_control_testing.create_access_control(
            team_id=self.team.id,
            resource="notebook",
            resource_id=str(notebook.id),
            access_level="viewer",
            organization_member_id=self.guest_membership.id,
        )
        relationships = OrganizationProjection(self.organization.id).build()
        project = self._key("project", self.team.id)
        notebook_key = self._key("notebook", f"{self.team.id}/{notebook.id}")
        recording_key = self._key("session_recording", f"{self.team.id}/session-1")
        policy = self._key("access_policy", f"{self.team.id}/notebook/{notebook.id}")
        assert {
            Relationship(user=project, relation="project", object=notebook_key),
            Relationship(
                user=self._key("resource", f"{self.team.id}/notebook"), relation="resource", object=notebook_key
            ),
            Relationship(user=policy, relation="policy", object=notebook_key),
            Relationship(
                user=self._member(OrganizationMembership.objects.get(user=self.user)),
                relation="creator",
                object=notebook_key,
            ),
            Relationship(user=self._member(self.guest_membership), relation="member_viewer", object=policy),
            Relationship(
                user=notebook_key, relation="notebook", object=self._key("insight", f"{self.team.id}/{insight.id}")
            ),
            Relationship(user=project, relation="project", object=recording_key),
            Relationship(user=notebook_key, relation="notebook", object=recording_key),
        } <= relationships
        assert not {
            relationship
            for relationship in relationships
            if relationship.user == notebook_key and relationship.object.endswith(("/missing", "#1"))
        }

    def test_a_deleted_dashboard_passes_no_access_to_its_insights(self) -> None:
        insight = Insight.objects.create(team=self.team, created_by=self.user)
        dashboard_id = dashboard_testing.create_dashboard(team_id=self.team.id)
        DashboardTile.objects.create(dashboard_id=dashboard_id, insight=insight)
        dashboard_testing.set_dashboard_deleted(team_id=self.team.id, dashboard_id=dashboard_id, deleted=True)
        relationships = OrganizationProjection(self.organization.id).build()
        insight_key = self._key("insight", f"{self.team.id}/{insight.id}")
        assert not {
            relationship
            for relationship in relationships
            if relationship.object == insight_key and relationship.relation in ("dashboard", "has_dashboard")
        }

    @parameterized.expand([("embedded recording", True, "none"), ("recording with its own grant", False, "viewer")])
    def test_a_rule_on_a_recording_reaches_its_policy(self, _name: str, embedded: bool, access_level: str) -> None:
        recording = SessionRecording.objects.create(team=self.team, session_id="session-1")
        if embedded:
            Notebook.objects.create(
                team=self.team,
                created_by=self.user,
                content={"type": "doc", "content": [{"type": "ph-recording", "attrs": {"id": "session-1"}}]},
            )
        access_control_testing.create_access_control(
            team_id=self.team.id,
            resource="session_recording",
            resource_id=str(recording.id),
            access_level=access_level,
            organization_member_id=self.guest_membership.id,
        )
        relationships = OrganizationProjection(self.organization.id).build()
        recording_key = self._key("session_recording", f"{self.team.id}/session-1")
        policy = self._key("access_policy", f"{self.team.id}/session_recording/session-1")
        assert {
            Relationship(user=self._key("project", self.team.id), relation="project", object=recording_key),
            Relationship(
                user=self._key("resource", f"{self.team.id}/session_recording"),
                relation="resource",
                object=recording_key,
            ),
            Relationship(user=policy, relation="policy", object=recording_key),
            Relationship(user=self._member(self.guest_membership), relation=f"member_{access_level}", object=policy),
        } <= relationships
