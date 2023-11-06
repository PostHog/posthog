import concurrent.futures
from typing import cast
from unittest.mock import patch

from django.core.cache import cache
from django.db import IntegrityError, connection
from django.test import TransactionTestCase
from django.utils import timezone
import pytest

from posthog.models import Cohort, FeatureFlag, GroupTypeMapping, Person
from posthog.models.feature_flag import get_feature_flags_for_team_in_cache
from posthog.models.feature_flag.flag_matching import (
    FeatureFlagHashKeyOverride,
    FeatureFlagMatch,
    FeatureFlagMatcher,
    FeatureFlagMatchReason,
    FlagsMatcherCache,
    get_all_feature_flags,
    get_feature_flag_hash_key_overrides,
    set_feature_flag_hash_key_overrides,
)
from posthog.models.group import Group
from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.user import User
from posthog.test.base import (
    BaseTest,
    QueryMatchingTest,
    snapshot_postgres_queries,
    snapshot_postgres_queries_context,
)


class TestFeatureFlagCohortExpansion(BaseTest):
    maxDiff = None

    def test_cohort_expansion(self):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "email",
                            "value": ["@posthog.com"],
                            "type": "person",
                            "operator": "icontains",
                        }
                    ]
                }
            ],
        )
        flag: FeatureFlag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            active=True,
            key="active-flag",
            filters={"groups": [{"properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}]}]},
        )
        self.assertEqual(
            flag.transform_cohort_filters_for_easy_evaluation(),
            [
                {
                    "properties": [
                        {
                            "key": "email",
                            "operator": "icontains",
                            "type": "person",
                            "value": ["@posthog.com"],
                        }
                    ],
                    "rollout_percentage": None,
                }
            ],
        )

    def test_cohort_expansion_with_negation(self):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "email",
                            "value": ["@posthog.com"],
                            "type": "person",
                            "operator": "icontains",
                            "negation": True,
                        }
                    ]
                }
            ],
        )
        flag: FeatureFlag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            active=True,
            key="active-flag",
            filters={"groups": [{"properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}]}]},
        )
        self.assertEqual(
            flag.transform_cohort_filters_for_easy_evaluation(),
            [{"properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}]}],
        )

    def test_cohort_expansion_multiple_properties(self):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "email",
                            "value": ["@posthog.com"],
                            "type": "person",
                            "operator": "icontains",
                        },
                        {
                            "key": "name",
                            "value": ["posthog"],
                            "type": "person",
                            "operator": "icontains",
                        },
                    ]
                }
            ],
        )
        flag: FeatureFlag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            active=True,
            key="active-flag",
            filters={"groups": [{"properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}]}]},
        )
        self.assertEqual(
            flag.transform_cohort_filters_for_easy_evaluation(),
            [
                {
                    "properties": [
                        {
                            "key": "email",
                            "operator": "icontains",
                            "type": "person",
                            "value": ["@posthog.com"],
                        },
                        {
                            "key": "name",
                            "value": ["posthog"],
                            "type": "person",
                            "operator": "icontains",
                        },
                    ],
                    "rollout_percentage": None,
                }
            ],
        )

    def test_cohort_property_group(self):
        cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$some_prop",
                                    "value": "nomatchihope",
                                    "type": "person",
                                },
                                {
                                    "key": "$some_prop2",
                                    "value": "nomatchihope2",
                                    "type": "person",
                                },
                            ],
                        }
                    ],
                }
            },
            name="cohort1",
        )
        flag: FeatureFlag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            active=True,
            key="active-flag",
            filters={
                "groups": [
                    {
                        "properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],
                        "rollout_percentage": 50,
                    }
                ]
            },
        )
        self.assertEqual(
            flag.transform_cohort_filters_for_easy_evaluation(),
            [
                {
                    "properties": [{"key": "$some_prop", "value": "nomatchihope", "type": "person"}],
                    "rollout_percentage": 50,
                },
                {
                    "properties": [
                        {
                            "key": "$some_prop2",
                            "value": "nomatchihope2",
                            "type": "person",
                        }
                    ],
                    "rollout_percentage": 50,
                },
            ],
        )

    def test_behavioral_cohorts(self):
        cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$some_prop",
                                    "value": "nomatchihope",
                                    "type": "person",
                                },
                                {
                                    "key": "$some_prop2",
                                    "value": "nomatchihope2",
                                    "type": "person",
                                },
                                {
                                    "key": "$pageview",
                                    "event_type": "events",
                                    "time_value": 1,
                                    "time_interval": "week",
                                    "value": "performed_event",
                                    "type": "behavioral",
                                },
                            ],
                        }
                    ],
                }
            },
            name="cohort1",
        )
        flag: FeatureFlag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            active=True,
            key="active-flag",
            filters={
                "groups": [
                    {
                        "properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],
                        "rollout_percentage": 50,
                    }
                ]
            },
        )
        self.assertEqual(
            flag.transform_cohort_filters_for_easy_evaluation(),
            [
                {
                    "properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],
                    "rollout_percentage": 50,
                }
            ],
        )

    def test_multiple_cohorts(self):
        cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$some_prop",
                                    "value": "nomatchihope",
                                    "type": "person",
                                },
                                {
                                    "key": "$some_prop2",
                                    "value": "nomatchihope2",
                                    "type": "person",
                                },
                            ],
                        }
                    ],
                }
            },
            name="cohort1",
        )

        cohort2 = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "$some_prop",
                                    "value": "nomatchihope",
                                    "type": "person",
                                },
                                {
                                    "key": "$some_prop2",
                                    "value": "nomatchihope2",
                                    "type": "person",
                                },
                            ],
                        }
                    ],
                }
            },
            name="cohort2",
        )
        flag: FeatureFlag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            active=True,
            key="active-flag",
            filters={
                "groups": [
                    {
                        "properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],
                        "rollout_percentage": 50,
                    },
                    {
                        "properties": [{"key": "id", "value": cohort2.pk, "type": "cohort"}],
                        "rollout_percentage": 50,
                    },
                ]
            },
        )

        # even though it's technically possible to express this specific case in feature flag terms,
        # the effort isn't worth it. Complexity here leads to bugs, where correctness is paramount.
        self.assertEqual(flag.transform_cohort_filters_for_easy_evaluation(), flag.conditions)

    def test_cohort_thats_impossible_to_expand(self):
        cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$some_prop",
                                    "value": "nomatchihope",
                                    "type": "person",
                                },
                                {
                                    "key": "$some_prop2",
                                    "value": "nomatchihope2",
                                    "type": "person",
                                },
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "$some_prop3",
                                    "value": "nomatchihope",
                                    "type": "person",
                                },
                                {
                                    "key": "$some_prop4",
                                    "value": "nomatchihope2",
                                    "type": "person",
                                },
                            ],
                        },
                    ],
                }
            },
            name="cohort1",
        )

        flag: FeatureFlag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            active=True,
            key="active-flag",
            filters={
                "groups": [
                    {
                        "properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],
                        "rollout_percentage": 50,
                    },
                ]
            },
        )

        self.assertEqual(flag.transform_cohort_filters_for_easy_evaluation(), flag.conditions)

    def test_feature_flag_preventing_simple_cohort_expansion(self):
        cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$some_prop",
                                    "value": "nomatchihope",
                                    "type": "person",
                                },
                                {
                                    "key": "$some_prop2",
                                    "value": "nomatchihope2",
                                    "type": "person",
                                },
                            ],
                        }
                    ],
                }
            },
            name="cohort1",
        )

        flag: FeatureFlag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            active=True,
            key="active-flag",
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": "id", "value": cohort.pk, "type": "cohort"},
                            {"key": "name", "value": "name", "type": "person"},
                        ],
                        "rollout_percentage": 50,
                    },
                ]
            },
        )

        self.assertEqual(flag.transform_cohort_filters_for_easy_evaluation(), flag.conditions)

    def test_feature_flag_with_additional_conditions_playing_well_with_complex_cohort_expansion(self):
        cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "$some_prop",
                                    "value": "nomatchihope",
                                    "type": "person",
                                },
                                {
                                    "key": "$some_prop2",
                                    "value": "nomatchihope2",
                                    "type": "person",
                                },
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "$name",
                                    "value": "nomatchihope",
                                    "type": "person",
                                },
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "$email",
                                    "value": "nomatchihope",
                                    "type": "person",
                                },
                            ],
                        },
                    ],
                }
            },
            name="cohort1",
        )

        flag: FeatureFlag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            active=True,
            key="active-flag",
            filters={
                "groups": [
                    {
                        "properties": [{"key": "name_above", "value": "name", "type": "person"}],
                        "rollout_percentage": 50,
                    },
                    {
                        "properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],
                        "rollout_percentage": 50,
                    },
                    {
                        "properties": [{"key": "name", "value": "name", "type": "person"}],
                        "rollout_percentage": 50,
                    },
                ]
            },
        )

        self.assertEqual(
            flag.transform_cohort_filters_for_easy_evaluation(),
            [
                {
                    "properties": [{"key": "name_above", "value": "name", "type": "person"}],
                    "rollout_percentage": 50,
                },
                {
                    "properties": [{"key": "name", "value": "name", "type": "person"}],
                    "rollout_percentage": 50,
                },
                {
                    "properties": [
                        {
                            "key": "$some_prop",
                            "value": "nomatchihope",
                            "type": "person",
                        },
                        {
                            "key": "$some_prop2",
                            "value": "nomatchihope2",
                            "type": "person",
                        },
                    ],
                    "rollout_percentage": 50,
                },
                {
                    "properties": [
                        {"key": "$name", "value": "nomatchihope", "type": "person"},
                    ],
                    "rollout_percentage": 50,
                },
                {
                    "properties": [
                        {"key": "$email", "value": "nomatchihope", "type": "person"},
                    ],
                    "rollout_percentage": 50,
                },
            ],
        )

    def test_complex_cohort_expansion_that_is_simplified_via_clearing_excess_levels(self):
        cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$some_prop",
                                    "value": "nomatchihope",
                                    "type": "person",
                                },
                            ],
                        },
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$name",
                                    "value": "nomatchihope",
                                    "type": "person",
                                },
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "$email",
                                    "value": "nomatchihope",
                                    "type": "person",
                                },
                            ],
                        },
                    ],
                }
            },
            name="cohort1",
        )

        flag: FeatureFlag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            active=True,
            key="active-flag",
            filters={
                "groups": [
                    {
                        "properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],
                        "rollout_percentage": 50,
                    },
                    {
                        "properties": [{"key": "name", "value": "name", "type": "person"}],
                        "rollout_percentage": 50,
                    },
                ]
            },
        )

        self.assertEqual(
            flag.transform_cohort_filters_for_easy_evaluation(),
            [
                {
                    "properties": [{"key": "name", "value": "name", "type": "person"}],
                    "rollout_percentage": 50,
                },
                {
                    "properties": [{"key": "$some_prop", "value": "nomatchihope", "type": "person"}],
                    "rollout_percentage": 50,
                },
                {
                    "properties": [{"key": "$name", "value": "nomatchihope", "type": "person"}],
                    "rollout_percentage": 50,
                },
                {
                    "properties": [{"key": "$email", "value": "nomatchihope", "type": "person"}],
                    "rollout_percentage": 50,
                },
            ],
        )


