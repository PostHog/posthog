from posthog.models import Cohort, FeatureFlag, GroupTypeMapping, Person
from posthog.models.feature_flag import (
    FeatureFlagMatch,
    FeatureFlagMatcher,
    FeatureFlagOverride,
    get_overridden_feature_flags,
)
from posthog.models.group import Group
from posthog.test.base import BaseTest, QueryMatchingTest, snapshot_postgres_queries


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
        Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={"$some_prop": "something"})
        cohort = Cohort.objects.create(
            team=self.team, groups=[{"properties": {"$some_prop": "something"}}], name="cohort1"
        )
        cohort.calculate_people(use_clickhouse=False)

        feature_flag = self.create_feature_flag(
            filters={"groups": [{"properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],}]}
        )

        self.assertEqual(FeatureFlagMatcher(feature_flag, "example_id").get_match(), FeatureFlagMatch())
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
        Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={"$some_prop": "something"})
        cohort = Cohort.objects.create(
            team=self.team, groups=[{"properties": {"$some_prop": "something"}}], name="cohort1"
        )
        cohort.calculate_people(use_clickhouse=False)

        feature_flag = self.create_feature_flag(
            filters={"properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],}
        )

        self.assertEqual(FeatureFlagMatcher(feature_flag, "example_id").get_match(), FeatureFlagMatch())
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


# Integration + performance tests for get_overridden_feature_flags
class TestFeatureFlagsWithOverrides(BaseTest, QueryMatchingTest):
    feature_flag: FeatureFlag

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        person = Person.objects.create(
            team=cls.team,
            distinct_ids=["distinct_id", "another_id"],
            properties={"email": "tim@posthog.com", "team": "posthog"},
        )
        GroupTypeMapping.objects.create(team=cls.team, group_type="organization", group_type_index=0)
        Group.objects.create(
            team=cls.team, group_type_index=0, group_key="PostHog", group_properties={"name": "foo.inc"}, version=1
        )

        FeatureFlag.objects.create(
            team=cls.team,
            name="feature-all",
            key="feature-all",
            created_by=cls.user,
            filters={"groups": [{"rollout_percentage": 100}],},
        )

        FeatureFlag.objects.create(
            team=cls.team,
            name="feature-posthog",
            key="feature-posthog",
            created_by=cls.user,
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": "email", "type": "person", "value": "posthog.com", "operator": "icontains"}
                        ],
                    }
                ],
            },
        )

        tim_feature = FeatureFlag.objects.create(
            team=cls.team,
            name="feature-tim",
            key="feature-tim",
            created_by=cls.user,
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": "email", "type": "person", "value": "tim@posthog.com", "operator": "exact"}
                        ],
                    }
                ],
            },
        )

        FeatureFlag.objects.create(
            team=cls.team,
            name="feature-groups-all",
            key="feature-groups-all",
            created_by=cls.user,
            filters={"aggregation_group_type_index": 0, "groups": [{"rollout_percentage": 100}],},
        )

        FeatureFlag.objects.create(
            team=cls.team,
            name="feature-groups",
            key="feature-groups",
            created_by=cls.user,
            filters={
                "aggregation_group_type_index": 0,
                "groups": [
                    {"properties": [{"key": "name", "value": "foo.inc", "type": "group", "group_type_index": 0}],}
                ],
            },
        )

        disabled_feature = FeatureFlag.objects.create(
            team=cls.team,
            name="feature-disabled",
            key="feature-disabled",
            created_by=cls.user,
            filters={"aggregation_group_type_index": 0, "groups": [{"rollout_percentage": 0}],},
        )

        cls.user.distinct_id = "distinct_id"
        cls.user.save()

        FeatureFlagOverride.objects.create(
            team=cls.team, user=cls.user, feature_flag=disabled_feature, override_value=True
        )
        FeatureFlagOverride.objects.create(team=cls.team, user=cls.user, feature_flag=tim_feature, override_value=False)

    @snapshot_postgres_queries
    def test_person_flags_with_overrides(self):
        flags = get_overridden_feature_flags(self.team, "distinct_id")
        self.assertEqual(flags, {"feature-all": True, "feature-posthog": True, "feature-disabled": True})

    @snapshot_postgres_queries
    def test_group_flags_with_overrides(self):
        flags = get_overridden_feature_flags(self.team, "distinct_id", {"organization": "PostHog"})
        self.assertEqual(
            flags,
            {
                "feature-all": True,
                "feature-posthog": True,
                "feature-disabled": True,
                "feature-groups": True,
                "feature-groups-all": True,
            },
        )
