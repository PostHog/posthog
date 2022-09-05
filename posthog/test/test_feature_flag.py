from typing import cast

from django.db import connection
from django.utils import timezone

from posthog.models import Cohort, FeatureFlag, GroupTypeMapping, Person
from posthog.models.feature_flag import (
    FeatureFlagHashKeyOverride,
    FeatureFlagMatch,
    FeatureFlagMatcher,
    FeatureFlagMatchReason,
    FlagsMatcherCache,
    get_active_feature_flags,
    hash_key_overrides,
    set_feature_flag_hash_key_overrides,
)
from posthog.models.group import Group
from posthog.test.base import BaseTest, QueryMatchingTest, snapshot_postgres_queries


class TestFeatureFlagMatcher(BaseTest, QueryMatchingTest):
    maxDiff = None

    def test_blank_flag(self):
        # Blank feature flags now default to be released for everyone
        feature_flag = self.create_feature_flag()
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

    def test_rollout_percentage(self):
        feature_flag = self.create_feature_flag(filters={"groups": [{"rollout_percentage": 50}]})
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 0),
        )

    def test_empty_group(self):
        feature_flag = self.create_feature_flag(filters={"groups": [{}]})
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

    def test_null_rollout_percentage(self):
        feature_flag = self.create_feature_flag(filters={"groups": [{"properties": [], "rollout_percentage": None}]})
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

    def test_zero_rollout_percentage(self):
        feature_flag = self.create_feature_flag(filters={"groups": [{"properties": [], "rollout_percentage": 0}]})
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 0),
        )

    def test_complicated_flag(self):
        Person.objects.create(team=self.team, distinct_ids=["test_id"], properties={"email": "test@posthog.com"})

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

        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "test_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 1),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 1),
        )

    @snapshot_postgres_queries
    def test_multiple_flags(self):
        Person.objects.create(team=self.team, distinct_ids=["test_id"], properties={"email": "test@posthog.com"})
        self.create_groups()
        feature_flag_one = self.create_feature_flag(
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
            },
            key="one",
        )
        feature_flag_always_match = self.create_feature_flag(
            filters={"groups": [{"rollout_percentage": 100}]}, key="always_match"
        )
        feature_flag_never_match = self.create_feature_flag(
            filters={"groups": [{"rollout_percentage": 0}]}, key="never_match"
        )
        feature_flag_group_match = self.create_feature_flag(
            filters={"aggregation_group_type_index": 1, "groups": [{"rollout_percentage": 100}]}, key="group_match"
        )
        feature_flag_group_no_match = self.create_feature_flag(
            filters={"aggregation_group_type_index": 1, "groups": [{"rollout_percentage": 0}]}, key="group_no_match"
        )
        feature_flag_group_property_match = self.create_feature_flag(
            filters={
                "aggregation_group_type_index": 0,
                "groups": [
                    {
                        "rollout_percentage": 100,
                        "properties": [
                            {
                                "key": "name",
                                "value": ["foo.inc"],
                                "operator": "exact",
                                "type": "group",
                                "group_type_index": 0,
                            }
                        ],
                    }
                ],
            },
            key="group_property_match",
        )
        feature_flag_group_property_match_for_different_group_key = self.create_feature_flag(
            filters={
                "aggregation_group_type_index": 0,
                "groups": [
                    {
                        "rollout_percentage": 100,
                        "properties": [
                            {
                                "key": "name",
                                "value": ["foo2.inc"],
                                "operator": "exact",
                                "type": "group",
                                "group_type_index": 0,
                            }
                        ],
                    }
                ],
            },
            key="group_property_different_match",
        )
        feature_flag_variant = self.create_feature_flag(
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                        {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                        {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 25},
                    ]
                },
            },
            key="variant",
        )

        with self.assertNumQueries(
            4
        ):  # 1 to fill group cache, 2 to match feature flags with group properties (of each type), 1 to match feature flags with person properties

            matches, reasons = FeatureFlagMatcher(
                [
                    feature_flag_one,
                    feature_flag_always_match,
                    feature_flag_never_match,
                    feature_flag_group_match,
                    feature_flag_group_no_match,
                    feature_flag_variant,
                    feature_flag_group_property_match,
                    feature_flag_group_property_match_for_different_group_key,
                ],
                "test_id",
                {"project": "group_key", "organization": "foo"},
                FlagsMatcherCache(self.team.id),
            ).get_matches()

            self.assertEqual(
                matches,
                {
                    "one": True,
                    "always_match": True,
                    "group_match": True,
                    "variant": "first-variant",
                    "group_property_match": True,
                    # never_match and group_no_match don't match
                    # group_property_different_match doesn't match because we're dealing with a different group key
                },
            )

            self.assertEqual(
                reasons,
                {
                    "one": {"reason": FeatureFlagMatchReason.CONDITION_MATCH, "condition_index": 0},
                    "always_match": {"reason": FeatureFlagMatchReason.CONDITION_MATCH, "condition_index": 0},
                    "group_match": {"reason": FeatureFlagMatchReason.CONDITION_MATCH, "condition_index": 0},
                    "variant": {"reason": FeatureFlagMatchReason.CONDITION_MATCH, "condition_index": 0},
                    "group_property_match": {"reason": FeatureFlagMatchReason.CONDITION_MATCH, "condition_index": 0},
                    "never_match": {"reason": FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, "condition_index": 0},
                    "group_no_match": {"reason": FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, "condition_index": 0},
                    "group_property_different_match": {
                        "reason": FeatureFlagMatchReason.NO_CONDITION_MATCH,
                        "condition_index": 0,
                    },
                },
            )

        with self.assertNumQueries(
            3
        ):  # 1 to fill group cache, 1 to match feature flags with group properties (only 1 group provided), 1 to match feature flags with person properties

            matches, reasons = FeatureFlagMatcher(
                [
                    feature_flag_one,
                    feature_flag_always_match,
                    feature_flag_never_match,
                    feature_flag_group_match,
                    feature_flag_group_no_match,
                    feature_flag_variant,
                    feature_flag_group_property_match,
                    feature_flag_group_property_match_for_different_group_key,
                ],
                "test_id",
                {"organization": "foo2"},
                FlagsMatcherCache(self.team.id),
            ).get_matches()

            self.assertEqual(
                matches,
                {
                    "one": True,
                    "always_match": True,
                    "variant": "first-variant",
                    "group_property_different_match": True,
                    # never_match and group_no_match don't match
                    # group_match doesn't match because no project (group type index 1) given.
                    # group_property_match doesn't match because we're dealing with a different group key
                },
            )

            self.assertEqual(
                reasons,
                {
                    "one": {"reason": FeatureFlagMatchReason.CONDITION_MATCH, "condition_index": 0},
                    "always_match": {"reason": FeatureFlagMatchReason.CONDITION_MATCH, "condition_index": 0},
                    "group_match": {"reason": FeatureFlagMatchReason.NO_GROUP_TYPE, "condition_index": None},
                    "variant": {"reason": FeatureFlagMatchReason.CONDITION_MATCH, "condition_index": 0},
                    "group_property_different_match": {
                        "reason": FeatureFlagMatchReason.CONDITION_MATCH,
                        "condition_index": 0,
                    },
                    "never_match": {"reason": FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, "condition_index": 0},
                    "group_no_match": {"reason": FeatureFlagMatchReason.NO_GROUP_TYPE, "condition_index": None},
                    "group_property_match": {"reason": FeatureFlagMatchReason.NO_CONDITION_MATCH, "condition_index": 0},
                },
            )

    def test_multi_property_filters(self):
        Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"})
        Person.objects.create(team=self.team, distinct_ids=["another_id"], properties={"email": "example@example.com"})
        Person.objects.create(team=self.team, distinct_ids=["false_id"], properties={})
        feature_flag = self.create_feature_flag(
            filters={
                "groups": [
                    {"properties": [{"key": "email", "value": "tim@posthog.com"}]},
                    {"properties": [{"key": "email", "value": "example@example.com"}]},
                ]
            }
        )
        with self.assertNumQueries(1):
            self.assertEqual(
                FeatureFlagMatcher([feature_flag], "example_id").get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )
        with self.assertNumQueries(1):
            self.assertEqual(
                FeatureFlagMatcher([feature_flag], "another_id").get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 1),
            )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "false_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 1),
        )

    def test_multi_property_filters_with_override_properties(self):
        Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"})
        Person.objects.create(team=self.team, distinct_ids=["another_id"], properties={"email": "example@example.com"})
        Person.objects.create(team=self.team, distinct_ids=["random_id"], properties={})
        feature_flag = self.create_feature_flag(
            filters={
                "groups": [
                    {"properties": [{"key": "email", "value": "tim@posthog.com"}]},
                    {"properties": [{"key": "email", "value": "example@example.com"}]},
                ]
            }
        )
        with self.assertNumQueries(1):
            self.assertEqual(
                FeatureFlagMatcher([feature_flag], "example_id", property_value_overrides={}).get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )
            # can be computed locally
            self.assertEqual(
                FeatureFlagMatcher([feature_flag], "example_id", property_value_overrides={"email": "bzz"}).get_match(
                    feature_flag
                ),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 1),
            )

        with self.assertNumQueries(1):
            self.assertEqual(
                FeatureFlagMatcher([feature_flag], "random_id").get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 1),
            )

            # can be computed locally
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag], "random_id", property_value_overrides={"email": "example@example.com"}
                ).get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 1),
            )

    def test_override_properties_where_person_doesnt_exist_yet(self):
        feature_flag = self.create_feature_flag(
            filters={
                "groups": [
                    {"properties": [{"key": "email", "value": "tim@posthog.com", "type": "person"}]},
                    {"properties": [{"key": "email", "value": "example@example.com"}]},
                ]
            }
        )
        with self.assertNumQueries(0):
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag], "example_id", property_value_overrides={"email": "tim@posthog.com"}
                ).get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )
            self.assertEqual(
                FeatureFlagMatcher([feature_flag], "example_id", property_value_overrides={"email": "bzz"}).get_match(
                    feature_flag
                ),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 1),
            )

        with self.assertNumQueries(1):
            self.assertEqual(
                FeatureFlagMatcher([feature_flag], "random_id").get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 1),
            )

        with self.assertNumQueries(0):
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag], "random_id", property_value_overrides={"email": "example@example.com"}
                ).get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 1),
            )

    def test_override_properties_where_person_doesnt_exist_yet_multiple_conditions(self):
        feature_flag = self.create_feature_flag(
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": "email", "value": "tim@posthog.com"},
                            {"key": "another_prop", "value": "slow"},
                        ],
                        "rollout_percentage": 50,
                    }
                ]
            }
        )
        with self.assertNumQueries(2):
            # None in both because all conditions don't match
            # and user doesn't exist yet
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag], "example_id", property_value_overrides={"email": "tim@posthog.com"}
                ).get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )
            self.assertEqual(
                FeatureFlagMatcher([feature_flag], "example_id", property_value_overrides={"email": "bzz"}).get_match(
                    feature_flag
                ),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )

        with self.assertNumQueries(1):
            self.assertEqual(
                FeatureFlagMatcher([feature_flag], "random_id").get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )

        with self.assertNumQueries(0):
            # Both of these match properties, but second one is outside rollout %.
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag],
                    "random_id_without_rollout",
                    property_value_overrides={"email": "tim@posthog.com", "another_prop": "slow", "blah": "blah"},
                ).get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag],
                    "random_id_within_rollout",
                    property_value_overrides={"email": "tim@posthog.com", "another_prop": "slow", "blah": "blah"},
                ).get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 0),
            )

        with self.assertNumQueries(0):
            # These don't match properties
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag],
                    "random_id_without_rollout",
                    property_value_overrides={"email": "tim@posthog.com", "another_prop": "slow2", "blah": "blah"},
                ).get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag],
                    "random_id_without_rollout",
                    property_value_overrides={"email": "tim2@posthog.com", "another_prop": "slow", "blah": "blah"},
                ).get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )

    def test_multi_property_filters_with_override_properties_with_is_not_set(self):
        Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"})
        Person.objects.create(team=self.team, distinct_ids=["another_id"], properties={"email": "example@example.com"})
        Person.objects.create(team=self.team, distinct_ids=["random_id"], properties={})
        feature_flag = self.create_feature_flag(
            filters={"groups": [{"properties": [{"key": "email", "operator": "is_not_set"}]}]}
        )
        with self.assertNumQueries(2):
            self.assertEqual(
                FeatureFlagMatcher([feature_flag], "example_id", property_value_overrides={}).get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )
            self.assertEqual(
                FeatureFlagMatcher([feature_flag], "example_id", property_value_overrides={"email": "bzz"}).get_match(
                    feature_flag
                ),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )

        with self.assertNumQueries(2):
            self.assertEqual(
                FeatureFlagMatcher([feature_flag], "random_id").get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag], "random_id", property_value_overrides={"email": "example@example.com"}
                ).get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )

    def test_user_in_cohort(self):
        Person.objects.create(team=self.team, distinct_ids=["example_id_1"], properties={"$some_prop_1": "something_1"})
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop_1", "value": "something_1", "type": "person"}]}],
            name="cohort1",
        )
        cohort.calculate_people_ch(pending_version=0)

        feature_flag: FeatureFlag = self.create_feature_flag(
            filters={"groups": [{"properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}]}]}
        )

        feature_flag.update_cohorts()

        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "example_id_1").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )

    def test_user_in_static_cohort(self):
        Person.objects.create(team_id=self.team.pk, distinct_ids=["example_id_1"])
        Person.objects.create(team_id=self.team.pk, distinct_ids=["example_id_2"])
        Person.objects.create(team_id=self.team.pk, distinct_ids=["3"])

        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, last_calculation=timezone.now())
        cohort.insert_users_by_list(["example_id_1", "example_id_2"])

        feature_flag: FeatureFlag = self.create_feature_flag(
            filters={"groups": [{"properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}]}]}
        )

        feature_flag.update_cohorts()
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "example_id_1").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "3").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )

    def test_legacy_rollout_percentage(self):
        feature_flag = self.create_feature_flag(rollout_percentage=50)
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 0),
        )

    def test_legacy_property_filters(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com"},
        )
        Person.objects.create(
            team=self.team,
            distinct_ids=["another_id"],
            properties={"email": "example@example.com"},
        )
        feature_flag = self.create_feature_flag(
            filters={"properties": [{"key": "email", "value": "tim@posthog.com"}]},
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )

    def test_legacy_rollout_and_property_filter(self):
        Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"})
        Person.objects.create(team=self.team, distinct_ids=["another_id"], properties={"email": "tim@posthog.com"})
        Person.objects.create(team=self.team, distinct_ids=["id_number_3"], properties={"email": "example@example.com"})
        feature_flag = self.create_feature_flag(
            rollout_percentage=50,
            filters={"properties": [{"key": "email", "value": "tim@posthog.com", "type": "person"}]},
        )
        with self.assertNumQueries(1):
            self.assertEqual(
                FeatureFlagMatcher([feature_flag], "example_id").get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "id_number_3").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )

    def test_legacy_user_in_cohort(self):
        Person.objects.create(team=self.team, distinct_ids=["example_id_2"], properties={"$some_prop_2": "something_2"})
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop_2", "value": "something_2", "type": "person"}]}],
            name="cohort2",
        )
        cohort.calculate_people_ch(pending_version=0)

        feature_flag: FeatureFlag = self.create_feature_flag(
            filters={"properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}]}
        )

        feature_flag.update_cohorts()

        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "example_id_2").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )

    def test_variants(self):
        feature_flag = self.create_feature_flag(
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                        {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                        {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 25},
                    ]
                },
            }
        )

        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "11").get_match(feature_flag),
            FeatureFlagMatch(
                True, variant="first-variant", reason=FeatureFlagMatchReason.CONDITION_MATCH, condition_index=0
            ),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(
                True, variant="second-variant", reason=FeatureFlagMatchReason.CONDITION_MATCH, condition_index=0
            ),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "3").get_match(feature_flag),
            FeatureFlagMatch(
                True, variant="third-variant", reason=FeatureFlagMatchReason.CONDITION_MATCH, condition_index=0
            ),
        )

    def test_flag_by_groups_with_rollout_100(self):
        self.create_groups()
        feature_flag = self.create_feature_flag(
            filters={"aggregation_group_type_index": 1, "groups": [{"rollout_percentage": 100}]}
        )

        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_GROUP_TYPE),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "", {"unknown": "group_key"}).get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_GROUP_TYPE),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "", {"organization": "group_key"}).get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_GROUP_TYPE),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "", {"project": "group_key"}).get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

    def test_flag_by_groups_with_rollout_50(self):
        self.create_groups()
        feature_flag = self.create_feature_flag(
            filters={"aggregation_group_type_index": 1, "groups": [{"rollout_percentage": 50}]}
        )

        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "", {"project": "1"}).get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "", {"project": "4"}).get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

    def test_flag_by_group_properties(self):
        self.create_groups()
        feature_flag = self.create_feature_flag(
            filters={
                "aggregation_group_type_index": 0,
                "groups": [
                    {"properties": [{"key": "name", "value": ["foo.inc"], "type": "group", "group_type_index": 0}]}
                ],
            }
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "", {"organization": "foo"}).get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "", {"organization": "bar"}).get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )

    def create_groups(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        GroupTypeMapping.objects.create(team=self.team, group_type="project", group_type_index=1)

        # Add other irrelevant groups
        for i in range(5):
            Group.objects.create(
                team=self.team,
                group_type_index=0,
                group_key=f"foo{i}",
                group_properties={"name": f"foo{i}.inc"},
                version=1,
            )
        Group.objects.create(
            team=self.team, group_type_index=0, group_key="foo", group_properties={"name": "foo.inc"}, version=1
        )
        Group.objects.create(
            team=self.team, group_type_index=0, group_key="bar", group_properties={"name": "var.inc"}, version=1
        )
        # Add other irrelevant groups
        for i in range(5):
            Group.objects.create(
                team=self.team, group_type_index=1, group_key=f"group_key{i}", group_properties={}, version=1
            )
        Group.objects.create(
            team=self.team, group_type_index=1, group_key="group_key", group_properties={"name": "var.inc"}, version=1
        )

    def create_feature_flag(self, key="beta-feature", **kwargs):
        return FeatureFlag.objects.create(team=self.team, name="Beta feature", key=key, created_by=self.user, **kwargs)


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
                    ]
                },
            },
            name="This is a feature flag with multiple variants.",
            key="multivariate-flag",
            created_by=cls.user,
            ensure_experience_continuity=True,
        )

        cls.person = Person.objects.create(
            team=cls.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com", "team": "posthog"}
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
        flags, reasons = get_active_feature_flags(self.team.pk, "other_id", {}, "example_id")
        self.assertEqual(
            flags,
            {
                "beta-feature": True,
                "multivariate-flag": "first-variant",
                "default-flag": True,
            },
        )

        self.assertEqual(
            reasons,
            {
                "beta-feature": {
                    "reason": FeatureFlagMatchReason.CONDITION_MATCH,
                    "condition_index": 0,
                },
                "multivariate-flag": {
                    "reason": FeatureFlagMatchReason.CONDITION_MATCH,
                    "condition_index": 0,
                },
                "default-flag": {
                    "reason": FeatureFlagMatchReason.CONDITION_MATCH,
                    "condition_index": 0,
                },
            },
        )


class TestFeatureFlagMatcherConsistency(BaseTest):
    # These tests are common between all libraries doing local evaluation of feature flags.
    # This ensures there are no mismatches between implementations.

    def test_simple_flag_consistency(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name="Simple flag",
            key="simple-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 45}]},
        )

        results = [
            False,
            True,
            True,
            False,
            True,
            False,
            False,
            True,
            False,
            True,
            False,
            True,
            True,
            False,
            True,
            False,
            False,
            False,
            True,
            True,
            False,
            True,
            False,
            False,
            True,
            False,
            True,
            True,
            False,
            False,
            False,
            True,
            True,
            True,
            True,
            False,
            False,
            False,
            False,
            False,
            False,
            True,
            True,
            False,
            True,
            True,
            False,
            False,
            False,
            True,
            True,
            False,
            False,
            False,
            False,
            True,
            False,
            True,
            False,
            True,
            False,
            True,
            True,
            False,
            True,
            False,
            True,
            False,
            True,
            True,
            False,
            False,
            True,
            False,
            False,
            True,
            False,
            True,
            False,
            False,
            True,
            False,
            False,
            False,
            True,
            True,
            False,
            True,
            True,
            False,
            True,
            True,
            True,
            True,
            True,
            False,
            True,
            True,
            False,
            False,
            True,
            True,
            True,
            True,
            False,
            False,
            True,
            False,
            True,
            True,
            True,
            False,
            False,
            False,
            False,
            False,
            True,
            False,
            False,
            True,
            True,
            True,
            False,
            False,
            True,
            False,
            True,
            False,
            False,
            True,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            True,
            True,
            False,
            False,
            True,
            False,
            False,
            True,
            True,
            False,
            False,
            True,
            False,
            True,
            False,
            True,
            True,
            True,
            False,
            False,
            False,
            True,
            False,
            False,
            False,
            False,
            True,
            True,
            False,
            True,
            True,
            False,
            True,
            False,
            True,
            True,
            False,
            True,
            False,
            True,
            True,
            True,
            False,
            True,
            False,
            False,
            True,
            True,
            False,
            True,
            False,
            True,
            True,
            False,
            False,
            True,
            True,
            True,
            True,
            False,
            True,
            True,
            False,
            False,
            True,
            False,
            True,
            False,
            False,
            True,
            True,
            False,
            True,
            False,
            True,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            True,
            False,
            True,
            True,
            False,
            False,
            True,
            False,
            True,
            False,
            False,
            False,
            True,
            False,
            True,
            False,
            False,
            False,
            True,
            False,
            False,
            True,
            False,
            True,
            True,
            False,
            False,
            False,
            False,
            True,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            True,
            True,
            False,
            True,
            False,
            True,
            True,
            False,
            True,
            False,
            True,
            False,
            False,
            False,
            True,
            True,
            True,
            True,
            False,
            False,
            False,
            False,
            False,
            True,
            True,
            True,
            False,
            False,
            True,
            True,
            False,
            False,
            False,
            False,
            False,
            True,
            False,
            True,
            True,
            True,
            True,
            False,
            True,
            True,
            True,
            False,
            False,
            True,
            False,
            True,
            False,
            False,
            True,
            True,
            True,
            False,
            True,
            False,
            False,
            False,
            True,
            True,
            False,
            True,
            False,
            True,
            False,
            True,
            True,
            True,
            True,
            True,
            False,
            False,
            True,
            False,
            True,
            False,
            True,
            True,
            True,
            False,
            True,
            False,
            True,
            True,
            False,
            True,
            True,
            True,
            True,
            True,
            False,
            False,
            False,
            False,
            False,
            True,
            False,
            True,
            False,
            False,
            True,
            True,
            False,
            False,
            False,
            True,
            False,
            True,
            True,
            True,
            True,
            False,
            False,
            False,
            False,
            True,
            True,
            False,
            False,
            True,
            True,
            False,
            True,
            True,
            True,
            True,
            False,
            True,
            True,
            True,
            False,
            False,
            True,
            True,
            False,
            False,
            True,
            False,
            False,
            True,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            True,
            True,
            False,
            False,
            True,
            False,
            False,
            True,
            False,
            True,
            False,
            False,
            True,
            False,
            False,
            False,
            False,
            False,
            False,
            True,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            True,
            True,
            True,
            False,
            False,
            False,
            True,
            False,
            True,
            False,
            False,
            False,
            True,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            True,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            True,
            False,
            True,
            False,
            True,
            True,
            True,
            False,
            False,
            False,
            True,
            True,
            True,
            False,
            True,
            False,
            True,
            True,
            False,
            False,
            False,
            True,
            False,
            False,
            False,
            False,
            True,
            False,
            True,
            False,
            True,
            True,
            False,
            True,
            False,
            False,
            False,
            True,
            False,
            False,
            True,
            True,
            False,
            True,
            False,
            False,
            False,
            False,
            False,
            False,
            True,
            True,
            False,
            False,
            True,
            False,
            False,
            True,
            True,
            True,
            False,
            False,
            False,
            True,
            False,
            False,
            False,
            False,
            True,
            False,
            True,
            False,
            False,
            False,
            True,
            False,
            True,
            True,
            False,
            True,
            False,
            True,
            False,
            True,
            False,
            False,
            True,
            False,
            False,
            True,
            False,
            True,
            False,
            True,
            False,
            True,
            False,
            False,
            True,
            True,
            True,
            True,
            False,
            True,
            False,
            False,
            False,
            False,
            False,
            True,
            False,
            False,
            True,
            False,
            False,
            True,
            True,
            False,
            False,
            False,
            False,
            True,
            True,
            True,
            False,
            False,
            True,
            False,
            False,
            True,
            True,
            True,
            True,
            False,
            False,
            False,
            True,
            False,
            False,
            False,
            True,
            False,
            False,
            True,
            True,
            True,
            True,
            False,
            False,
            True,
            True,
            False,
            True,
            False,
            True,
            False,
            False,
            True,
            True,
            False,
            True,
            True,
            True,
            True,
            False,
            False,
            True,
            False,
            False,
            True,
            True,
            False,
            True,
            False,
            True,
            False,
            False,
            True,
            False,
            False,
            False,
            False,
            True,
            True,
            True,
            False,
            True,
            False,
            False,
            True,
            False,
            False,
            True,
            False,
            False,
            False,
            False,
            True,
            False,
            True,
            False,
            True,
            True,
            False,
            False,
            True,
            False,
            True,
            True,
            True,
            False,
            False,
            False,
            False,
            True,
            True,
            False,
            True,
            False,
            False,
            False,
            True,
            False,
            False,
            False,
            False,
            True,
            True,
            True,
            False,
            False,
            False,
            True,
            True,
            True,
            True,
            False,
            True,
            True,
            False,
            True,
            True,
            True,
            False,
            True,
            False,
            False,
            True,
            False,
            True,
            True,
            True,
            True,
            False,
            True,
            False,
            True,
            False,
            True,
            False,
            False,
            True,
            True,
            False,
            False,
            True,
            False,
            True,
            False,
            False,
            False,
            False,
            True,
            False,
            True,
            False,
            False,
            False,
            True,
            True,
            True,
            False,
            False,
            False,
            True,
            False,
            True,
            True,
            False,
            False,
            False,
            False,
            False,
            True,
            False,
            True,
            False,
            False,
            True,
            True,
            False,
            True,
            True,
            True,
            True,
            False,
            False,
            True,
            False,
            False,
            True,
            False,
            True,
            False,
            True,
            True,
            False,
            False,
            False,
            True,
            False,
            True,
            True,
            False,
            False,
            False,
            True,
            False,
            True,
            False,
            True,
            True,
            False,
            True,
            False,
            False,
            True,
            False,
            False,
            False,
            True,
            True,
            True,
            False,
            False,
            False,
            False,
            False,
            True,
            False,
            False,
            True,
            True,
            True,
            True,
            True,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            True,
            True,
            True,
            False,
            False,
            True,
            True,
            False,
            True,
            True,
            False,
            True,
            False,
            True,
            False,
            False,
            False,
            True,
            False,
            False,
            True,
            False,
            False,
            True,
            True,
            True,
            True,
            False,
            False,
            True,
            False,
            True,
            True,
            False,
            False,
            True,
            False,
            False,
            True,
            True,
            False,
            True,
            False,
            False,
            True,
            True,
            True,
            False,
            False,
            False,
            False,
            False,
            True,
            False,
            True,
            False,
            False,
            False,
            False,
            False,
            True,
            True,
            False,
            True,
            True,
            True,
            False,
            False,
            False,
            False,
            True,
            True,
            True,
            True,
            False,
            True,
            True,
            False,
            True,
            False,
            True,
            False,
            True,
            False,
            False,
            False,
            False,
            True,
            True,
            True,
            True,
            False,
            False,
            True,
            False,
            True,
            True,
            False,
            False,
            False,
            False,
            False,
            False,
            True,
            False,
            True,
            False,
            True,
            True,
            False,
            False,
            True,
            True,
            True,
            True,
            False,
            False,
            True,
            False,
            True,
            True,
            False,
            False,
            True,
            True,
            True,
            False,
            True,
            False,
            False,
            True,
            True,
            False,
            False,
            False,
            True,
            False,
            False,
            True,
            False,
            False,
            False,
            True,
            True,
            True,
            True,
            False,
            True,
            False,
            True,
            False,
            True,
            False,
            True,
            False,
            False,
            True,
            False,
            False,
            True,
            False,
            True,
            True,
        ]

        for i in range(1000):
            distinctID = f"distinct_id_{i}"

            feature_flag_match = FeatureFlagMatcher([feature_flag], distinctID).get_match(feature_flag)

            if results[i]:
                self.assertEqual(
                    feature_flag_match, FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0)
                )
            else:
                self.assertEqual(
                    feature_flag_match, FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 0)
                )

    def test_multivariate_flag_consistency(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name="Multivariate flag",
            key="multivariate-flag",
            created_by=self.user,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 55}],
                "multivariate": {
                    "variants": [
                        {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                        {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 20},
                        {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 20},
                        {"key": "fourth-variant", "name": "Fourth Variant", "rollout_percentage": 5},
                        {"key": "fifth-variant", "name": "Fifth Variant", "rollout_percentage": 5},
                    ]
                },
            },
        )

        results = [
            "second-variant",
            "second-variant",
            "first-variant",
            False,
            False,
            "second-variant",
            "first-variant",
            False,
            False,
            False,
            "first-variant",
            "third-variant",
            False,
            "first-variant",
            "second-variant",
            "first-variant",
            False,
            False,
            "fourth-variant",
            "first-variant",
            False,
            "third-variant",
            False,
            False,
            False,
            "first-variant",
            "first-variant",
            "first-variant",
            "first-variant",
            "first-variant",
            "first-variant",
            "third-variant",
            False,
            "third-variant",
            "second-variant",
            "first-variant",
            False,
            "third-variant",
            False,
            False,
            "first-variant",
            "second-variant",
            False,
            "first-variant",
            "first-variant",
            "second-variant",
            False,
            "first-variant",
            False,
            False,
            "first-variant",
            "first-variant",
            "first-variant",
            "second-variant",
            "first-variant",
            False,
            "second-variant",
            "second-variant",
            "third-variant",
            "second-variant",
            "first-variant",
            False,
            "first-variant",
            "second-variant",
            "fourth-variant",
            False,
            "first-variant",
            "first-variant",
            "first-variant",
            False,
            "first-variant",
            "second-variant",
            False,
            "third-variant",
            False,
            False,
            False,
            False,
            False,
            False,
            "first-variant",
            "fifth-variant",
            False,
            "second-variant",
            "first-variant",
            "second-variant",
            False,
            "third-variant",
            "third-variant",
            False,
            False,
            False,
            False,
            "third-variant",
            False,
            False,
            "first-variant",
            "first-variant",
            False,
            "third-variant",
            "third-variant",
            False,
            "third-variant",
            "second-variant",
            "third-variant",
            False,
            False,
            "second-variant",
            "first-variant",
            False,
            False,
            "first-variant",
            False,
            False,
            False,
            False,
            "first-variant",
            "first-variant",
            "first-variant",
            False,
            False,
            False,
            "first-variant",
            "first-variant",
            False,
            "first-variant",
            "first-variant",
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            "first-variant",
            "first-variant",
            "first-variant",
            "first-variant",
            "second-variant",
            "first-variant",
            "first-variant",
            "first-variant",
            "second-variant",
            False,
            "second-variant",
            "first-variant",
            "second-variant",
            "first-variant",
            False,
            "second-variant",
            "second-variant",
            False,
            "first-variant",
            False,
            False,
            False,
            "third-variant",
            "first-variant",
            False,
            False,
            "first-variant",
            False,
            False,
            False,
            False,
            "first-variant",
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            "first-variant",
            "first-variant",
            "third-variant",
            "first-variant",
            "first-variant",
            False,
            False,
            "first-variant",
            False,
            False,
            "fifth-variant",
            "second-variant",
            False,
            "second-variant",
            False,
            "first-variant",
            "third-variant",
            "first-variant",
            "fifth-variant",
            "third-variant",
            False,
            False,
            "fourth-variant",
            False,
            False,
            False,
            False,
            "third-variant",
            False,
            False,
            "third-variant",
            False,
            "first-variant",
            "second-variant",
            "second-variant",
            "second-variant",
            False,
            "first-variant",
            "third-variant",
            "first-variant",
            "first-variant",
            False,
            False,
            False,
            False,
            False,
            "first-variant",
            "first-variant",
            "first-variant",
            "second-variant",
            False,
            False,
            False,
            "second-variant",
            False,
            False,
            "first-variant",
            False,
            "first-variant",
            False,
            False,
            "first-variant",
            "first-variant",
            "first-variant",
            "first-variant",
            "third-variant",
            "first-variant",
            "third-variant",
            "first-variant",
            "first-variant",
            "second-variant",
            "third-variant",
            "third-variant",
            False,
            "second-variant",
            "first-variant",
            False,
            "second-variant",
            "first-variant",
            False,
            "first-variant",
            False,
            False,
            "first-variant",
            "fifth-variant",
            "first-variant",
            False,
            False,
            False,
            False,
            "first-variant",
            "first-variant",
            "second-variant",
            False,
            "second-variant",
            "third-variant",
            "third-variant",
            False,
            "first-variant",
            "third-variant",
            False,
            False,
            "first-variant",
            False,
            "third-variant",
            "first-variant",
            False,
            "third-variant",
            "first-variant",
            "first-variant",
            False,
            "first-variant",
            "second-variant",
            "second-variant",
            "first-variant",
            False,
            False,
            False,
            "second-variant",
            False,
            False,
            "first-variant",
            "first-variant",
            False,
            "third-variant",
            False,
            "first-variant",
            False,
            "third-variant",
            False,
            "third-variant",
            "second-variant",
            "first-variant",
            False,
            False,
            "first-variant",
            "third-variant",
            "first-variant",
            "second-variant",
            "fifth-variant",
            False,
            False,
            "first-variant",
            False,
            False,
            False,
            "third-variant",
            False,
            "second-variant",
            "first-variant",
            False,
            False,
            False,
            False,
            "third-variant",
            False,
            False,
            "third-variant",
            False,
            False,
            "first-variant",
            "third-variant",
            False,
            False,
            "first-variant",
            False,
            False,
            "fourth-variant",
            "fourth-variant",
            "third-variant",
            "second-variant",
            "first-variant",
            "third-variant",
            "fifth-variant",
            False,
            "first-variant",
            "fifth-variant",
            False,
            "first-variant",
            "first-variant",
            "first-variant",
            False,
            False,
            False,
            "second-variant",
            "fifth-variant",
            "second-variant",
            "first-variant",
            "first-variant",
            "second-variant",
            False,
            False,
            "third-variant",
            False,
            "second-variant",
            "fifth-variant",
            False,
            "third-variant",
            "first-variant",
            False,
            False,
            "fourth-variant",
            False,
            False,
            "second-variant",
            False,
            False,
            "first-variant",
            "fourth-variant",
            "first-variant",
            "second-variant",
            False,
            False,
            False,
            "first-variant",
            "third-variant",
            "third-variant",
            False,
            "first-variant",
            "first-variant",
            "first-variant",
            False,
            "first-variant",
            False,
            "first-variant",
            "third-variant",
            "third-variant",
            False,
            False,
            "first-variant",
            False,
            False,
            "second-variant",
            "second-variant",
            "first-variant",
            "first-variant",
            "first-variant",
            False,
            "fifth-variant",
            "first-variant",
            False,
            False,
            False,
            "second-variant",
            "third-variant",
            "first-variant",
            "fourth-variant",
            "first-variant",
            "third-variant",
            False,
            "first-variant",
            "first-variant",
            False,
            "third-variant",
            "first-variant",
            "first-variant",
            "third-variant",
            False,
            "fourth-variant",
            "fifth-variant",
            "first-variant",
            "first-variant",
            False,
            False,
            False,
            "first-variant",
            "first-variant",
            "first-variant",
            False,
            "first-variant",
            "first-variant",
            "second-variant",
            "first-variant",
            False,
            "first-variant",
            "second-variant",
            "first-variant",
            False,
            "first-variant",
            "second-variant",
            False,
            "first-variant",
            "first-variant",
            False,
            "first-variant",
            False,
            "first-variant",
            False,
            "first-variant",
            False,
            False,
            False,
            "third-variant",
            "third-variant",
            "first-variant",
            False,
            False,
            "second-variant",
            "third-variant",
            "first-variant",
            "first-variant",
            False,
            False,
            False,
            "second-variant",
            "first-variant",
            False,
            "first-variant",
            "third-variant",
            False,
            "first-variant",
            False,
            False,
            False,
            "first-variant",
            "third-variant",
            "third-variant",
            False,
            False,
            False,
            False,
            "third-variant",
            "fourth-variant",
            "fourth-variant",
            "first-variant",
            "second-variant",
            False,
            "first-variant",
            False,
            "second-variant",
            "first-variant",
            "third-variant",
            False,
            "third-variant",
            False,
            "first-variant",
            "first-variant",
            "third-variant",
            False,
            False,
            False,
            "fourth-variant",
            "second-variant",
            "first-variant",
            False,
            False,
            "first-variant",
            "fourth-variant",
            False,
            "first-variant",
            "third-variant",
            "first-variant",
            False,
            False,
            "third-variant",
            False,
            "first-variant",
            False,
            "first-variant",
            "first-variant",
            "third-variant",
            "second-variant",
            "fourth-variant",
            False,
            "first-variant",
            False,
            False,
            False,
            False,
            "second-variant",
            "first-variant",
            "second-variant",
            False,
            "first-variant",
            False,
            "first-variant",
            "first-variant",
            False,
            "first-variant",
            "first-variant",
            "second-variant",
            "third-variant",
            "first-variant",
            "first-variant",
            "first-variant",
            False,
            False,
            False,
            "third-variant",
            False,
            "first-variant",
            "first-variant",
            "first-variant",
            "third-variant",
            "first-variant",
            "first-variant",
            "second-variant",
            "first-variant",
            "fifth-variant",
            "fourth-variant",
            "first-variant",
            "second-variant",
            False,
            "fourth-variant",
            False,
            False,
            False,
            "fourth-variant",
            False,
            False,
            "third-variant",
            False,
            False,
            False,
            "first-variant",
            "third-variant",
            "third-variant",
            "second-variant",
            "first-variant",
            "second-variant",
            "first-variant",
            False,
            "first-variant",
            False,
            False,
            False,
            False,
            False,
            "first-variant",
            "first-variant",
            False,
            "second-variant",
            False,
            False,
            "first-variant",
            False,
            "second-variant",
            "first-variant",
            "first-variant",
            "first-variant",
            "third-variant",
            "second-variant",
            False,
            False,
            "fifth-variant",
            "third-variant",
            False,
            False,
            "first-variant",
            False,
            False,
            False,
            "first-variant",
            "second-variant",
            "third-variant",
            "third-variant",
            False,
            False,
            "first-variant",
            False,
            "third-variant",
            "first-variant",
            False,
            False,
            False,
            False,
            "fourth-variant",
            "first-variant",
            False,
            False,
            False,
            "third-variant",
            False,
            False,
            "second-variant",
            "first-variant",
            False,
            False,
            "second-variant",
            "third-variant",
            "first-variant",
            "first-variant",
            False,
            "first-variant",
            "first-variant",
            False,
            False,
            "second-variant",
            "third-variant",
            "second-variant",
            "third-variant",
            False,
            False,
            "first-variant",
            False,
            False,
            "first-variant",
            False,
            "second-variant",
            False,
            False,
            False,
            False,
            "first-variant",
            False,
            "third-variant",
            False,
            "first-variant",
            False,
            False,
            "second-variant",
            "third-variant",
            "second-variant",
            "fourth-variant",
            "first-variant",
            "first-variant",
            "first-variant",
            False,
            "first-variant",
            False,
            "second-variant",
            False,
            False,
            False,
            False,
            False,
            "first-variant",
            False,
            False,
            False,
            False,
            False,
            "first-variant",
            False,
            "second-variant",
            False,
            False,
            False,
            False,
            "second-variant",
            False,
            "first-variant",
            False,
            "third-variant",
            False,
            False,
            "first-variant",
            "third-variant",
            False,
            "third-variant",
            False,
            False,
            "second-variant",
            False,
            "first-variant",
            "second-variant",
            "first-variant",
            False,
            False,
            False,
            False,
            False,
            "second-variant",
            False,
            False,
            "first-variant",
            "third-variant",
            False,
            "first-variant",
            False,
            False,
            False,
            False,
            False,
            "first-variant",
            "second-variant",
            False,
            False,
            False,
            "first-variant",
            "first-variant",
            "fifth-variant",
            False,
            False,
            False,
            "first-variant",
            False,
            "third-variant",
            False,
            False,
            "second-variant",
            False,
            False,
            False,
            False,
            False,
            "fourth-variant",
            "second-variant",
            "first-variant",
            "second-variant",
            False,
            "second-variant",
            False,
            "second-variant",
            False,
            "first-variant",
            False,
            "first-variant",
            "first-variant",
            False,
            "second-variant",
            False,
            "first-variant",
            False,
            "fifth-variant",
            False,
            "first-variant",
            "first-variant",
            False,
            False,
            False,
            "first-variant",
            False,
            "first-variant",
            "third-variant",
            False,
            False,
            "first-variant",
            "first-variant",
            False,
            False,
            "fifth-variant",
            False,
            False,
            "third-variant",
            False,
            "third-variant",
            "first-variant",
            "first-variant",
            "third-variant",
            "third-variant",
            False,
            "first-variant",
            False,
            False,
            False,
            False,
            False,
            "first-variant",
            False,
            False,
            False,
            False,
            "second-variant",
            "first-variant",
            "second-variant",
            "first-variant",
            False,
            "fifth-variant",
            "first-variant",
            False,
            False,
            "fourth-variant",
            "first-variant",
            "first-variant",
            False,
            False,
            "fourth-variant",
            "first-variant",
            False,
            "second-variant",
            "third-variant",
            "third-variant",
            "first-variant",
            "first-variant",
            False,
            False,
            False,
            "first-variant",
            "first-variant",
            "first-variant",
            False,
            "third-variant",
            "third-variant",
            "third-variant",
            False,
            False,
            "first-variant",
            "first-variant",
            False,
            "second-variant",
            False,
            False,
            "second-variant",
            False,
            "third-variant",
            "first-variant",
            "second-variant",
            "fifth-variant",
            "first-variant",
            "first-variant",
            False,
            "first-variant",
            "fifth-variant",
            False,
            False,
            False,
            "third-variant",
            "first-variant",
            "first-variant",
            "second-variant",
            "fourth-variant",
            "first-variant",
            "second-variant",
            "first-variant",
            False,
            False,
            False,
            "second-variant",
            "third-variant",
            False,
            False,
            "first-variant",
            False,
            False,
            False,
            False,
            False,
            False,
            "first-variant",
            "first-variant",
            False,
            "third-variant",
            False,
            "first-variant",
            False,
            "third-variant",
            "third-variant",
            "first-variant",
            "first-variant",
            False,
            "second-variant",
            False,
            "second-variant",
            "first-variant",
            False,
            False,
            False,
            "second-variant",
            False,
            "third-variant",
            False,
            "first-variant",
            "fifth-variant",
            "first-variant",
            "first-variant",
            False,
            False,
            "first-variant",
            False,
            False,
            False,
            "first-variant",
            "fourth-variant",
            "first-variant",
            "first-variant",
            "first-variant",
            "fifth-variant",
            False,
            False,
            False,
            "second-variant",
            False,
            False,
            False,
            "first-variant",
            "first-variant",
            False,
            False,
            "first-variant",
            "first-variant",
            "second-variant",
            "first-variant",
            "first-variant",
            "first-variant",
            "first-variant",
            "first-variant",
            "third-variant",
            "first-variant",
            False,
            "second-variant",
            False,
            False,
            "third-variant",
            "second-variant",
            "third-variant",
            False,
            "first-variant",
            "third-variant",
            "second-variant",
            "first-variant",
            "third-variant",
            False,
            False,
            "first-variant",
            "first-variant",
            False,
            False,
            False,
            "first-variant",
            "third-variant",
            "second-variant",
            "first-variant",
            "first-variant",
            "first-variant",
            False,
            "third-variant",
            "second-variant",
            "third-variant",
            False,
            False,
            "third-variant",
            "first-variant",
            False,
            "first-variant",
        ]

        for i in range(1000):
            distinctID = f"distinct_id_{i}"

            feature_flag_match = FeatureFlagMatcher([feature_flag], distinctID).get_match(feature_flag)

            if results[i]:
                self.assertEqual(
                    feature_flag_match,
                    FeatureFlagMatch(
                        True,
                        variant=cast(str, results[i]),
                        reason=FeatureFlagMatchReason.CONDITION_MATCH,
                        condition_index=0,
                    ),
                )
            else:
                self.assertEqual(
                    feature_flag_match, FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 0)
                )