class TestModelCache(BaseTest):
    def setUp(self):
        cache.clear()
        return super().setUp()

    def test_save_updates_cache(self):
        initial_cached_flags = get_feature_flags_for_team_in_cache(self.team.pk)
        self.assertIsNone(initial_cached_flags)

        key = "test-flag"

        flag = FeatureFlag.objects.create(
            team=self.team,
            name="Beta feature",
            key=key,
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
        )

        cached_flags = get_feature_flags_for_team_in_cache(self.team.pk)
        assert cached_flags is not None
        self.assertEqual(1, len(cached_flags))
        self.assertEqual(cached_flags[0].key, key)
        self.assertEqual(
            cached_flags[0].filters,
            {
                "groups": [{"properties": [], "rollout_percentage": None}],
            },
        )
        self.assertEqual(cached_flags[0].name, "Beta feature")
        self.assertEqual(cached_flags[0].active, True)
        self.assertEqual(cached_flags[0].deleted, False)

        flag.name = "New name"
        flag.key = "new-key"
        flag.save()

        cached_flags = get_feature_flags_for_team_in_cache(self.team.pk)
        assert cached_flags is not None
        self.assertEqual(1, len(cached_flags))
        self.assertEqual(cached_flags[0].key, "new-key")
        self.assertEqual(
            cached_flags[0].filters,
            {
                "groups": [{"properties": [], "rollout_percentage": None}],
            },
        )
        self.assertEqual(cached_flags[0].name, "New name")
        self.assertEqual(cached_flags[0].active, True)
        self.assertEqual(cached_flags[0].deleted, False)

        flag.deleted = True
        flag.save()

        cached_flags = get_feature_flags_for_team_in_cache(self.team.pk)
        assert cached_flags is not None
        self.assertEqual(0, len(cached_flags))

        flag.deleted = False
        flag.save()

        cached_flags = get_feature_flags_for_team_in_cache(self.team.pk)
        assert cached_flags is not None
        self.assertEqual(1, len(cached_flags))

        flag.active = False
        flag.save()

        cached_flags = get_feature_flags_for_team_in_cache(self.team.pk)
        assert cached_flags is not None
        self.assertEqual(0, len(cached_flags))

        flag.active = True
        flag.save()

        cached_flags = get_feature_flags_for_team_in_cache(self.team.pk)
        assert cached_flags is not None
        self.assertEqual(1, len(cached_flags))

        flag.delete()
        cached_flags = get_feature_flags_for_team_in_cache(self.team.pk)
        assert cached_flags is not None
        self.assertEqual(0, len(cached_flags))


