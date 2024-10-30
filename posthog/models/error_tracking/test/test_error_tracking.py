# class TestErrorTracking(BaseTest):
#     def test_defaults(self):
#         group = ErrorTrackingGroup.objects.create(status="active", team=self.team, fingerprint=["a_fingerprint"])

#         assert group.fingerprint == ["a_fingerprint"]
#         assert group.merged_fingerprints == []
#         assert group.assignee is None

#     def test_merge(self):
#         primary_group = ErrorTrackingGroup.objects.create(
#             status="active",
#             team=self.team,
#             fingerprint=["a_fingerprint"],
#             merged_fingerprints=[["already_merged_fingerprint"]],
#         )
#         merge_group_1 = ErrorTrackingGroup.objects.create(
#             status="active", team=self.team, fingerprint=["new_fingerprint"]
#         )
#         merge_group_2 = ErrorTrackingGroup.objects.create(
#             status="active",
#             team=self.team,
#             fingerprint=["another_fingerprint"],
#             merged_fingerprints=[["merged_fingerprint"]],
#         )

#         merging_fingerprints = [merge_group_1.fingerprint, merge_group_2.fingerprint, ["no_group_fingerprint"]]
#         primary_group.merge(merging_fingerprints)

#         assert sorted(primary_group.merged_fingerprints) == [
#             ["already_merged_fingerprint"],
#             ["another_fingerprint"],
#             ["merged_fingerprint"],
#             ["new_fingerprint"],
#             ["no_group_fingerprint"],
#         ]

#         # deletes the old groups
#         assert ErrorTrackingGroup.objects.count() == 1
