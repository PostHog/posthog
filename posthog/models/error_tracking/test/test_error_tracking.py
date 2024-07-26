from posthog.models.error_tracking import ErrorTrackingGroup
from posthog.test.base import BaseTest


class TestErrorTracking(BaseTest):
    def test_defaults(self):
        group = ErrorTrackingGroup.objects.create(status="active", team=self.team, fingerprint="a_fingerprint")

        assert group.fingerprint == "a_fingerprint"
        assert group.merged_fingerprints == []
        assert group.assignee is None

    def test_filtering(self):
        ErrorTrackingGroup.objects.bulk_create(
            [
                ErrorTrackingGroup(team=self.team, fingerprint="first_error"),
                ErrorTrackingGroup(
                    team=self.team, fingerprint="second_error", merged_fingerprints=["previously_merged"]
                ),
                ErrorTrackingGroup(team=self.team, fingerprint="third_error"),
            ]
        )

        matching_groups = ErrorTrackingGroup.objects.filter(fingerprint__in=["first_error", "second_error"])
        assert len(matching_groups) == 2

        matching_groups = ErrorTrackingGroup.objects.filter(merged_fingerprints__contains=["previously_merged"])
        assert len(matching_groups) == 1

        matching_groups = ErrorTrackingGroup.filter_fingerprints(
            queryset=ErrorTrackingGroup.objects, fingerprints=["first_error", "previously_merged"]
        )
        assert len(matching_groups) == 2

    def test_merge(self):
        root_group = ErrorTrackingGroup.objects.create(
            status="active",
            team=self.team,
            fingerprint="a_fingerprint",
            merged_fingerprints=["already_merged_fingerprint"],
        )
        merge_group_1 = ErrorTrackingGroup.objects.create(
            status="active", team=self.team, fingerprint="new_fingerprint"
        )
        merge_group_2 = ErrorTrackingGroup.objects.create(
            status="active",
            team=self.team,
            fingerprint="another_fingerprint",
            merged_fingerprints=["merged_fingerprint"],
        )

        root_group.merge([merge_group_1, merge_group_2])

        assert sorted(root_group.merged_fingerprints) == [
            "already_merged_fingerprint",
            "another_fingerprint",
            "merged_fingerprint",
            "new_fingerprint",
        ]

        # deletes the old groups
        assert len(ErrorTrackingGroup.objects.filter(fingerprint="new_fingerprint")) == 0