class TestFeatureFlagMatcher(BaseTest, QueryMatchingTest):
    maxDiff = None

    def match_flag(self, flag: FeatureFlag, distinct_id: str = "test_id", **kwargs):
        return FeatureFlagMatcher([flag], distinct_id, **kwargs).get_match(flag)

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

    def test_coercion_of_strings_and_numbers(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["307"],
            properties={
                "Distinct Id": 307,
                "Organizer Id": "307",
            },
        )

        feature_flag = self.create_feature_flag(
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "Organizer Id",
                                "value": ["307"],
                                "operator": "exact",
                                "type": "person",
                            }
                        ]
                    }
                ]
            }
        )
        feature_flag2 = self.create_feature_flag(
            key="random",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "Distinct Id",
                                "value": ["307"],
                                "operator": "exact",
                                "type": "person",
                            }
                        ]
                    },
                    {
                        "properties": [
                            {
                                "key": "Distinct Id",
                                "value": [307],
                                "operator": "exact",
                                "type": "person",
                            }
                        ]
                    },
                ]
            },
        )

        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "307").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        # confirm it works with overrides as well, which are computed locally
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "307", property_value_overrides={"Organizer Id": "307"}).get_match(
                feature_flag
            ),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "307", property_value_overrides={"Organizer Id": 307}).get_match(
                feature_flag
            ),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        # test with a flag where the property is a number

        self.assertEqual(
            FeatureFlagMatcher([feature_flag2], "307").get_match(feature_flag2),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        # confirm it works with overrides as well, which are computed locally
        self.assertEqual(
            FeatureFlagMatcher([feature_flag2], "307", property_value_overrides={"Distinct Id": "307"}).get_match(
                feature_flag2
            ),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        self.assertEqual(
            FeatureFlagMatcher([feature_flag2], "307", property_value_overrides={"Distinct Id": 307}).get_match(
                feature_flag2
            ),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

    def test_coercion_of_strings_and_numbers_with_is_not_operator(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["307"],
            properties={
                "Distinct Id": 307,
                "Organizer Id": "307",
            },
        )

        feature_flag = self.create_feature_flag(
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "Organizer Id",
                                "value": ["307"],
                                "operator": "is_not",
                                "type": "person",
                            },
                            {
                                "key": "Organizer Id",
                                "value": [307],
                                "operator": "is_not",
                                "type": "person",
                            },
                            {
                                "key": "Organizer Id",
                                "value": "307",
                                "operator": "is_not",
                                "type": "person",
                            },
                            {
                                "key": "Organizer Id",
                                "value": 307,
                                "operator": "is_not",
                                "type": "person",
                            },
                        ]
                    }
                ]
            }
        )
        feature_flag2 = self.create_feature_flag(
            key="random",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "Distinct Id",
                                "value": ["307"],
                                "operator": "is_not",
                                "type": "person",
                            }
                        ]
                    },
                    {
                        "properties": [
                            {
                                "key": "Distinct Id",
                                "value": [307],
                                "operator": "is_not",
                                "type": "person",
                            }
                        ]
                    },
                    {
                        "properties": [
                            {
                                "key": "Distinct Id",
                                "value": "307",
                                "operator": "is_not",
                                "type": "person",
                            }
                        ]
                    },
                    {
                        "properties": [
                            {
                                "key": "Distinct Id",
                                "value": 307,
                                "operator": "is_not",
                                "type": "person",
                            }
                        ]
                    },
                ]
            },
        )

        with snapshot_postgres_queries_context(self), self.assertNumQueries(4):
            self.assertEqual(
                self.match_flag(feature_flag, "307"),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )

        # confirm it works with overrides as well, which are computed locally
        self.assertEqual(
            self.match_flag(feature_flag, "307", property_value_overrides={"Organizer Id": "307"}),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(feature_flag, "307", property_value_overrides={"Organizer Id": 307}),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(feature_flag, "307", property_value_overrides={"Organizer Id": 0}),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(feature_flag, "307", property_value_overrides={"Organizer Id": "308"}),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(feature_flag, "307", property_value_overrides={"Organizer Id": "0"}),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        # test with a flag where the property is a number
        with snapshot_postgres_queries_context(self), self.assertNumQueries(4):
            self.assertEqual(
                self.match_flag(feature_flag2, "307"),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 3),
            )

        # confirm it works with overrides as well, which are computed locally
        self.assertEqual(
            self.match_flag(feature_flag2, "307", property_value_overrides={"Distinct Id": "307"}),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 3),
        )
        self.assertEqual(
            self.match_flag(feature_flag2, "307", property_value_overrides={"Distinct Id": 307}),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 3),
        )
        self.assertEqual(
            self.match_flag(feature_flag2, "307", property_value_overrides={"Distinct Id": 0}),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(feature_flag2, "307", property_value_overrides={"Distinct Id": "308"}),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(feature_flag2, "307", property_value_overrides={"Distinct Id": "0"}),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

    def test_coercion_of_booleans(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["307"],
            properties={
                "enabled": True,
                "string_enabled": "true",
            },
        )

        feature_flag1 = self.create_feature_flag(
            key="random1",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "enabled",
                                "value": ["true"],
                                "operator": "exact",
                                "type": "person",
                            }
                        ]
                    }
                ]
            },
        )
        feature_flag2 = self.create_feature_flag(
            key="random2",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "enabled",
                                "value": True,
                                "operator": "exact",
                                "type": "person",
                            }
                        ]
                    },
                    {
                        "properties": [
                            {
                                "key": "enabled",
                                "value": [True],
                                "operator": "exact",
                                "type": "person",
                            }
                        ]
                    },
                ]
            },
        )
        feature_flag3 = self.create_feature_flag(
            key="random3",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "string_enabled",
                                "value": [True],
                                "operator": "exact",
                                "type": "person",
                            }
                        ]
                    },
                    {
                        "properties": [
                            {
                                "key": "string_enabled",
                                "value": True,
                                "operator": "exact",
                                "type": "person",
                            }
                        ]
                    },
                ]
            },
        )
        feature_flag4 = self.create_feature_flag(
            key="random4",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "string_enabled",
                                "value": ['"true"'],
                                "operator": "exact",
                                "type": "person",
                            }
                        ]
                    },
                    {
                        "properties": [
                            {
                                "key": "string_enabled",
                                "value": '"true"',
                                "operator": "exact",
                                "type": "person",
                            }
                        ]
                    },
                ]
            },
        )

        self.assertEqual(
            FeatureFlagMatcher([feature_flag1], "307").get_match(feature_flag1),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag2], "307").get_match(feature_flag2),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag3], "307").get_match(feature_flag3),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag4], "307").get_match(feature_flag4),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        # confirm it works with overrides as well, which are computed locally
        self.assertEqual(
            FeatureFlagMatcher([feature_flag1], "307", property_value_overrides={"enabled": True}).get_match(
                feature_flag1
            ),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag2], "307", property_value_overrides={"enabled": True}).get_match(
                feature_flag2
            ),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(
                [feature_flag3],
                "307",
                property_value_overrides={"string_enabled": True},
            ).get_match(feature_flag3),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(
                [feature_flag4],
                "307",
                property_value_overrides={"string_enabled": True},
            ).get_match(feature_flag4),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        self.assertEqual(
            FeatureFlagMatcher([feature_flag1], "307", property_value_overrides={"enabled": "true"}).get_match(
                feature_flag1
            ),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag2], "307", property_value_overrides={"enabled": "true"}).get_match(
                feature_flag2
            ),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(
                [feature_flag3],
                "307",
                property_value_overrides={"string_enabled": "true"},
            ).get_match(feature_flag3),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(
                [feature_flag4],
                "307",
                property_value_overrides={"string_enabled": "true"},
            ).get_match(feature_flag4),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

    def test_coercion_of_booleans_with_is_not_operator(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["307"],
            properties={
                "enabled": True,
                "string_enabled": "true",
                "disabled": False,
                "string_disabled": "false",
                "uppercase_disabled": "False",
            },
        )

        feature_flag1 = self.create_feature_flag(
            key="random1",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "enabled",
                                "value": ["true"],
                                "operator": "is_not",
                                "type": "person",
                            },
                            {
                                "key": "enabled",
                                "value": [True],
                                "operator": "is_not",
                                "type": "person",
                            },
                            {
                                "key": "enabled",
                                "value": "true",
                                "operator": "is_not",
                                "type": "person",
                            },
                            {
                                "key": "enabled",
                                "value": True,
                                "operator": "is_not",
                                "type": "person",
                            },
                            # also check string_enabled, which is 'true'
                            {
                                "key": "string_enabled",
                                "value": ["true"],
                                "operator": "is_not",
                                "type": "person",
                            },
                            {
                                "key": "string_enabled",
                                "value": [True],
                                "operator": "is_not",
                                "type": "person",
                            },
                            {
                                "key": "string_enabled",
                                "value": "true",
                                "operator": "is_not",
                                "type": "person",
                            },
                            {
                                "key": "string_enabled",
                                "value": True,
                                "operator": "is_not",
                                "type": "person",
                            },
                        ]
                    }
                ]
            },
        )
        feature_flag1_with_disabled = self.create_feature_flag(
            key="random1_disabled",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "disabled",
                                "value": ["false"],
                                "operator": "is_not",
                                "type": "person",
                            },
                            {
                                "key": "disabled",
                                "value": [False],
                                "operator": "is_not",
                                "type": "person",
                            },
                            {
                                "key": "disabled",
                                "value": "false",
                                "operator": "is_not",
                                "type": "person",
                            },
                            {
                                "key": "disabled",
                                "value": False,
                                "operator": "is_not",
                                "type": "person",
                            },
                            {
                                "key": "string_disabled",
                                "value": False,
                                "operator": "is_not",
                                "type": "person",
                            },
                        ]
                    },
                    {
                        "properties": [
                            {
                                "key": "disabled",
                                "value": True,
                                "operator": "is_not",
                                "type": "person",
                            },
                            {
                                "key": "disabled",
                                "value": "true",
                                "operator": "is_not",
                                "type": "person",
                            },
                            {
                                "key": "disabled",
                                "value": ["true"],
                                "operator": "is_not",
                                "type": "person",
                            },
                            {
                                "key": "disabled",
                                "value": [True],
                                "operator": "is_not",
                                "type": "person",
                            },
                            {
                                "key": "string_disabled",
                                "value": True,
                                "operator": "is_not",
                                "type": "person",
                            },
                            {
                                "key": "string_disabled",
                                "value": "true",
                                "operator": "is_not",
                                "type": "person",
                            },
                            {
                                "key": "string_disabled",
                                "value": ["true"],
                                "operator": "is_not",
                                "type": "person",
                            },
                        ]
                    },
                ]
            },
        )
        feature_flag2 = self.create_feature_flag(
            key="random2",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "disabled",
                                "value": ["false"],
                                "operator": "is_not",
                                "type": "person",
                            },
                        ]
                    },
                    {
                        "properties": [
                            {
                                "key": "disabled",
                                "value": [False],
                                "operator": "is_not",
                                "type": "person",
                            },
                        ]
                    },
                    {
                        "properties": [
                            {
                                "key": "disabled",
                                "value": False,
                                "operator": "is_not",
                                "type": "person",
                            },
                        ]
                    },
                    {
                        "properties": [
                            {
                                "key": "disabled",
                                "value": "False",
                                "operator": "is_not",
                                "type": "person",
                            },
                        ]
                    },
                    {
                        "properties": [
                            {
                                "key": "disabled",
                                "value": "false",
                                "operator": "is_not",
                                "type": "person",
                            },
                        ]
                    },
                    {
                        "properties": [
                            {
                                "key": "string_disabled",
                                "value": "false",
                                "operator": "is_not",
                                "type": "person",
                            },
                        ]
                    },
                    {
                        "properties": [
                            {
                                "key": "string_disabled",
                                "value": False,
                                "operator": "is_not",
                                "type": "person",
                            },
                        ]
                    },
                    {
                        "properties": [
                            {
                                "key": "string_disabled",
                                "value": ["false"],
                                "operator": "is_not",
                                "type": "person",
                            },
                        ]
                    },
                    {
                        "properties": [
                            {
                                "key": "string_disabled",
                                "value": [False],
                                "operator": "is_not",
                                "type": "person",
                            },
                        ]
                    },
                ]
            },
        )
        self.assertEqual(
            self.match_flag(feature_flag1, "307"),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(feature_flag1_with_disabled, "307"),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 1),
        )

        with snapshot_postgres_queries_context(self), self.assertNumQueries(4):
            self.assertEqual(
                self.match_flag(feature_flag2, "307"),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 8),
            )

        # confirm it works with overrides as well, which are computed locally
        self.assertEqual(
            self.match_flag(feature_flag1, "307", property_value_overrides={"enabled": True, "string_enabled": True}),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(
                feature_flag1, "307", property_value_overrides={"enabled": "true", "string_enabled": "true"}
            ),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(feature_flag1, "307", property_value_overrides={"enabled": False, "string_enabled": True}),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(
                feature_flag1, "307", property_value_overrides={"enabled": "true", "string_enabled": "false"}
            ),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(feature_flag1, "307", property_value_overrides={"enabled": False, "string_enabled": False}),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(
                feature_flag1, "307", property_value_overrides={"enabled": "false", "string_enabled": "false"}
            ),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        # confirm it works with overrides as well, which are computed locally
        self.assertEqual(
            self.match_flag(
                feature_flag1_with_disabled, "307", property_value_overrides={"disabled": True, "string_disabled": True}
            ),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(
                feature_flag1_with_disabled,
                "307",
                property_value_overrides={"disabled": "true", "string_disabled": "true"},
            ),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(
                feature_flag1_with_disabled,
                "307",
                property_value_overrides={"disabled": False, "string_disabled": True},
            ),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 1),
        )
        self.assertEqual(
            self.match_flag(
                feature_flag1_with_disabled,
                "307",
                property_value_overrides={"disabled": "true", "string_disabled": "false"},
            ),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 1),
        )
        self.assertEqual(
            self.match_flag(
                feature_flag1_with_disabled,
                "307",
                property_value_overrides={"disabled": False, "string_disabled": False},
            ),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 1),
        )
        self.assertEqual(
            self.match_flag(
                feature_flag1_with_disabled,
                "307",
                property_value_overrides={"disabled": "false", "string_disabled": "false"},
            ),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 1),
        )

        # confirm it works with overrides as well, which are computed locally
        self.assertEqual(
            self.match_flag(feature_flag2, "307", property_value_overrides={"disabled": True, "string_disabled": True}),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(feature_flag2, "307", property_value_overrides={"string_disabled": True}),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 5),
        )
        self.assertEqual(
            self.match_flag(
                feature_flag2, "307", property_value_overrides={"disabled": "true", "string_disabled": "true"}
            ),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(
                feature_flag2, "307", property_value_overrides={"disabled": False, "string_disabled": True}
            ),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 5),
        )
        self.assertEqual(
            self.match_flag(
                feature_flag2, "307", property_value_overrides={"disabled": "true", "string_disabled": "false"}
            ),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(
                feature_flag2, "307", property_value_overrides={"disabled": False, "string_disabled": False}
            ),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 8),
        )
        self.assertEqual(
            self.match_flag(
                feature_flag2, "307", property_value_overrides={"disabled": "false", "string_disabled": "false"}
            ),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 8),
        )

    def test_non_existing_key_passes_is_not_check(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["307"],
            properties={},
        )
        feature_flag = self.create_feature_flag(
            key="random",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "Distinct Id",
                                "value": ["307"],
                                "operator": "is_not",
                                "type": "person",
                            }
                        ]
                    },
                ]
            },
        )

        self.assertEqual(
            self.match_flag(feature_flag, "307"),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        self.assertEqual(
            self.match_flag(feature_flag, "308"),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )

    @snapshot_postgres_queries
    def test_db_matches_independent_of_string_or_number_type(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["307"],
            properties={
                "Distinct Id": 307,
                "Organizer Id": "307",
            },
        )

        feature_flag = self.create_feature_flag(
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "Distinct Id",
                                "value": ["307"],
                                "operator": "exact",
                                "type": "person",
                            }
                        ]
                    }
                ]
            }
        )
        feature_flag2 = self.create_feature_flag(
            key="random",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "Distinct Id",
                                "value": [307],
                                "operator": "exact",
                                "type": "person",
                            }
                        ]
                    },
                ]
            },
        )

        feature_flag3 = self.create_feature_flag(
            key="random2",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "Distinct Id",
                                "value": 307,
                                "operator": "exact",
                                "type": "person",
                            }
                        ]
                    },
                ]
            },
        )

        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "307").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        # don't require explicit type correctness for overrides when you're already at /decide
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "307", property_value_overrides={"Distinct Id": 307}).get_match(
                feature_flag
            ),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        # test with a flag where the property is a number
        self.assertEqual(
            FeatureFlagMatcher([feature_flag2], "307").get_match(feature_flag2),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        self.assertEqual(
            FeatureFlagMatcher([feature_flag2], "307", property_value_overrides={"Distinct Id": 307}).get_match(
                feature_flag2
            ),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        # test with a flag where the property is a non-array number
        self.assertEqual(
            FeatureFlagMatcher([feature_flag3], "307").get_match(feature_flag3),
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
        Person.objects.create(
            team=self.team,
            distinct_ids=["test_id"],
            properties={"email": "test@posthog.com"},
        )

        feature_flag = self.create_feature_flag(
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": "test@posthog.com",
                                "operator": "exact",
                            }
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

    def test_super_condition_matches_boolean(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["test_id"],
            properties={"email": "test@posthog.com", "is_enabled": True},
        )

        feature_flag = self.create_feature_flag(
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": "fake@posthog.com",
                                "operator": "exact",
                            }
                        ],
                        "rollout_percentage": 0,
                    },
                    {
                        "properties": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": "test@posthog.com",
                                "operator": "exact",
                            }
                        ],
                        "rollout_percentage": 100,
                    },
                    {"rollout_percentage": 50},
                ],
                "super_groups": [
                    {
                        "properties": [
                            {
                                "key": "is_enabled",
                                "type": "person",
                                "operator": "exact",
                                "value": ["true"],
                            }
                        ],
                        "rollout_percentage": 100,
                    },
                ],
            },
        )

        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "test_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.SUPER_CONDITION_VALUE, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 2),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 2),
        )

    def test_super_condition_matches_string(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["test_id"],
            properties={"email": "test@posthog.com", "is_enabled": "true"},
        )

        feature_flag = self.create_feature_flag(
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": "fake@posthog.com",
                                "operator": "exact",
                            }
                        ],
                        "rollout_percentage": 0,
                    },
                    {
                        "properties": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": "test@posthog.com",
                                "operator": "exact",
                            }
                        ],
                        "rollout_percentage": 100,
                    },
                    {"rollout_percentage": 50},
                ],
                "super_groups": [
                    {
                        "properties": [
                            {
                                "key": "is_enabled",
                                "type": "person",
                                "operator": "exact",
                                "value": "true",
                            }
                        ],
                        "rollout_percentage": 100,
                    },
                ],
            },
        )

        with snapshot_postgres_queries_context(self):
            self.assertEqual(
                FeatureFlagMatcher([feature_flag], "test_id").get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.SUPER_CONDITION_VALUE, 0),
            )

    def test_super_condition_matches_and_false(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["test_id"],
            properties={"email": "test@posthog.com", "is_enabled": True},
        )

        feature_flag = self.create_feature_flag(
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": "fake@posthog.com",
                                "operator": "exact",
                            }
                        ],
                        "rollout_percentage": 0,
                    },
                    {
                        "properties": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": "test@posthog.com",
                                "operator": "exact",
                            }
                        ],
                        "rollout_percentage": 100,
                    },
                    {"rollout_percentage": 50},
                ],
                "super_groups": [
                    {
                        "properties": [
                            {
                                "key": "is_enabled",
                                "type": "person",
                                "operator": "exact",
                                "value": False,
                            }
                        ],
                        "rollout_percentage": 100,
                    },
                ],
            },
        )

        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "test_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.SUPER_CONDITION_VALUE, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 2),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 2),
        )

    def test_super_condition_is_not_set(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["test_id"],
            properties={"email": "test@posthog.com"},
        )

        feature_flag = self.create_feature_flag(
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": "fake@posthog.com",
                                "operator": "exact",
                            }
                        ],
                        "rollout_percentage": 0,
                    },
                    {
                        "properties": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": "test@posthog.com",
                                "operator": "exact",
                            }
                        ],
                        "rollout_percentage": 100,
                    },
                    {"rollout_percentage": 50},
                ],
                "super_groups": [
                    {
                        "properties": [
                            {
                                "key": "is_enabled",
                                "type": "person",
                                "operator": "exact",
                                "value": True,
                            }
                        ],
                        "rollout_percentage": 100,
                    },
                ],
            },
        )

        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "test_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 1),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 2),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 2),
        )

    def test_super_condition_promoted(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["test_id"],
            properties={"email": "test@posthog.com", "is_enabled": True},
        )

        feature_flag = self.create_feature_flag(
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": "fake@posthog.com",
                                "operator": "exact",
                            }
                        ],
                        "rollout_percentage": 0,
                    },
                    {
                        "properties": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": "test@posthog.com",
                                "operator": "exact",
                            }
                        ],
                        "rollout_percentage": 100,
                    },
                    {"rollout_percentage": 50},
                ],
                "super_groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 100,
                    },
                ],
            },
        )

        # Rollout to everyone
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "test_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.SUPER_CONDITION_VALUE, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.SUPER_CONDITION_VALUE, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.SUPER_CONDITION_VALUE, 0),
        )

    def test_super_condition_rolled_out_to_50(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["test_id"],
            properties={"email": "test@posthog.com", "is_enabled": True},
        )

        feature_flag = self.create_feature_flag(
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": "fake@posthog.com",
                                "operator": "exact",
                            }
                        ],
                        "rollout_percentage": 0,
                    },
                    {
                        "properties": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": "test@posthog.com",
                                "operator": "exact",
                            }
                        ],
                        "rollout_percentage": 100,
                    },
                    {"rollout_percentage": 50},
                ],
                "super_groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 50,
                    },
                ],
            },
        )

        # Rollout to everyone
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "test_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.SUPER_CONDITION_VALUE, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 0),
        )

    def test_super_condition_with_override_properties(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["test_id"],
            properties={"email": "test@posthog.com", "is_enabled": False},
        )

        feature_flag = self.create_feature_flag(
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": "fake@posthog.com",
                                "operator": "exact",
                            }
                        ],
                        "rollout_percentage": 0,
                    },
                    {
                        "properties": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": "test@posthog.com",
                                "operator": "exact",
                            }
                        ],
                        "rollout_percentage": 100,
                    },
                    {"rollout_percentage": 50},
                ],
                "super_groups": [
                    {
                        "properties": [
                            {
                                "key": "is_enabled",
                                "type": "person",
                                "operator": "exact",
                                "value": True,
                            }
                        ],
                        "rollout_percentage": 100,
                    },
                ],
            },
        )

        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "test_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.SUPER_CONDITION_VALUE, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "test_id", property_value_overrides={"is_enabled": True}).get_match(
                feature_flag
            ),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.SUPER_CONDITION_VALUE, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 2),
        )
        self.assertEqual(
            FeatureFlagMatcher(
                [feature_flag],
                "example_id",
                property_value_overrides={"is_enabled": True},
            ).get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.SUPER_CONDITION_VALUE, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 2),
        )
        self.assertEqual(
            FeatureFlagMatcher(
                [feature_flag],
                "another_id",
                property_value_overrides={"is_enabled": True},
            ).get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.SUPER_CONDITION_VALUE, 0),
        )

    def test_super_condition_with_override_properties_with_property_not_ingested(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["test_id"],
            properties={"email": "test@posthog.com"},
        )

        feature_flag = self.create_feature_flag(
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": "fake@posthog.com",
                                "operator": "exact",
                            }
                        ],
                        "rollout_percentage": 0,
                    },
                    {
                        "properties": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": "test@posthog.com",
                                "operator": "exact",
                            }
                        ],
                        "rollout_percentage": 100,
                    },
                    {"rollout_percentage": 50},
                ],
                "super_groups": [
                    {
                        "properties": [
                            {
                                "key": "is_enabled",
                                "type": "person",
                                "operator": "exact",
                                "value": True,
                            }
                        ],
                        "rollout_percentage": 100,
                    },
                ],
            },
        )

        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "test_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 1),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "test_id", property_value_overrides={"is_enabled": True}).get_match(
                feature_flag
            ),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.SUPER_CONDITION_VALUE, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 2),
        )
        self.assertEqual(
            FeatureFlagMatcher(
                [feature_flag],
                "example_id",
                property_value_overrides={"is_enabled": True},
            ).get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.SUPER_CONDITION_VALUE, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 2),
        )
        self.assertEqual(
            FeatureFlagMatcher(
                [feature_flag],
                "another_id",
                property_value_overrides={"is_enabled": True},
            ).get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.SUPER_CONDITION_VALUE, 0),
        )

    @pytest.mark.skip("TODO: We're going to the database for now, but we should be able to do this in memory.")
    def test_super_condition_with_override_properties_doesnt_make_database_requests(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["test_id"],
            properties={"email": "test@posthog.com"},
        )

        feature_flag = self.create_feature_flag(
            filters={
                "groups": [
                    {"rollout_percentage": 50},
                ],
                "super_groups": [
                    {
                        "properties": [
                            {
                                "key": "is_enabled",
                                "type": "person",
                                "operator": "exact",
                                "value": True,
                            }
                        ],
                        "rollout_percentage": 100,
                    },
                ],
            },
        )

        with self.assertNumQueries(0), snapshot_postgres_queries_context(self):
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag],
                    "test_id",
                    property_value_overrides={"is_enabled": True},
                ).get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.SUPER_CONDITION_VALUE, 0),
            )
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag],
                    "example_id",
                    property_value_overrides={"is_enabled": True},
                ).get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.SUPER_CONDITION_VALUE, 0),
            )

    def test_flag_with_variant_overrides(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["test_id"],
            properties={"email": "test@posthog.com"},
        )

        feature_flag = self.create_feature_flag(
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": "test@posthog.com",
                                "operator": "exact",
                            }
                        ],
                        "rollout_percentage": 100,
                        "variant": "second-variant",
                    },
                    {"rollout_percentage": 50, "variant": "first-variant"},
                ],
                "multivariate": {
                    "variants": [
                        {
                            "key": "first-variant",
                            "name": "First Variant",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "second-variant",
                            "name": "Second Variant",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "third-variant",
                            "name": "Third Variant",
                            "rollout_percentage": 25,
                        },
                    ]
                },
            }
        )

        # would've been `third-variant` if not for the override
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "test_id").get_match(feature_flag),
            FeatureFlagMatch(True, "second-variant", FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        # would've been `second-variant` if not for the override
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, "first-variant", FeatureFlagMatchReason.CONDITION_MATCH, 1),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 1),
        )

    def test_flag_with_clashing_variant_overrides(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["test_id", "example_id"],
            properties={"email": "test@posthog.com"},
        )

        feature_flag = self.create_feature_flag(
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": "test@posthog.com",
                                "operator": "exact",
                            }
                        ],
                        "rollout_percentage": 100,
                        "variant": "second-variant",
                    },
                    # since second-variant comes first in the list, it will be the one that gets picked
                    {
                        "properties": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": "test@posthog.com",
                                "operator": "exact",
                            }
                        ],
                        "rollout_percentage": 100,
                        "variant": "first-variant",
                    },
                    {"rollout_percentage": 50},
                ],
                "multivariate": {
                    "variants": [
                        {
                            "key": "first-variant",
                            "name": "First Variant",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "second-variant",
                            "name": "Second Variant",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "third-variant",
                            "name": "Third Variant",
                            "rollout_percentage": 25,
                        },
                    ]
                },
            }
        )

        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "test_id").get_match(feature_flag),
            FeatureFlagMatch(True, "second-variant", FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, "second-variant", FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 2),
        )

    def test_flag_with_invalid_variant_overrides(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["test_id"],
            properties={"email": "test@posthog.com"},
        )

        feature_flag = self.create_feature_flag(
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": "test@posthog.com",
                                "operator": "exact",
                            }
                        ],
                        "rollout_percentage": 100,
                        "variant": "second???",
                    },
                    {"rollout_percentage": 50, "variant": "first???"},
                ],
                "multivariate": {
                    "variants": [
                        {
                            "key": "first-variant",
                            "name": "First Variant",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "second-variant",
                            "name": "Second Variant",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "third-variant",
                            "name": "Third Variant",
                            "rollout_percentage": 25,
                        },
                    ]
                },
            }
        )

        # would've been `third-variant` if not for the override
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "test_id").get_match(feature_flag),
            FeatureFlagMatch(True, "third-variant", FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        # would've been `second-variant` if not for the override
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, "second-variant", FeatureFlagMatchReason.CONDITION_MATCH, 1),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 1),
        )

    def test_flag_with_multiple_variant_overrides(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["test_id"],
            properties={"email": "test@posthog.com"},
        )

        feature_flag = self.create_feature_flag(
            filters={
                "groups": [
                    {
                        "rollout_percentage": 100,
                        # The override applies even if the first condition matches all and gives everyone their default group
                    },
                    {
                        "properties": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": "test@posthog.com",
                                "operator": "exact",
                            }
                        ],
                        "rollout_percentage": 100,
                        "variant": "second-variant",
                    },
                    {"rollout_percentage": 50, "variant": "third-variant"},
                ],
                "multivariate": {
                    "variants": [
                        {
                            "key": "first-variant",
                            "name": "First Variant",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "second-variant",
                            "name": "Second Variant",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "third-variant",
                            "name": "Third Variant",
                            "rollout_percentage": 25,
                        },
                    ]
                },
            }
        )

        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "test_id").get_match(feature_flag),
            FeatureFlagMatch(True, "second-variant", FeatureFlagMatchReason.CONDITION_MATCH, 1),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, "third-variant", FeatureFlagMatchReason.CONDITION_MATCH, 2),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(True, "second-variant", FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

    def test_multiple_flags(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["test_id"],
            properties={"email": "test@posthog.com"},
        )
        self.create_groups()
        feature_flag_one = self.create_feature_flag(
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": "test@posthog.com",
                                "operator": "exact",
                            }
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
            filters={
                "aggregation_group_type_index": 1,
                "groups": [{"rollout_percentage": 100}],
            },
            key="group_match",
        )
        feature_flag_group_no_match = self.create_feature_flag(
            filters={
                "aggregation_group_type_index": 1,
                "groups": [{"rollout_percentage": 0}],
            },
            key="group_no_match",
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
                        {
                            "key": "first-variant",
                            "name": "First Variant",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "second-variant",
                            "name": "Second Variant",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "third-variant",
                            "name": "Third Variant",
                            "rollout_percentage": 25,
                        },
                    ]
                },
                "payloads": {
                    "first-variant": {"color": "blue"},
                    "second-variant": {"color": "green"},
                    "third-variant": {"color": "red"},
                },
            },
            key="variant",
        )

        with self.assertNumQueries(10), snapshot_postgres_queries_context(
            self
        ):  # 1 to fill group cache, 2 to match feature flags with group properties (of each type), 1 to match feature flags with person properties
            matches, reasons, payloads, _ = FeatureFlagMatcher(
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
                "never_match": False,
                "group_no_match": False,
                "group_property_different_match": False,
                # never_match and group_no_match don't match
                # group_property_different_match doesn't match because we're dealing with a different group key
            },
        )

        self.assertEqual(
            reasons,
            {
                "one": {
                    "reason": FeatureFlagMatchReason.CONDITION_MATCH,
                    "condition_index": 0,
                },
                "always_match": {
                    "reason": FeatureFlagMatchReason.CONDITION_MATCH,
                    "condition_index": 0,
                },
                "group_match": {
                    "reason": FeatureFlagMatchReason.CONDITION_MATCH,
                    "condition_index": 0,
                },
                "variant": {
                    "reason": FeatureFlagMatchReason.CONDITION_MATCH,
                    "condition_index": 0,
                },
                "group_property_match": {
                    "reason": FeatureFlagMatchReason.CONDITION_MATCH,
                    "condition_index": 0,
                },
                "never_match": {
                    "reason": FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND,
                    "condition_index": 0,
                },
                "group_no_match": {
                    "reason": FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND,
                    "condition_index": 0,
                },
                "group_property_different_match": {
                    "reason": FeatureFlagMatchReason.NO_CONDITION_MATCH,
                    "condition_index": 0,
                },
            },
        )

        self.assertEqual(payloads, {"variant": {"color": "blue"}})

        with self.assertNumQueries(9), snapshot_postgres_queries_context(
            self
        ):  # 1 to fill group cache, 1 to match feature flags with group properties (only 1 group provided), 1 to match feature flags with person properties
            matches, reasons, payloads, _ = FeatureFlagMatcher(
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

        self.assertEqual(payloads, {"variant": {"color": "blue"}})

        self.assertEqual(
            matches,
            {
                "one": True,
                "always_match": True,
                "variant": "first-variant",
                "group_property_different_match": True,
                "never_match": False,
                "group_no_match": False,
                "group_match": False,
                "group_property_match": False,
                # never_match and group_no_match don't match
                # group_match doesn't match because no project (group type index 1) given.
                # group_property_match doesn't match because we're dealing with a different group key
            },
        )

        self.assertEqual(
            reasons,
            {
                "one": {
                    "reason": FeatureFlagMatchReason.CONDITION_MATCH,
                    "condition_index": 0,
                },
                "always_match": {
                    "reason": FeatureFlagMatchReason.CONDITION_MATCH,
                    "condition_index": 0,
                },
                "group_match": {
                    "reason": FeatureFlagMatchReason.NO_GROUP_TYPE,
                    "condition_index": None,
                },
                "variant": {
                    "reason": FeatureFlagMatchReason.CONDITION_MATCH,
                    "condition_index": 0,
                },
                "group_property_different_match": {
                    "reason": FeatureFlagMatchReason.CONDITION_MATCH,
                    "condition_index": 0,
                },
                "never_match": {
                    "reason": FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND,
                    "condition_index": 0,
                },
                "group_no_match": {
                    "reason": FeatureFlagMatchReason.NO_GROUP_TYPE,
                    "condition_index": None,
                },
                "group_property_match": {
                    "reason": FeatureFlagMatchReason.NO_CONDITION_MATCH,
                    "condition_index": 0,
                },
            },
        )

    def test_multi_property_filters(self):
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
        Person.objects.create(team=self.team, distinct_ids=["false_id"], properties={})
        feature_flag = self.create_feature_flag(
            filters={
                "groups": [
                    {"properties": [{"key": "email", "value": "tim@posthog.com"}]},
                    {"properties": [{"key": "email", "value": "example@example.com"}]},
                ]
            }
        )
        with self.assertNumQueries(4):
            self.assertEqual(
                FeatureFlagMatcher([feature_flag], "example_id").get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )
        with self.assertNumQueries(4):
            self.assertEqual(
                FeatureFlagMatcher([feature_flag], "another_id").get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 1),
            )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "false_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 1),
        )

    def test_multi_property_filters_with_override_properties(self):
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
        Person.objects.create(team=self.team, distinct_ids=["random_id"], properties={})
        feature_flag = self.create_feature_flag(
            filters={
                "groups": [
                    {"properties": [{"key": "email", "value": "tim@posthog.com"}]},
                    {"properties": [{"key": "email", "value": "example@example.com"}]},
                ]
            }
        )
        with self.assertNumQueries(4):
            self.assertEqual(
                FeatureFlagMatcher([feature_flag], "example_id", property_value_overrides={}).get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )
            # can be computed locally
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag],
                    "example_id",
                    property_value_overrides={"email": "bzz"},
                ).get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 1),
            )

        with self.assertNumQueries(4):
            self.assertEqual(
                FeatureFlagMatcher([feature_flag], "random_id").get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 1),
            )

            # can be computed locally
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag],
                    "random_id",
                    property_value_overrides={"email": "example@example.com"},
                ).get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 1),
            )

    def test_multi_property_filters_with_override_group_properties(self):
        self.create_groups()
        feature_flag = self.create_feature_flag(
            filters={
                "aggregation_group_type_index": 0,
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "name",
                                "value": ["foo.inc"],
                                "type": "group",
                                "group_type_index": 0,
                            },
                            {
                                "key": "not_ingested",
                                "value": "example.com",
                                "type": "group",
                                "group_type_index": 0,
                            },
                        ]
                    },
                ],
            }
        )
        cache = FlagsMatcherCache(self.team.id)
        # force the query to load group types
        cache.group_type_index_to_name  # noqa: B018

        with self.assertNumQueries(12):
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag],
                    "example1_id",
                    cache=cache,
                    groups={"organization": "foo"},
                    group_property_value_overrides={},
                ).get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )
            # can be computed using the db, with help from the overrides
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag],
                    "example2_id",
                    cache=cache,
                    groups={"organization": "foo"},
                    group_property_value_overrides={"organization": {"not_ingested": "example.com"}},
                ).get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )
            # name property is incorrect, since different group
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag],
                    "example3_id",
                    cache=cache,
                    groups={"organization": "bar"},
                    group_property_value_overrides={"organization": {"not_ingested": "example.com"}},
                ).get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )

        with self.assertNumQueries(0):
            self.assertEqual(
                FeatureFlagMatcher([feature_flag], "random_id", cache=cache).get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_GROUP_TYPE),
            )

            # can be computed locally
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag],
                    "random_id",
                    cache=cache,
                    groups={"organization": "foo"},
                    group_property_value_overrides={
                        "organization": {
                            "not_ingested": "example.com",
                            "name": "foo.inc",
                        }
                    },
                ).get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )
            # even if the group property stored in db is different
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag],
                    "random_id",
                    cache=cache,
                    groups={"organization": "bar"},
                    group_property_value_overrides={
                        "organization": {
                            "not_ingested": "example.com",
                            "name": "foo.inc",
                        }
                    },
                ).get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )

    def test_override_properties_where_person_doesnt_exist_yet(self):
        feature_flag = self.create_feature_flag(
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "value": "tim@posthog.com",
                                "type": "person",
                            }
                        ]
                    },
                    {"properties": [{"key": "email", "value": "example@example.com"}]},
                ]
            }
        )
        with self.assertNumQueries(0):
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag],
                    "example_id",
                    property_value_overrides={"email": "tim@posthog.com"},
                ).get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag],
                    "example_id",
                    property_value_overrides={"email": "bzz"},
                ).get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 1),
            )

        with self.assertNumQueries(4):
            self.assertEqual(
                FeatureFlagMatcher([feature_flag], "random_id").get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 1),
            )

        with self.assertNumQueries(0):
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag],
                    "random_id",
                    property_value_overrides={"email": "example@example.com"},
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
        with self.assertNumQueries(8):
            # None in both because all conditions don't match
            # and user doesn't exist yet
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag],
                    "example_id",
                    property_value_overrides={"email": "tim@posthog.com"},
                ).get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag],
                    "example_id",
                    property_value_overrides={"email": "bzz"},
                ).get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )

        with self.assertNumQueries(4):
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
                    property_value_overrides={
                        "email": "tim@posthog.com",
                        "another_prop": "slow",
                        "blah": "blah",
                    },
                ).get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag],
                    "random_id_within_rollout",
                    property_value_overrides={
                        "email": "tim@posthog.com",
                        "another_prop": "slow",
                        "blah": "blah",
                    },
                ).get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 0),
            )

        with self.assertNumQueries(0):
            # These don't match properties
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag],
                    "random_id_without_rollout",
                    property_value_overrides={
                        "email": "tim@posthog.com",
                        "another_prop": "slow2",
                        "blah": "blah",
                    },
                ).get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag],
                    "random_id_without_rollout",
                    property_value_overrides={
                        "email": "tim2@posthog.com",
                        "another_prop": "slow",
                        "blah": "blah",
                    },
                ).get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )

    def test_multi_property_filters_with_override_properties_with_is_not_set(self):
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
        Person.objects.create(team=self.team, distinct_ids=["random_id"], properties={})
        feature_flag = self.create_feature_flag(
            filters={"groups": [{"properties": [{"key": "email", "operator": "is_not_set"}]}]}
        )
        with self.assertNumQueries(8):
            self.assertEqual(
                FeatureFlagMatcher([feature_flag], "example_id", property_value_overrides={}).get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag],
                    "example_id",
                    property_value_overrides={"email": "bzz"},
                ).get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )

        with self.assertNumQueries(8):
            self.assertEqual(
                FeatureFlagMatcher([feature_flag], "random_id").get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag],
                    "random_id",
                    property_value_overrides={"email": "example@example.com"},
                ).get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )

    def test_cohort_cache_no_unnecessary_queries(self):
        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "email",
                            "type": "person",
                            "value": r"@posthog\.com$",
                            "negation": False,
                            "operator": "regex",
                        }
                    ]
                }
            ],
            name="cohort1",
        )
        cohort2 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "email",
                            "type": "person",
                            "value": "@posthog.com",
                            "negation": False,
                            "operator": "icontains",
                        }
                    ]
                }
            ],
            name="cohort2",
        )

        cohort3 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "email",
                            "type": "person",
                            "value": r"@posthog\.com$",
                            "negation": False,
                            "operator": "regex",
                        }
                    ]
                }
            ],
            name="cohort3",
        )

        feature_flag1: FeatureFlag = self.create_feature_flag(
            key="x1",
            filters={"groups": [{"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]}]},
        )
        feature_flag2: FeatureFlag = self.create_feature_flag(
            filters={"groups": [{"properties": [{"key": "id", "value": cohort2.pk, "type": "cohort"}]}]}
        )
        feature_flag3: FeatureFlag = self.create_feature_flag(
            key="x2",
            filters={
                "groups": [
                    {"properties": [{"key": "id", "value": cohort2.pk, "type": "cohort"}]},
                    {"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]},
                    {"properties": [{"key": "id", "value": cohort3.pk, "type": "cohort"}]},
                ]
            },
        )
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com"},
        )

        with self.assertNumQueries(5):
            # single query for all cohorts
            # no team queries
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag1, feature_flag2, feature_flag3],
                    "example_id",
                    property_value_overrides={},
                ).get_match(feature_flag1),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )

    def test_cohort_filters_with_override_properties(self):
        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "email",
                            "type": "person",
                            "value": r"@posthog\.com$",
                            "negation": False,
                            "operator": "regex",
                        }
                    ]
                }
            ],
            name="cohort1",
        )
        cohort2 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "email",
                            "type": "person",
                            "value": "@posthog.com",
                            "negation": False,
                            "operator": "icontains",
                        }
                    ]
                }
            ],
            name="cohort2",
        )

        feature_flag1: FeatureFlag = self.create_feature_flag(
            key="x1",
            filters={"groups": [{"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]}]},
        )
        feature_flag2: FeatureFlag = self.create_feature_flag(
            filters={"groups": [{"properties": [{"key": "id", "value": cohort2.pk, "type": "cohort"}]}]}
        )
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com"},
        )

        with self.assertNumQueries(5):
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag1, feature_flag2],
                    "example_id",
                    property_value_overrides={},
                ).get_match(feature_flag1),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )

        with self.assertNumQueries(4):
            # no local computation because cohort lookup is required
            # no postgres person query required here to get the person, because email is sufficient
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag1, feature_flag2],
                    "example_id",
                    property_value_overrides={"email": "bzz"},
                ).get_match(feature_flag1),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )

        with self.assertNumQueries(4):
            # no postgres query required here to get the person
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag1, feature_flag2],
                    "example_id",
                    property_value_overrides={"email": "neil@posthog.com"},
                ).get_match(feature_flag1),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )

        with self.assertNumQueries(4):
            # Random person doesn't yet exist, but still should resolve thanks to overrides
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag1, feature_flag2],
                    "random_id",
                    property_value_overrides={"email": "xxx"},
                ).get_match(feature_flag2),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )

        with self.assertNumQueries(4):
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag1, feature_flag2],
                    "random_id",
                    property_value_overrides={"email": "example@posthog.com"},
                ).get_match(feature_flag2),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )

    @pytest.mark.skip("This case is not supported yet")
    def test_complex_cohort_filter_with_override_properties(self):
        # TODO: Currently we don't support this case for persons who haven't been ingested yet
        # The case:
        # - A cohort has multiple conditions
        # - All of which are the _same_ / are true for the same property.
        # Example: email contains .com ; email contains @ ; email contains posthog
        # -> 3 different filters, all of which match neil@posthog.com.

        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "email",
                            "type": "person",
                            "value": r"@posthog\.com$",
                            "negation": False,
                            "operator": "regex",
                        }
                    ]
                },
                {
                    "properties": [
                        {
                            "key": "email",
                            "type": "person",
                            "value": "@posthog.com",
                            "negation": False,
                            "operator": "icontains",
                        }
                    ]
                },
            ],
            name="cohort1",
        )
        feature_flag1: FeatureFlag = self.create_feature_flag(
            key="x1",
            filters={"groups": [{"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]}]},
        )

        with self.assertNumQueries(5):
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag1],
                    "example_id",
                    property_value_overrides={"email": "neil@posthog.com"},
                ).get_match(feature_flag1),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )

        with self.assertNumQueries(5):
            # no local computation because cohort lookup is required
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag1],
                    "example_id",
                    property_value_overrides={"email": "bzz"},
                ).get_match(feature_flag1),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )

    def test_cohort_filters_with_multiple_OR_override_properties(self):
        cohort1 = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": r"@posthog\.com$",
                                    "negation": False,
                                    "operator": "regex",
                                }
                            ],
                        },
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": ["fuzion@xyz.com"],
                                    "operator": "exact",
                                }
                            ],
                        },
                    ],
                }
            },
            name="cohort1",
        )

        feature_flag1: FeatureFlag = self.create_feature_flag(
            filters={"groups": [{"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]}]}
        )

        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com"},
        )

        with self.assertNumQueries(5):
            self.assertEqual(
                FeatureFlagMatcher([feature_flag1], "example_id", property_value_overrides={}).get_match(feature_flag1),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )

        with self.assertNumQueries(5):
            # no local computation because cohort lookup is required
            self.assertEqual(
                FeatureFlagMatcher(
                    [feature_flag1],
                    "example_id",
                    property_value_overrides={"email": "neil@posthog.com"},
                ).get_match(feature_flag1),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )

    def test_user_in_cohort(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id_1"],
            properties={"$some_prop_1": "something_1"},
        )
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "$some_prop_1",
                            "value": "something_1",
                            "type": "person",
                        }
                    ]
                }
            ],
            name="cohort1",
        )
        cohort.calculate_people_ch(pending_version=0)

        feature_flag: FeatureFlag = self.create_feature_flag(
            filters={"groups": [{"properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}]}]}
        )

        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "example_id_1").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )

    def test_cohort_expansion_returns_same_result_as_regular_flag(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id_4"],
            properties={"$some_prop1": "something1"},
        )
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id_5"],
            properties={"$some_prop2": "something2"},
        )
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id_6"],
            properties={"$some_prop": "something"},
        )

        cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$some_prop1",
                                    "value": "something1",
                                    "type": "person",
                                },
                                {
                                    "key": "$some_prop2",
                                    "value": "something2",
                                    "type": "person",
                                },
                            ],
                        }
                    ],
                }
            },
            name="cohort1",
        )

        cohort.calculate_people_ch(pending_version=0)

        ff_key = "cohort-exp"

        feature_flag: FeatureFlag = self.create_feature_flag(
            key=ff_key,
            filters={
                "groups": [
                    {
                        "properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],
                        "rollout_percentage": 28,
                    }
                ]
            },
        )

        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "example_id_4").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "example_id_5").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )

        matches = []
        for i in range(1, 7):
            distinct_id = f"example_id_{i}"
            match = FeatureFlagMatcher([feature_flag], distinct_id).get_match(feature_flag)
            matches.append((match.match, match.reason))

        expanded_filters = feature_flag.transform_cohort_filters_for_easy_evaluation()
        feature_flag.delete()

        feature_flag_expanded: FeatureFlag = self.create_feature_flag(key=ff_key, filters={"groups": expanded_filters})

        expanded_matches = []
        for i in range(1, 7):
            distinct_id = f"example_id_{i}"
            match = FeatureFlagMatcher([feature_flag_expanded], distinct_id).get_match(feature_flag_expanded)
            expanded_matches.append((match.match, match.reason))

        self.assertEqual(matches, expanded_matches)

    def test_user_in_static_cohort(self):
        Person.objects.create(team_id=self.team.pk, distinct_ids=["example_id_1"])
        Person.objects.create(team_id=self.team.pk, distinct_ids=["example_id_2"])
        Person.objects.create(team_id=self.team.pk, distinct_ids=["3"])

        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, last_calculation=timezone.now())
        cohort.insert_users_by_list(["example_id_1", "example_id_2"])

        feature_flag: FeatureFlag = self.create_feature_flag(
            filters={"groups": [{"properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}]}]}
        )

        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "example_id_1").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "3").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )

    def test_user_in_cohort_without_calculation(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id_1"],
            properties={"$some_prop_1": "something_1"},
        )
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "$some_prop_1",
                            "value": "something_1",
                            "type": "person",
                        }
                    ]
                }
            ],
            name="cohort1",
        )
        feature_flag: FeatureFlag = self.create_feature_flag(
            filters={"groups": [{"properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}]}]}
        )

        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "example_id_1").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )

    @patch("posthog.models.feature_flag.flag_matching.postgres_healthcheck")
    def test_invalid_filters_dont_set_db_down(self, mock_database_healthcheck):
        cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$some_prop",
                                    "value": "nomatchihope",
                                    "type": "person",
                                },
                                {
                                    "key": "$some_prop2",
                                    "value": "nomatchihope2",
                                    "type": "person",
                                },
                                {
                                    "key": "$pageview",
                                    "event_type": "events",
                                    "time_value": 1,
                                    "time_interval": "week",
                                    "value": "performed_event",
                                    "type": "behavioral",
                                },
                            ],
                        }
                    ],
                }
            },
            name="cohort1",
        )
        flag: FeatureFlag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            active=True,
            key="active-flag",
            filters={
                "groups": [
                    {
                        "properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],
                        "rollout_percentage": 50,
                    }
                ]
            },
        )

        matcher = FeatureFlagMatcher([flag], "example_id_1")

        self.assertEqual(matcher.get_matches(), ({}, {}, {}, True))
        self.assertEqual(matcher.failed_to_fetch_conditions, False)
        mock_database_healthcheck.set_connection.assert_not_called()

    @patch("posthog.models.feature_flag.flag_matching.postgres_healthcheck")
    def test_invalid_group_filters_dont_set_db_down(self, mock_database_healthcheck):
        flag: FeatureFlag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            active=True,
            key="active-flag",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        flag2: FeatureFlag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            active=True,
            key="group-flag",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "aggregation_group_type_index": 0,
            },
        )
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)

        matcher = FeatureFlagMatcher([flag, flag2], "example_id_1", ["organization"])  # type: ignore

        self.assertEqual(
            matcher.get_matches(),
            (
                {"active-flag": True},
                {
                    "active-flag": {
                        "condition_index": 0,
                        "reason": FeatureFlagMatchReason.CONDITION_MATCH,
                    }
                },
                {},
                True,
            ),
        )
        self.assertEqual(matcher.failed_to_fetch_conditions, False)
        mock_database_healthcheck.set_connection.assert_not_called()

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
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com"},
        )
        Person.objects.create(
            team=self.team,
            distinct_ids=["another_id"],
            properties={"email": "tim@posthog.com"},
        )
        Person.objects.create(
            team=self.team,
            distinct_ids=["id_number_3"],
            properties={"email": "example@example.com"},
        )
        feature_flag = self.create_feature_flag(
            rollout_percentage=50,
            filters={"properties": [{"key": "email", "value": "tim@posthog.com", "type": "person"}]},
        )
        with self.assertNumQueries(4):
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
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id_2"],
            properties={"$some_prop_2": "something_2"},
        )
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "$some_prop_2",
                            "value": "something_2",
                            "type": "person",
                        }
                    ]
                }
            ],
            name="cohort2",
        )
        cohort.calculate_people_ch(pending_version=0)

        feature_flag: FeatureFlag = self.create_feature_flag(
            filters={"properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}]}
        )

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
                        {
                            "key": "first-variant",
                            "name": "First Variant",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "second-variant",
                            "name": "Second Variant",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "third-variant",
                            "name": "Third Variant",
                            "rollout_percentage": 25,
                        },
                    ]
                },
            }
        )

        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "11").get_match(feature_flag),
            FeatureFlagMatch(
                True,
                variant="first-variant",
                reason=FeatureFlagMatchReason.CONDITION_MATCH,
                condition_index=0,
            ),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(
                True,
                variant="second-variant",
                reason=FeatureFlagMatchReason.CONDITION_MATCH,
                condition_index=0,
            ),
        )
        self.assertEqual(
            FeatureFlagMatcher([feature_flag], "3").get_match(feature_flag),
            FeatureFlagMatch(
                True,
                variant="third-variant",
                reason=FeatureFlagMatchReason.CONDITION_MATCH,
                condition_index=0,
            ),
        )

    def test_flag_by_groups_with_rollout_100(self):
        self.create_groups()
        feature_flag = self.create_feature_flag(
            filters={
                "aggregation_group_type_index": 1,
                "groups": [{"rollout_percentage": 100}],
            }
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
            filters={
                "aggregation_group_type_index": 1,
                "groups": [{"rollout_percentage": 50}],
            }
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
                    {
                        "properties": [
                            {
                                "key": "name",
                                "value": ["foo.inc"],
                                "type": "group",
                                "group_type_index": 0,
                            }
                        ]
                    }
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
            team=self.team,
            group_type_index=0,
            group_key="foo",
            group_properties={"name": "foo.inc"},
            version=1,
        )
        Group.objects.create(
            team=self.team,
            group_type_index=0,
            group_key="bar",
            group_properties={"name": "var.inc"},
            version=1,
        )
        # Add other irrelevant groups
        for i in range(5):
            Group.objects.create(
                team=self.team,
                group_type_index=1,
                group_key=f"group_key{i}",
                group_properties={},
                version=1,
            )
        Group.objects.create(
            team=self.team,
            group_type_index=1,
            group_key="group_key",
            group_properties={"name": "var.inc"},
            version=1,
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
                        {
                            "key": "first-variant",
                            "name": "First Variant",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "second-variant",
                            "name": "Second Variant",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "third-variant",
                            "name": "Third Variant",
                            "rollout_percentage": 25,
                        },
                    ]
                },
            },
            name="This is a feature flag with multiple variants.",
            key="multivariate-flag",
            created_by=cls.user,
            ensure_experience_continuity=True,
        )

        cls.person = Person.objects.create(
            team=cls.team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com", "team": "posthog"},
        )

    def test_setting_overrides(self):
        set_feature_flag_hash_key_overrides(
            team_id=self.team.pk,
            distinct_ids=self.person.distinct_ids,
            hash_key_override="other_id",
        )

        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT hash_key FROM posthog_featureflaghashkeyoverride WHERE team_id = {self.team.pk} AND person_id={self.person.id}"
            )
            res = cursor.fetchall()
            self.assertEqual(len(res), 2)
            self.assertEqual({var[0] for var in res}, {"other_id"})

    def test_retrieving_hash_key_overrides(self):
        set_feature_flag_hash_key_overrides(
            team_id=self.team.pk,
            distinct_ids=self.person.distinct_ids,
            hash_key_override="other_id",
        )

        hash_keys = get_feature_flag_hash_key_overrides(self.team.pk, ["example_id"])

        self.assertEqual(hash_keys, {"beta-feature": "other_id", "multivariate-flag": "other_id"})

    def test_hash_key_overrides_for_multiple_ids_when_people_are_not_merged(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["1"],
            properties={"email": "beuk@posthog.com", "team": "posthog"},
        )

        Person.objects.create(
            team=self.team,
            distinct_ids=["2"],
            properties={"email": "beuk2@posthog.com", "team": "posthog"},
        )

        set_feature_flag_hash_key_overrides(team_id=self.team.pk, distinct_ids=["1"], hash_key_override="other_id1")
        set_feature_flag_hash_key_overrides(team_id=self.team.pk, distinct_ids=["2"], hash_key_override="aother_id2")

        hash_keys = get_feature_flag_hash_key_overrides(self.team.pk, ["1", "2"])

        self.assertEqual(hash_keys, {"beta-feature": "other_id1", "multivariate-flag": "other_id1"})

    def test_setting_overrides_doesnt_balk_with_existing_overrides(self):
        all_feature_flags = list(FeatureFlag.objects.filter(team_id=self.team.pk))

        # existing overrides
        hash_key = "bazinga"
        FeatureFlagHashKeyOverride.objects.bulk_create(
            [
                FeatureFlagHashKeyOverride(
                    team_id=self.team.pk,
                    person_id=self.person.id,
                    feature_flag_key=feature_flag.key,
                    hash_key=hash_key,
                )
                for feature_flag in all_feature_flags
            ]
        )

        # and now we come to get new overrides
        set_feature_flag_hash_key_overrides(
            team_id=self.team.pk,
            distinct_ids=self.person.distinct_ids,
            hash_key_override="other_id",
        )

        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT hash_key FROM posthog_featureflaghashkeyoverride WHERE team_id = {self.team.pk} AND person_id={self.person.id}"
            )
            res = cursor.fetchall()
            self.assertEqual(len(res), 3)
            self.assertEqual({var[0] for var in res}, {hash_key})

    def test_setting_overrides_when_persons_dont_exist(self):
        set_feature_flag_hash_key_overrides(
            team_id=self.team.pk,
            distinct_ids=["1", "2", "3", "4"],
            hash_key_override="other_id",
        )

        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT hash_key FROM posthog_featureflaghashkeyoverride WHERE team_id = {self.team.pk} AND person_id={self.person.id}"
            )
            res = cursor.fetchall()
            self.assertEqual(len(res), 0)

    def test_entire_flow_with_hash_key_override(self):
        # get feature flags for 'other_id', with an override for 'example_id'
        flags, reasons, payloads, _ = get_all_feature_flags(self.team.pk, "other_id", {}, "example_id")
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

        self.assertEqual(payloads, {})


