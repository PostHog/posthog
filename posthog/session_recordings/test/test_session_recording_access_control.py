import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.rbac.user_access_control import UserAccessControl
from posthog.session_recordings.models.session_recording import SessionRecording

try:
    from ee.models.rbac.access_control import AccessControl
    from ee.models.rbac.role import Role, RoleMembership
except ImportError:
    pass


@pytest.mark.ee
class TestSessionRecordingAccessControl(APIBaseTest):
    def setUp(self):
        super().setUp()

        # Enable access control features
        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ADVANCED_PERMISSIONS,
                "name": AvailableFeature.ADVANCED_PERMISSIONS,
            },
            {
                "key": AvailableFeature.ROLE_BASED_ACCESS,
                "name": AvailableFeature.ROLE_BASED_ACCESS,
            },
        ]
        self.organization.save()

        # Create test users
        self.viewer_user = User.objects.create_and_join(self.organization, "viewer@posthog.com", "testtest")
        self.editor_user = User.objects.create_and_join(self.organization, "editor@posthog.com", "testtest")
        self.no_access_user = User.objects.create_and_join(self.organization, "noaccess@posthog.com", "testtest")

        # Create a test recording
        self.recording = SessionRecording.objects.create(
            team=self.team, session_id="test_session_123", distinct_id="user123", deleted=False
        )

    def _create_access_control(self, user, resource="session_recording", resource_id=None, access_level="viewer"):
        """Helper to create access control for a user"""
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        return AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=resource_id,
            access_level=access_level,
            organization_member=membership,
        )

    @patch("posthog.session_recordings.models.session_recording.SessionRecording.load_metadata", return_value=True)
    def test_viewer_can_retrieve_recording(self, mock_load_metadata):
        """Test that a user with viewer access can retrieve a recording"""
        self._create_access_control(self.viewer_user, access_level="viewer")

        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/{self.recording.session_id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], self.recording.session_id)

    def test_viewer_can_list_recordings(self):
        """Test that a user with viewer access can list recordings"""
        self._create_access_control(self.viewer_user, access_level="viewer")

        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch("posthog.session_recordings.models.session_recording.SessionRecording.load_metadata", return_value=True)
    def test_viewer_cannot_delete_recording(self, mock_load_metadata):
        """Test that a user with viewer access cannot delete a recording"""
        self._create_access_control(self.viewer_user, access_level="viewer")

        self.client.force_login(self.viewer_user)
        response = self.client.delete(f"/api/projects/{self.team.id}/session_recordings/{self.recording.session_id}/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("You do not have editor access", response.json()["detail"])

    @patch("posthog.session_recordings.models.session_recording.SessionRecording.load_metadata", return_value=True)
    def test_editor_can_delete_recording(self, mock_load_metadata):
        """Test that a user with editor access can delete a recording"""
        self._create_access_control(self.editor_user, access_level="editor")

        self.client.force_login(self.editor_user)
        response = self.client.delete(f"/api/projects/{self.team.id}/session_recordings/{self.recording.session_id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # Verify the recording is marked as deleted
        self.recording.refresh_from_db()
        self.assertTrue(self.recording.deleted)

    @patch("posthog.session_recordings.session_recording_api.list_recordings_from_query")
    def test_editor_can_bulk_delete_recordings(self, mock_list_recordings):
        """Test that a user with editor access can bulk delete recordings"""
        # Create additional recordings
        recording2 = SessionRecording.objects.create(
            team=self.team, session_id="test_session_456", distinct_id="user456", deleted=False
        )

        # Mock the ClickHouse query to return our test recordings
        mock_list_recordings.return_value = ([self.recording, recording2], False, "")

        self._create_access_control(self.editor_user, access_level="editor")

        self.client.force_login(self.editor_user)
        response = self.client.post(
            f"/api/projects/{self.team.id}/session_recordings/bulk_delete/",
            {"session_recording_ids": [self.recording.session_id, recording2.session_id]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify both recordings are marked as deleted
        self.recording.refresh_from_db()
        recording2.refresh_from_db()
        self.assertTrue(self.recording.deleted)
        self.assertTrue(recording2.deleted)

    @patch("posthog.session_recordings.models.session_recording.SessionRecording.load_metadata", return_value=True)
    def test_no_access_user_cannot_view_recording(self, mock_load_metadata):
        """Test that a user with no access cannot view a recording"""
        self._create_access_control(self.no_access_user, access_level="none")

        self.client.force_login(self.no_access_user)
        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/{self.recording.session_id}/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("posthog.session_recordings.models.session_recording.SessionRecording.load_metadata", return_value=True)
    def test_specific_recording_access(self, mock_load_metadata):
        """Test that a user can have access to specific recordings only"""
        # Create another recording
        recording2 = SessionRecording.objects.create(
            team=self.team, session_id="test_session_789", distinct_id="user789", deleted=False
        )

        # Give viewer access to only the first recording
        self._create_access_control(
            self.viewer_user, resource="session_recording", resource_id=str(self.recording.id), access_level="viewer"
        )

        # Set resource-level access to none
        self._create_access_control(
            self.viewer_user, resource="session_recording", resource_id=None, access_level="none"
        )

        self.client.force_login(self.viewer_user)

        # Should be able to access the first recording
        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/{self.recording.session_id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should not be able to access the second recording
        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/{recording2.session_id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("posthog.session_recordings.models.session_recording.SessionRecording.load_metadata", return_value=True)
    def test_org_admin_has_full_access(self, mock_load_metadata):
        """Test that organization admins have full access to recordings"""
        # Make user an org admin
        membership = OrganizationMembership.objects.get(user=self.editor_user, organization=self.organization)
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save()

        self.client.force_login(self.editor_user)

        # Should be able to delete without explicit permissions
        response = self.client.delete(f"/api/projects/{self.team.id}/session_recordings/{self.recording.session_id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    @patch("posthog.session_recordings.models.session_recording.SessionRecording.load_metadata", return_value=True)
    def test_role_based_access(self, mock_load_metadata):
        """Test that roles can be used to grant recording access"""
        # Create a role with editor access to recordings
        role = Role.objects.create(name="Recording Editors", organization=self.organization)
        RoleMembership.objects.create(user=self.editor_user, role=role)

        # Grant the role editor access
        AccessControl.objects.create(team=self.team, resource="session_recording", access_level="editor", role=role)

        self.client.force_login(self.editor_user)
        response = self.client.delete(f"/api/projects/{self.team.id}/session_recordings/{self.recording.session_id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_manager_can_modify_access_controls(self):
        """Test that a user with manager access can modify access controls for recordings"""
        # Give manager access to the user
        self._create_access_control(self.editor_user, access_level="manager")

        # The manager should be able to grant access to others
        uac = UserAccessControl(self.editor_user, self.team)
        can_modify = uac.check_can_modify_access_levels_for_object(self.recording)

        self.assertTrue(can_modify)
