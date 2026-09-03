import pytest

from rest_framework import status

from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team import Team
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.facade.resolution_preview import build_resolution_preview
from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.tests.test_user_access_control import BaseUserAccessControlTest
from products.dashboards.backend.models.dashboard import Dashboard


@pytest.mark.ee
class TestBuildResolutionPreview(BaseUserAccessControlTest):
    def setUp(self):
        super().setUp()
        self.other_membership = OrganizationMembership.objects.get(user=self.other_user, organization=self.organization)
        self.dashboard = Dashboard.objects.create(team=self.team, created_by=self.user, name="Growth KPIs")

    def _changes(self):
        return build_resolution_preview(self.team, self.user_access_control)

    def test_object_default_change_is_one_everyone_record(self):
        # The change reaches every member without a more specific rule, but it is one rule:
        # per-member records would explode a default change into the whole project roster
        self._create_access_control(resource="dashboard", resource_id=str(self.dashboard.id), access_level="viewer")
        self._create_access_control(resource="dashboard", access_level="editor")

        changes = self._changes()

        assert len(changes) == 1
        change = changes[0]
        assert change.subject.type == "default"
        assert change.scope == "object"
        assert change.object_id == str(self.dashboard.id)
        assert change.object_name == "Growth KPIs"
        assert (change.current.access_level, change.current.source) == ("editor", "resource")
        assert (change.proposed.access_level, change.proposed.source) == ("viewer", "object")
        assert change.direction == "loses"

    def test_member_override_produces_member_record_only(self):
        # other_user holds role_b (base fixture). Today the role's grant applies; after the
        # change their own override applies. The role itself resolves the same both ways, so
        # only the member record is reported, not one row per role member.
        self._create_access_control(
            resource="dashboard",
            resource_id=str(self.dashboard.id),
            access_level="none",
            organization_member=self.other_membership,
        )
        self._create_access_control(
            resource="dashboard", resource_id=str(self.dashboard.id), access_level="editor", role=self.role_b
        )

        changes = self._changes()

        assert len(changes) == 1
        change = changes[0]
        assert change.subject.type == "member"
        assert change.subject.id == str(self.other_membership.id)
        assert (change.current.access_level, change.proposed.access_level) == ("editor", "none")
        assert change.proposed.source_subject == "member"
        assert change.direction == "loses"

    def test_resource_scope_member_below_role_is_one_record(self):
        # other_user holds role_b (base fixture); their own resource-wide "none" starts applying
        self._create_access_control(
            resource="dashboard", access_level="none", organization_member=self.other_membership
        )
        self._create_access_control(resource="dashboard", access_level="editor", role=self.role_b)

        changes = self._changes()

        assert len(changes) == 1
        change = changes[0]
        assert change.scope == "resource"
        assert change.subject.type == "member"
        assert (change.current.access_level, change.proposed.access_level) == ("editor", "none")

    def test_member_row_on_one_object_adds_no_records_for_other_objects(self):
        # The everyone record already describes objects the member holds no rule on; a
        # per-member copy of it would repeat the same change once per rule-holding member
        other_dashboard = Dashboard.objects.create(team=self.team, created_by=self.user, name="Ops KPIs")
        self._create_access_control(resource="dashboard", resource_id=str(self.dashboard.id), access_level="viewer")
        self._create_access_control(resource="dashboard", access_level="editor")
        self._create_access_control(
            resource="dashboard",
            resource_id=str(other_dashboard.id),
            access_level="editor",
            organization_member=self.other_membership,
        )

        changes = self._changes()

        assert [(change.subject.type, change.object_id) for change in changes] == [("default", str(self.dashboard.id))]

    def test_parent_resource_row_is_compared_against_child_objects(self):
        # Resolution consults the parent resource (session_recording) for playlist objects, so
        # a member whose only rule sits there can still resolve a playlist differently
        from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist

        playlist = SessionRecordingPlaylist.objects.create(team=self.team, created_by=self.user, name="Bug hunts")
        self._create_access_control(
            resource="session_recording_playlist", resource_id=str(playlist.id), access_level="none"
        )
        self._create_access_control(
            resource="session_recording", access_level="editor", organization_member=self.other_membership
        )

        changes = self._changes()

        member_changes = [change for change in changes if change.subject.type == "member"]
        assert [(change.scope, change.object_id) for change in member_changes] == [("object", str(playlist.id))]
        assert (member_changes[0].current.access_level, member_changes[0].proposed.access_level) == ("editor", "none")

    def test_creator_pairs_are_skipped(self):
        # Creators keep the highest level under both ladders, so their override never applies
        dashboard = Dashboard.objects.create(team=self.team, created_by=self.other_user)
        self._create_access_control(
            resource="dashboard",
            resource_id=str(dashboard.id),
            access_level="none",
            organization_member=self.other_membership,
        )
        self._create_access_control(resource="dashboard", resource_id=str(dashboard.id), access_level="editor")

        changes = self._changes()

        assert [change for change in changes if change.subject.type == "member"] == []

    def test_org_admin_members_are_skipped(self):
        self._create_access_control(
            resource="dashboard",
            resource_id=str(self.dashboard.id),
            access_level="none",
            organization_member=self.other_membership,
        )
        self._create_access_control(resource="dashboard", resource_id=str(self.dashboard.id), access_level="editor")
        self.other_membership.level = OrganizationMembership.Level.ADMIN
        self.other_membership.save()

        changes = self._changes()

        assert [change for change in changes if change.subject.type == "member"] == []

    def test_no_entitlement_returns_no_changes(self):
        self._create_access_control(resource="dashboard", resource_id=str(self.dashboard.id), access_level="viewer")
        self._create_access_control(resource="dashboard", access_level="editor")
        self.organization.available_product_features = []
        self.organization.save()

        assert self._changes() == []