@patch(
    "posthog.models.feature_flag.flag_matching.postgres_healthcheck.is_connected",
    return_value=True,
)
class TestHashKeyOverridesRaceConditions(TransactionTestCase, QueryMatchingTest):
    def setUp(self) -> None:
        return super().setUp()

    def test_hash_key_overrides_with_race_conditions(self, *args):
        org = Organization.objects.create(name="test")
        user = User.objects.create_and_join(org, "a@b.com", "kkk")
        team = Team.objects.create(organization=org)

        FeatureFlag.objects.create(
            team=team,
            rollout_percentage=30,
            name="Beta feature",
            key="beta-feature",
            created_by=user,
            ensure_experience_continuity=True,
        )
        FeatureFlag.objects.create(
            team=team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            name="This is a feature flag with default params, no filters.",
            key="default-flag",
            created_by=user,
        )  # Should be enabled for everyone
        FeatureFlag.objects.create(
            team=team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {
                            "key": "first-variant",
                            "name": "First Variant",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "second-variant",
                            "name": "Second Variant",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "third-variant",
                            "name": "Third Variant",
                            "rollout_percentage": 25,
                        },
                    ]
                },
            },
            name="This is a feature flag with multiple variants.",
            key="multivariate-flag",
            created_by=user,
            ensure_experience_continuity=True,
        )

        Person.objects.create(
            team=team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com", "team": "posthog"},
        )

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_index = {
                executor.submit(
                    get_all_feature_flags,
                    team.pk,
                    "other_id",
                    {},
                    hash_key_override="example_id",
                ): index
                for index in range(5)
            }
            for future in concurrent.futures.as_completed(future_to_index):
                flags, reasons, payloads, errors = future.result()
                assert errors is False
                assert flags == {
                    "beta-feature": True,
                    "multivariate-flag": "first-variant",
                    "default-flag": True,
                }

                # the failure mode is when this raises an `IntegrityError` because the hash key override was racy

    def test_hash_key_overrides_with_simulated_error_race_conditions_on_person_merging(self, *args):
        def insert_fail(execute, sql, *args, **kwargs):
            if "statement_timeout" in sql:
                return execute(sql, *args, **kwargs)
            if "insert" in sql.lower():
                # run the sql so it shows up in snapshots
                execute(sql, *args, **kwargs)

                raise IntegrityError(
                    """
                    insert or update on table "posthog_featureflaghashkeyoverride" violates foreign key constraint "posthog_featureflagh_person_id_7e517f7c_fk_posthog_p"
                    DETAIL:  Key (person_id)=(1487010281) is not present in table "posthog_person".
                """
                )
            return execute(sql, *args, **kwargs)

        org = Organization.objects.create(name="test")
        user = User.objects.create_and_join(org, "a@b.com", "kkk")
        team = Team.objects.create(organization=org)

        FeatureFlag.objects.create(
            team=team,
            rollout_percentage=30,
            name="Beta feature",
            key="beta-feature",
            created_by=user,
            ensure_experience_continuity=True,
        )
        FeatureFlag.objects.create(
            team=team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            name="This is a feature flag with default params, no filters.",
            key="default-flag",
            created_by=user,
        )  # Should be enabled for everyone
        FeatureFlag.objects.create(
            team=team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {
                            "key": "first-variant",
                            "name": "First Variant",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "second-variant",
                            "name": "Second Variant",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "third-variant",
                            "name": "Third Variant",
                            "rollout_percentage": 25,
                        },
                    ]
                },
            },
            name="This is a feature flag with multiple variants.",
            key="multivariate-flag",
            created_by=user,
            ensure_experience_continuity=True,
        )

        Person.objects.create(
            team=team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com", "team": "posthog"},
        )
        Person.objects.create(
            team=team,
            distinct_ids=["other_id"],
            properties={"email": "tim@posthog.com", "team": "posthog"},
        )

        with snapshot_postgres_queries_context(self, capture_all_queries=True), connection.execute_wrapper(insert_fail):
            flags, reasons, payloads, errors = get_all_feature_flags(
                team.pk, "other_id", {}, hash_key_override="example_id"
            )
            assert errors is False
            # overrides failed since both insert failed :shrug:
            assert flags == {
                "beta-feature": False,
                "multivariate-flag": "third-variant",
                "default-flag": True,
            }

    def test_hash_key_overrides_with_simulated_race_conditions_on_person_merging(self, *args):
        class InsertFailOnce:
            def __init__(self):
                self.has_failed = False

            def __call__(self, execute, sql, *args, **kwargs):
                if "statement_timeout" in sql:
                    return execute(sql, *args, **kwargs)
                if "insert" in sql.lower() and not self.has_failed:
                    self.has_failed = True
                    # run the sql so it shows up in snapshots
                    execute(sql, *args, **kwargs)
                    # then raise an error
                    raise IntegrityError(
                        """
                        insert or update on table "posthog_featureflaghashkeyoverride" violates foreign key constraint "posthog_featureflagh_person_id_7e517f7c_fk_posthog_p"
                        DETAIL:  Key (person_id)=(1487010281) is not present in table "posthog_person".
                    """
                    )
                return execute(sql, *args, **kwargs)

        org = Organization.objects.create(name="test")
        user = User.objects.create_and_join(org, "a@b.com", "kkk")
        team = Team.objects.create(organization=org)

        FeatureFlag.objects.create(
            team=team,
            rollout_percentage=30,
            name="Beta feature",
            key="beta-feature",
            created_by=user,
            ensure_experience_continuity=True,
        )
        FeatureFlag.objects.create(
            team=team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            name="This is a feature flag with default params, no filters.",
            key="default-flag",
            created_by=user,
        )  # Should be enabled for everyone
        FeatureFlag.objects.create(
            team=team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {
                            "key": "first-variant",
                            "name": "First Variant",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "second-variant",
                            "name": "Second Variant",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "third-variant",
                            "name": "Third Variant",
                            "rollout_percentage": 25,
                        },
                    ]
                },
            },
            name="This is a feature flag with multiple variants.",
            key="multivariate-flag",
            created_by=user,
            ensure_experience_continuity=True,
        )

        Person.objects.create(
            team=team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com", "team": "posthog"},
        )
        Person.objects.create(
            team=team,
            distinct_ids=["other_id"],
            properties={"email": "tim@posthog.com", "team": "posthog"},
        )

        with snapshot_postgres_queries_context(self, capture_all_queries=True), connection.execute_wrapper(
            InsertFailOnce()
        ):
            flags, reasons, payloads, errors = get_all_feature_flags(
                team.pk, "other_id", {}, hash_key_override="example_id"
            )
            assert errors is False
            # overrides succeeded on second try
            assert flags == {
                "beta-feature": True,
                "multivariate-flag": "first-variant",
                "default-flag": True,
            }

    def test_hash_key_overrides_with_race_conditions_on_person_creation_and_deletion(self, *args):
        org = Organization.objects.create(name="test")
        user = User.objects.create_and_join(org, "a@b.com", "kkk")
        team = Team.objects.create(organization=org)

        FeatureFlag.objects.create(
            team=team,
            rollout_percentage=30,
            name="Beta feature",
            key="beta-feature",
            created_by=user,
            ensure_experience_continuity=True,
        )
        FeatureFlag.objects.create(
            team=team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            name="This is a feature flag with default params, no filters.",
            key="default-flag",
            created_by=user,
        )  # Should be enabled for everyone
        FeatureFlag.objects.create(
            team=team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {
                            "key": "first-variant",
                            "name": "First Variant",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "second-variant",
                            "name": "Second Variant",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "third-variant",
                            "name": "Third Variant",
                            "rollout_percentage": 25,
                        },
                    ]
                },
            },
            name="This is a feature flag with multiple variants.",
            key="multivariate-flag",
            created_by=user,
            ensure_experience_continuity=True,
        )

        person1 = Person.objects.create(
            team=team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com", "team": "posthog"},
        )
        person2 = Person.objects.create(
            team=team,
            distinct_ids=["other_id"],
            properties={"email": "tim@posthog.com", "team": "posthog"},
        )

        def delete_and_add(person, person2, distinct_id):
            FeatureFlagHashKeyOverride.objects.filter(person=person).delete()
            Person.objects.filter(id=person.id).delete()
            person2.add_distinct_id(distinct_id)
            return True, "deleted and added", {}, False

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_index = {
                executor.submit(
                    get_all_feature_flags,
                    team.pk,
                    "other_id",
                    {},
                    hash_key_override="example_id",
                ): index
                for index in range(5)
            }

            future_to_index = {
                executor.submit(delete_and_add, person1, person2, "example_id"): 10,
                **future_to_index,
            }
            for future in concurrent.futures.as_completed(future_to_index):
                flags, reasons, payloads, errors = future.result()
                if flags is not True:  # type: ignore
                    assert errors is False
                    assert flags == {
                        "beta-feature": True,
                        "multivariate-flag": "first-variant",
                        "default-flag": True,
                    }

                # the failure mode is when this raises an `IntegrityError` because the hash key override was racy
                # or if the insert fails because person was deleted


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
                    feature_flag_match,
                    FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
                )
            else:
                self.assertEqual(
                    feature_flag_match,
                    FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 0),
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
                        {
                            "key": "first-variant",
                            "name": "First Variant",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "second-variant",
                            "name": "Second Variant",
                            "rollout_percentage": 20,
                        },
                        {
                            "key": "third-variant",
                            "name": "Third Variant",
                            "rollout_percentage": 20,
                        },
                        {
                            "key": "fourth-variant",
                            "name": "Fourth Variant",
                            "rollout_percentage": 5,
                        },
                        {
                            "key": "fifth-variant",
                            "name": "Fifth Variant",
                            "rollout_percentage": 5,
                        },
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
                    feature_flag_match,
                    FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 0),
                )
