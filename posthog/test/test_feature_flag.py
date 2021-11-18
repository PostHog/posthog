from posthog.models import Cohort, FeatureFlag, Person
from posthog.models.feature_flag import FeatureFlagMatch
from posthog.test.base import BaseTest


class TestFeatureFlag(BaseTest):
    def test_blank_flag(self):
        # Blank feature flags now default to be released for everyone
        feature_flag = self.create_feature_flag()
        self.assertEqual(feature_flag.matches("example_id"), FeatureFlagMatch())
        self.assertEqual(feature_flag.matches("another_id"), FeatureFlagMatch())

    def test_rollout_percentage(self):
        feature_flag = self.create_feature_flag(filters={"groups": [{"rollout_percentage": 50}]})
        self.assertEqual(feature_flag.matches("example_id"), FeatureFlagMatch())
        self.assertIsNone(feature_flag.matches("another_id"))

    def test_empty_group(self):
        feature_flag = self.create_feature_flag(filters={"groups": [{}]})
        self.assertEqual(feature_flag.matches("example_id"), FeatureFlagMatch())
        self.assertEqual(feature_flag.matches("another_id"), FeatureFlagMatch())

    def test_null_rollout_percentage(self):
        feature_flag = self.create_feature_flag(filters={"groups": [{"properties": [], "rollout_percentage": None}]})
        self.assertEqual(feature_flag.matches("example_id"), FeatureFlagMatch())

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

        self.assertEqual(feature_flag.matches("test_id"), FeatureFlagMatch())
        self.assertEqual(feature_flag.matches("example_id"), FeatureFlagMatch())
        self.assertIsNone(feature_flag.matches("another_id"))

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
            self.assertEqual(feature_flag.matches("example_id"), FeatureFlagMatch())
        with self.assertNumQueries(1):
            self.assertEqual(feature_flag.matches("another_id"), FeatureFlagMatch())
        self.assertIsNone(feature_flag.matches("false_id"))

    def test_user_in_cohort(self):
        Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={"$some_prop": "something"})
        cohort = Cohort.objects.create(
            team=self.team, groups=[{"properties": {"$some_prop": "something"}}], name="cohort1"
        )
        cohort.calculate_people(use_clickhouse=False)

        feature_flag = self.create_feature_flag(
            filters={"groups": [{"properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],}]}
        )

        self.assertEqual(feature_flag.matches("example_id"), FeatureFlagMatch())
        self.assertIsNone(feature_flag.matches("another_id"))

    def test_legacy_rollout_percentage(self):
        feature_flag = self.create_feature_flag(rollout_percentage=50)
        self.assertEqual(feature_flag.matches("example_id"), FeatureFlagMatch())
        self.assertIsNone(feature_flag.matches("another_id"))

    def test_legacy_property_filters(self):
        Person.objects.create(
            team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"},
        )
        Person.objects.create(
            team=self.team, distinct_ids=["another_id"], properties={"email": "example@example.com"},
        )
        feature_flag = self.create_feature_flag(filters={"properties": [{"key": "email", "value": "tim@posthog.com"}]},)
        self.assertEqual(feature_flag.matches("example_id"), FeatureFlagMatch())
        self.assertIsNone(feature_flag.matches("another_id"))

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
            self.assertEqual(feature_flag.matches("example_id"), FeatureFlagMatch())
        self.assertIsNone(feature_flag.matches("another_id"))
        self.assertIsNone(feature_flag.matches("id_number_3"))

    def test_legacy_user_in_cohort(self):
        Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={"$some_prop": "something"})
        cohort = Cohort.objects.create(
            team=self.team, groups=[{"properties": {"$some_prop": "something"}}], name="cohort1"
        )
        cohort.calculate_people(use_clickhouse=False)

        feature_flag = self.create_feature_flag(
            filters={"properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],}
        )

        self.assertEqual(feature_flag.matches("example_id"), FeatureFlagMatch())
        self.assertIsNone(feature_flag.matches("another_id"))

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

        self.assertEqual(feature_flag.matches("11"), FeatureFlagMatch(variant="first-variant"))
        self.assertEqual(feature_flag.matches("example_id"), FeatureFlagMatch(variant="second-variant"))
        self.assertEqual(feature_flag.matches("3"), FeatureFlagMatch(variant="third-variant"))

    def create_feature_flag(self, **kwargs):
        return FeatureFlag.objects.create(
            team=self.team, name="Beta feature", key="beta-feature", created_by=self.user, **kwargs
        )
