import pytest
from django.db.utils import IntegrityError

from posthog.test.base import BaseTest
from posthog.models.error_tracking import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingIssueAssignment,
)


class TestErrorTracking(BaseTest):
    def create_issue(self, fingerprints) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        for fingerprint in fingerprints:
            ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint=fingerprint)
        return issue

    def test_defaults(self):
        issue = ErrorTrackingIssue.objects.create(team=self.team)

        assert issue.status == "active"
        assert issue.name is None

    def test_basic_merge(self):
        issue_one = self.create_issue(["fingerprint_one"])
        issue_two = self.create_issue(["fingerprint_two"])

        issue_two.merge(issue_ids=[issue_one.id])

        # remaps the first fingerprint to the second issue
        assert ErrorTrackingIssueFingerprintV2.objects.filter(issue_id=issue_two.id).count() == 2
        # bumps the version
        override = ErrorTrackingIssueFingerprintV2.objects.filter(fingerprint="fingerprint_one").first()
        assert override
        assert override.version == 1

        # deletes issue one
        assert ErrorTrackingIssue.objects.count() == 1

    def test_merge_multiple_times(self):
        issue_one = self.create_issue(["fingerprint_one"])
        issue_two = self.create_issue(["fingerprint_two"])
        issue_three = self.create_issue(["fingerprint_three"])

        issue_two.merge(issue_ids=[issue_one.id])
        issue_three.merge(issue_ids=[issue_two.id])

        # only the third issue remains
        assert ErrorTrackingIssue.objects.count() == 1
        # all fingerprints point to the third issue
        assert ErrorTrackingIssueFingerprintV2.objects.filter(issue_id=issue_three.id).count() == 3

        # bumps versions of the merged issues correct number of times
        override = ErrorTrackingIssueFingerprintV2.objects.filter(fingerprint="fingerprint_one").first()
        assert override
        assert override.version == 2
        override = ErrorTrackingIssueFingerprintV2.objects.filter(fingerprint="fingerprint_two").first()
        assert override
        assert override.version == 1

    def test_merging_multiple_issues_at_once(self):
        issue_one = self.create_issue(["fingerprint_one"])
        issue_two = self.create_issue(["fingerprint_two"])
        issue_three = self.create_issue(["fingerprint_three"])

        issue_three.merge(issue_ids=[issue_one.id, issue_two.id])

        assert ErrorTrackingIssueFingerprintV2.objects.filter(issue_id=issue_three.id).count() == 3

    def test_splitting_fingerprints(self):
        issue = self.create_issue(["fingerprint_one", "fingerprint_two", "fingerprint_three"])

        issue.split(fingerprints=["fingerprint_one", "fingerprint_two"])

        # creates two new issues
        assert ErrorTrackingIssue.objects.count() == 3

        # bumps the version but no longer points to the old issue
        override = ErrorTrackingIssueFingerprintV2.objects.filter(fingerprint="fingerprint_one").first()
        assert override
        assert override.issue_id != issue.id
        assert override.version == 1

    def test_error_tracking_issue_assignment_cascade_deletes(self):
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        ErrorTrackingIssueAssignment.objects.create(issue=issue, user=self.user)

        assert ErrorTrackingIssueAssignment.objects.count() == 1
        issue.delete()
        assert ErrorTrackingIssueAssignment.objects.count() == 0

    def test_error_tracking_issue_assignment_uniqueness(self):
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        with pytest.raises(IntegrityError):
            ErrorTrackingIssueAssignment.objects.create(issue=issue, user=self.user)
            ErrorTrackingIssueAssignment.objects.create(issue=issue, user=self.user)
