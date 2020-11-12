from posthog.api.test.base import BaseTest
from posthog.models import Cohort, FeatureFlag, Person


class TestFeatureFlag(BaseTest):
    def test_rollout_percentage(self):
        user = self._create_user("tim")
        feature_flag = FeatureFlag.objects.create(
            team=self.team, rollout_percentage=50, name="Beta feature", key="beta-feature", created_by=user,
        )
        self.assertTrue(feature_flag.distinct_id_matches("example_id"))
        self.assertFalse(feature_flag.distinct_id_matches("another_id"))

    def test_property_filters(self):
        user = self._create_user("tim")
        Person.objects.create(
            team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"},
        )
        Person.objects.create(
            team=self.team, distinct_ids=["another_id"], properties={"email": "example@example.com"},
        )
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            filters={"properties": [{"key": "email", "value": "tim@posthog.com"}]},
            name="Beta feature",
            key="beta-feature",
            created_by=user,
        )
        self.assertTrue(feature_flag.distinct_id_matches("example_id"))
        self.assertFalse(feature_flag.distinct_id_matches("another_id"))

    def test_rollout_and_property_filter(self):
        user = self._create_user("tim")
        Person.objects.create(
            team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"},
        )
        Person.objects.create(
            team=self.team, distinct_ids=["another_id"], properties={"email": "tim@posthog.com"},
        )
        Person.objects.create(
            team=self.team, distinct_ids=["id_number_3"], properties={"email": "example@example.com"},
        )
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=50,
            filters={"properties": [{"key": "email", "value": "tim@posthog.com", "type": "person"}]},
            name="Beta feature",
            key="beta-feature",
            created_by=user,
        )
        with self.assertNumQueries(1):
            self.assertTrue(feature_flag.distinct_id_matches("example_id"))
        self.assertFalse(feature_flag.distinct_id_matches("another_id"))
        self.assertFalse(feature_flag.distinct_id_matches("id_number_3"))

    def test_user_in_cohort(self):
        user = self._create_user("tim")

        person1 = Person.objects.create(
            team=self.team, distinct_ids=["example_id"], properties={"$some_prop": "something"}
        )
        cohort = Cohort.objects.create(
            team=self.team, groups=[{"properties": {"$some_prop": "something"}}], name="cohort1"
        )
        cohort.calculate_people(use_clickhouse=False)

        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            filters={"properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],},
            name="Beta feature",
            key="beta-feature",
            created_by=user,
        )

        self.assertTrue(feature_flag.distinct_id_matches("example_id"))
        self.assertFalse(feature_flag.distinct_id_matches("another_id"))
