from posthog.test.base import APIBaseTest
from posthog.models import Team, ErrorTrackingGroup


class TestErrorTracking(APIBaseTest):
    def test_reuses_existing_group_for_team(self):
        fingerprint = "CustomFingerprint"
        ErrorTrackingGroup.objects.create(fingerprint=fingerprint, team=self.team)

        self.assertEqual(ErrorTrackingGroup.objects.count(), 1)
        self.client.patch(
            f"/api/projects/{self.team.id}/error_tracking/{fingerprint}",
            data={"assignee": self.user.id},
        )
        self.assertEqual(ErrorTrackingGroup.objects.count(), 1)

    def test_creates_group_if_not_already_existing_for_team(self):
        fingerprint = "CustomFingerprint"
        other_team = Team.objects.create(organization=self.organization)
        ErrorTrackingGroup.objects.create(fingerprint=fingerprint, team=other_team)

        self.assertEqual(ErrorTrackingGroup.objects.count(), 1)
        self.client.patch(
            f"/api/projects/{self.team.id}/error_tracking/{fingerprint}",
            data={"assignee": self.user.id},
        )
        self.assertEqual(ErrorTrackingGroup.objects.count(), 2)

    def test_can_only_update_allowed_fields(self):
        fingerprint = "CustomFingerprint"
        other_team = Team.objects.create(organization=self.organization)
        group = ErrorTrackingGroup.objects.create(fingerprint=fingerprint, team=other_team)

        self.client.patch(
            f"/api/projects/{self.team.id}/error_tracking/{fingerprint}",
            data={"fingerprint": "NewFingerprint", "assignee": self.user.id},
        )
        group.refresh_from_db()
        self.assertEqual(group.fingerprint, "CustomFingerprint")
