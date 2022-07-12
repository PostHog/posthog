from django.db import connection

from posthog.models import Cohort, FeatureFlag, GroupTypeMapping, Person
from posthog.models.feature_flag import (
    FeatureFlagHashKeyOverride,
    FeatureFlagMatch,
    FeatureFlagMatcher,
    get_active_feature_flags,
    hash_key_overrides,
    set_feature_flag_hash_key_overrides,
)
from posthog.models.group import Group
from posthog.test.base import BaseTest, QueryMatchingTest


class TestFeatureFlagMatcher(BaseTest):
    def test_blank_flag(self):
        # Blank feature flags now default to be released for everyone
        feature_flag = self.create_feature_flag()
        self.assertEqual(FeatureFlagMatcher(feature_flag, "example_id").get_match(), FeatureFlagMatch())
        self.assertEqual(FeatureFlagMatcher(feature_flag, "another_id").get_match(), FeatureFlagMatch())

    def test_rollout_percentage(self):
        feature_flag = self.create_feature_flag(filters={"groups": [{"rollout_percentage": 50}]})
        self.assertEqual(FeatureFlagMatcher(feature_flag, "example_id").get_match(), FeatureFlagMatch())
        self.assertIsNone(FeatureFlagMatcher(feature_flag, "another_id").get_match())

    def test_empty_group(self):
        feature_flag = self.create_feature_flag(filters={"groups": [{}]})
        self.assertEqual(FeatureFlagMatcher(feature_flag, "example_id").get_match(), FeatureFlagMatch())
        self.assertEqual(FeatureFlagMatcher(feature_flag, "another_id").get_match(), FeatureFlagMatch())

    def test_null_rollout_percentage(self):
        feature_flag = self.create_feature_flag(filters={"groups": [{"properties": [], "rollout_percentage": None}]})
        self.assertEqual(FeatureFlagMatcher(feature_flag, "example_id").get_match(), FeatureFlagMatch())

    def test_zero_rollout_percentage(self):
        feature_flag = self.create_feature_flag(filters={"groups": [{"properties": [], "rollout_percentage": 0}]})
        self.assertEqual(FeatureFlagMatcher(feature_flag, "example_id").get_match(), None)

    def test_complicated_flag(self):
        Person.objects.create(
            team=self.team, distinct_ids=["test_id"], properties={"email": "test@posthog.com"},
        )

        feature_flag = self.create_feature_flag(
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": "email", "type": "person", "value": "test@posthog.com", "operator": "exact"}
                        ],
                        "rollout_percentage": 100,
                    },
                    {"rollout_percentage": 50},
                ]
            }
        )

        self.assertEqual(FeatureFlagMatcher(feature_flag, "test_id").get_match(), FeatureFlagMatch())
        self.assertEqual(FeatureFlagMatcher(feature_flag, "example_id").get_match(), FeatureFlagMatch())
        self.assertIsNone(FeatureFlagMatcher(feature_flag, "another_id").get_match())

    def test_multi_property_filters(self):
        Person.objects.create(
            team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"},
        )
        Person.objects.create(
            team=self.team, distinct_ids=["another_id"], properties={"email": "example@example.com"},
        )
        feature_flag = self.create_feature_flag(
            filters={
                "groups": [
                    {"properties": [{"key": "email", "value": "tim@posthog.com"}]},
                    {"properties": [{"key": "email", "value": "example@example.com"}]},
                ]
            }
        )
        with self.assertNumQueries(1):
            self.assertEqual(FeatureFlagMatcher(feature_flag, "example_id").get_match(), FeatureFlagMatch())
        with self.assertNumQueries(1):
            self.assertEqual(FeatureFlagMatcher(feature_flag, "another_id").get_match(), FeatureFlagMatch())
        self.assertIsNone(FeatureFlagMatcher(feature_flag, "false_id").get_match())

    def test_user_in_cohort(self):
        Person.objects.create(team=self.team, distinct_ids=["example_id_1"], properties={"$some_prop_1": "something_1"})
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop_1", "value": "something_1", "type": "person"}]}],
            name="cohort1",
        )
        cohort.calculate_people_ch(pending_version=0)

        feature_flag: FeatureFlag = self.create_feature_flag(
            filters={"groups": [{"properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],}]}
        )

        feature_flag.update_cohorts()

        self.assertEqual(FeatureFlagMatcher(feature_flag, "example_id_1").get_match(), FeatureFlagMatch())
        self.assertIsNone(FeatureFlagMatcher(feature_flag, "another_id").get_match())

    def test_legacy_rollout_percentage(self):
        feature_flag = self.create_feature_flag(rollout_percentage=50)
        self.assertEqual(FeatureFlagMatcher(feature_flag, "example_id").get_match(), FeatureFlagMatch())
        self.assertIsNone(FeatureFlagMatcher(feature_flag, "another_id").get_match())

    def test_legacy_property_filters(self):
        Person.objects.create(
            team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"},
        )
        Person.objects.create(
            team=self.team, distinct_ids=["another_id"], properties={"email": "example@example.com"},
        )
        feature_flag = self.create_feature_flag(filters={"properties": [{"key": "email", "value": "tim@posthog.com"}]},)
        self.assertEqual(FeatureFlagMatcher(feature_flag, "example_id").get_match(), FeatureFlagMatch())
        self.assertIsNone(FeatureFlagMatcher(feature_flag, "another_id").get_match())

    def test_legacy_rollout_and_property_filter(self):
        Person.objects.create(
            team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"},
        )
        Person.objects.create(
            team=self.team, distinct_ids=["another_id"], properties={"email": "tim@posthog.com"},
        )
        Person.objects.create(
            team=self.team, distinct_ids=["id_number_3"], properties={"email": "example@example.com"},
        )
        feature_flag = self.create_feature_flag(
            rollout_percentage=50,
            filters={"properties": [{"key": "email", "value": "tim@posthog.com", "type": "person"}]},
        )
        with self.assertNumQueries(1):
            self.assertEqual(FeatureFlagMatcher(feature_flag, "example_id").get_match(), FeatureFlagMatch())
        self.assertIsNone(FeatureFlagMatcher(feature_flag, "another_id").get_match())
        self.assertIsNone(FeatureFlagMatcher(feature_flag, "id_number_3").get_match())

    def test_legacy_user_in_cohort(self):
        Person.objects.create(team=self.team, distinct_ids=["example_id_2"], properties={"$some_prop_2": "something_2"})
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop_2", "value": "something_2", "type": "person"}]}],
            name="cohort2",
        )
        cohort.calculate_people_ch(pending_version=0)

        feature_flag: FeatureFlag = self.create_feature_flag(
            filters={"properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],}
        )

        feature_flag.update_cohorts()

        self.assertEqual(FeatureFlagMatcher(feature_flag, "example_id_2").get_match(), FeatureFlagMatch())
        self.assertIsNone(FeatureFlagMatcher(feature_flag, "another_id").get_match())

    def test_variants(self):
        feature_flag = self.create_feature_flag(
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                        {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                        {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 25},
                    ],
                },
            }
        )

        self.assertEqual(FeatureFlagMatcher(feature_flag, "11").get_match(), FeatureFlagMatch(variant="first-variant"))
        self.assertEqual(
            FeatureFlagMatcher(feature_flag, "example_id").get_match(), FeatureFlagMatch(variant="second-variant")
        )
        self.assertEqual(FeatureFlagMatcher(feature_flag, "3").get_match(), FeatureFlagMatch(variant="third-variant"))

    def test_flag_by_groups_with_rollout_100(self):
        self.create_groups()
        feature_flag = self.create_feature_flag(
            filters={"aggregation_group_type_index": 1, "groups": [{"rollout_percentage": 100}],}
        )

        self.assertIsNone(FeatureFlagMatcher(feature_flag, "").get_match())
        self.assertIsNone(FeatureFlagMatcher(feature_flag, "", {"unknown": "group_key"}).get_match())
        self.assertIsNone(FeatureFlagMatcher(feature_flag, "", {"organization": "group_key"}).get_match())
        self.assertEqual(FeatureFlagMatcher(feature_flag, "", {"project": "group_key"}).get_match(), FeatureFlagMatch())

    def test_flag_by_groups_with_rollout_50(self):
        self.create_groups()
        feature_flag = self.create_feature_flag(
            filters={"aggregation_group_type_index": 1, "groups": [{"rollout_percentage": 50}],}
        )

        self.assertIsNone(FeatureFlagMatcher(feature_flag, "", {"project": "1"}).get_match())
        self.assertEqual(FeatureFlagMatcher(feature_flag, "", {"project": "4"}).get_match(), FeatureFlagMatch())

    def test_flag_by_group_properties(self):
        self.create_groups()
        feature_flag = self.create_feature_flag(
            filters={
                "aggregation_group_type_index": 0,
                "groups": [
                    {"properties": [{"key": "name", "value": "foo.inc", "type": "group", "group_type_index": 0}],}
                ],
            }
        )
        self.assertEqual(FeatureFlagMatcher(feature_flag, "", {"organization": "foo"}).get_match(), FeatureFlagMatch())
        self.assertIsNone(FeatureFlagMatcher(feature_flag, "", {"organization": "bar"}).get_match())

    def create_groups(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        GroupTypeMapping.objects.create(team=self.team, group_type="project", group_type_index=1)
        Group.objects.create(
            team=self.team, group_type_index=0, group_key="foo", group_properties={"name": "foo.inc"}, version=1
        )
        Group.objects.create(
            team=self.team, group_type_index=0, group_key="bar", group_properties={"name": "var.inc"}, version=1
        )

    def create_feature_flag(self, **kwargs):
        return FeatureFlag.objects.create(
            team=self.team, name="Beta feature", key="beta-feature", created_by=self.user, **kwargs
        )


class TestFeatureFlagHashKeyOverrides(BaseTest, QueryMatchingTest):

    person: Person

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        FeatureFlag.objects.create(
            team=cls.team,
            rollout_percentage=30,
            name="Beta feature",
            key="beta-feature",
            created_by=cls.user,
            ensure_experience_continuity=True,
        )
        FeatureFlag.objects.create(
            team=cls.team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            name="This is a feature flag with default params, no filters.",
            key="default-flag",
            created_by=cls.user,
        )  # Should be enabled for everyone
        FeatureFlag.objects.create(
            team=cls.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                        {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                        {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 25},
                    ],
                },
            },
            name="This is a feature flag with multiple variants.",
            key="multivariate-flag",
            created_by=cls.user,
            ensure_experience_continuity=True,
        )

        cls.person = Person.objects.create(
            team=cls.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com", "team": "posthog"},
        )

    def test_setting_overrides(self):

        all_feature_flags = FeatureFlag.objects.filter(team_id=self.team.pk)

        set_feature_flag_hash_key_overrides(
            all_feature_flags, team_id=self.team.pk, person_id=self.person.id, hash_key_override="other_id"
        )

        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT hash_key FROM posthog_featureflaghashkeyoverride WHERE team_id = {self.team.pk} AND person_id={self.person.id}"
            )
            res = cursor.fetchall()
            self.assertEqual(len(res), 2)
            self.assertEqual(set([var[0] for var in res]), set(["other_id"]))

    def test_retrieving_hash_key_overrides(self):

        all_feature_flags = FeatureFlag.objects.filter(team_id=self.team.pk)

        set_feature_flag_hash_key_overrides(
            all_feature_flags, team_id=self.team.pk, person_id=self.person.id, hash_key_override="other_id"
        )

        hash_keys = hash_key_overrides(self.team.pk, self.person.id)

        self.assertEqual(hash_keys, {"beta-feature": "other_id", "multivariate-flag": "other_id"})

    def test_setting_overrides_doesnt_balk_with_existing_overrides(self):

        all_feature_flags = FeatureFlag.objects.filter(team_id=self.team.pk)

        # existing overrides
        hash_key = "bazinga"
        FeatureFlagHashKeyOverride.objects.bulk_create(
            [
                FeatureFlagHashKeyOverride(
                    team_id=self.team.pk, person_id=self.person.id, feature_flag_key=feature_flag.key, hash_key=hash_key
                )
                for feature_flag in all_feature_flags
            ]
        )

        # and now we come to get new overrides
        set_feature_flag_hash_key_overrides(
            all_feature_flags, team_id=self.team.pk, person_id=self.person.id, hash_key_override="other_id"
        )

        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT hash_key FROM posthog_featureflaghashkeyoverride WHERE team_id = {self.team.pk} AND person_id={self.person.id}"
            )
            res = cursor.fetchall()
            self.assertEqual(len(res), 3)
            self.assertEqual(set([var[0] for var in res]), set([hash_key]))

    def test_entire_flow_with_hash_key_override(self):
        # get feature flags for 'other_id', with an override for 'example_id'
        flags = get_active_feature_flags(self.team.pk, "other_id", {}, "example_id")
        self.assertEqual(flags, {"beta-feature": True, "multivariate-flag": "first-variant", "default-flag": True,})