@pytest.mark.ee
class TestResolutionPreviewAPI(BaseUserAccessControlTest):
    def setUp(self):
        super().setUp()
        self.dashboard = Dashboard.objects.create(team=self.team, created_by=self.other_user, name="Growth KPIs")
        self._create_access_control(resource="dashboard", resource_id=str(self.dashboard.id), access_level="viewer")
        self._create_access_control(resource="dashboard", access_level="editor")
        self.membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        self.client.force_login(self.user)

    def test_requires_admin(self):
        response = self.client.get("/api/projects/@current/access_control_resolution_preview")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_hidden_member_list_requires_org_admin(self):
        # A project admin passes the base gate, but the org hides its member list
        self._create_access_control(resource="project", resource_id=str(self.team.id), access_level="admin")
        self.organization.members_can_see_org_members = False
        self.organization.save()

        response = self.client.get("/api/projects/@current/access_control_resolution_preview")
        assert response.status_code == status.HTTP_403_FORBIDDEN

        self.membership.level = OrganizationMembership.Level.ADMIN
        self.membership.save()

        response = self.client.get("/api/projects/@current/access_control_resolution_preview")
        assert response.status_code == status.HTTP_200_OK

    def test_returns_changes_and_summary(self):
        self.membership.level = OrganizationMembership.Level.ADMIN
        self.membership.save()

        response = self.client.get("/api/projects/@current/access_control_resolution_preview")

        assert response.status_code == status.HTTP_200_OK, response.json()
        data = response.json()
        assert data["summary"]["total"] == 1
        assert data["summary"]["loses"] == 1
        change = data["changes"][0]
        assert change["subject"] == {"type": "default", "id": None, "name": "Everyone"}
        assert change["object_name"] == "Growth KPIs"
        assert change["project_id"] == self.team.id
        assert change["project_name"] == self.team.name
        assert change["current"] == {
            "access_level": "editor",
            "source": "resource",
            "source_subject": "default",
            "source_resource": "dashboard",
            "source_resource_id": None,
            "subject_name": None,
        }
        assert change["proposed"] == {
            "access_level": "viewer",
            "source": "object",
            "source_subject": "default",
            "source_resource": "dashboard",
            "source_resource_id": str(self.dashboard.id),
            "subject_name": None,
        }

    def test_covers_every_project_the_requester_administers(self):
        other_team = Team.objects.create(organization=self.organization, name="Second project")
        other_dashboard = Dashboard.objects.create(team=other_team, created_by=self.other_user, name="Other KPIs")
        AccessControl.objects.create(
            team=other_team, resource="dashboard", resource_id=str(other_dashboard.id), access_level="viewer"
        )
        AccessControl.objects.create(team=other_team, resource="dashboard", resource_id=None, access_level="editor")

        # A project admin of the current team only sees this team's changes
        self._create_access_control(resource="project", resource_id=str(self.team.id), access_level="admin")
        response = self.client.get("/api/projects/@current/access_control_resolution_preview")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert {change["project_name"] for change in response.json()["changes"]} == {self.team.name}

        # An org admin sees every project with rules
        self.membership.level = OrganizationMembership.Level.ADMIN
        self.membership.save()
        response = self.client.get("/api/projects/@current/access_control_resolution_preview")
        assert response.status_code == status.HTTP_200_OK, response.json()
        data = response.json()
        assert data["summary"]["total"] == 2
        assert {change["project_name"] for change in data["changes"]} == {self.team.name, "Second project"}

    def test_project_scoped_credential_stays_within_its_projects(self):
        self.membership.level = OrganizationMembership.Level.ADMIN
        self.membership.save()
        other_team = Team.objects.create(organization=self.organization, name="Second project")
        other_dashboard = Dashboard.objects.create(team=other_team, created_by=self.other_user, name="Other KPIs")
        AccessControl.objects.create(
            team=other_team, resource="dashboard", resource_id=str(other_dashboard.id), access_level="viewer"
        )
        AccessControl.objects.create(team=other_team, resource="dashboard", resource_id=None, access_level="editor")
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="scoped", user=self.user, secure_value=hash_key_value(key), scoped_teams=[self.team.id], scopes=["*"]
        )
        self.client.logout()

        response = self.client.get(
            f"/api/projects/{self.team.id}/access_control_resolution_preview",
            headers={"authorization": f"Bearer {key}"},
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert {change["project_name"] for change in response.json()["changes"]} == {self.team.name}
