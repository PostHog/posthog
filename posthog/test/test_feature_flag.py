import concurrent.futures
from datetime import datetime
from typing import cast

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest, QueryMatchingTest, snapshot_postgres_queries, snapshot_postgres_queries_context
from unittest.mock import patch

from django.core.cache import cache
from django.db import IntegrityError, connection
from django.test import TransactionTestCase
from django.utils import timezone

from flaky import flaky
from parameterized import parameterized

from posthog.models import Cohort, FeatureFlag, Person
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
from posthog.test.test_utils import create_group_type_mapping_without_created_at


class TestFeatureFlagCohortExpansion(BaseTest):
    maxDiff = None

    @parameterized.expand(
        [
            ("some_distinct_id", 0.7270002403585725),
            ("test-identifier", 0.4493881716040236),
            ("example_id", 0.9402003475831224),
            ("example_id2", 0.6292740389966519),
        ]
    )
    def test_calculate_hash(self, identifier, expected_hash):
        result = FeatureFlagMatcher.calculate_hash("holdout-", identifier, "")
        self.assertAlmostEqual(result, expected_hash)

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

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    def test_save_updates_cache(self, mock_on_commit):
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
        return FeatureFlagMatcher(self.team.id, self.project.id, [flag], distinct_id, **kwargs).get_match(flag)

    def test_blank_flag(self):
        # Blank feature flags now default to be released for everyone
        feature_flag = self.create_feature_flag()
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

    @snapshot_postgres_queries
    def test_invalid_regex_match_flag(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["307"],
            properties={
                "email": '"neil@x.com"',
            },
        )
        feature_flag = self.create_feature_flag(
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "value": '["neil@x.com"]',
                                "operator": "regex",
                                "type": "person",
                            }
                        ]
                    }
                ]
            }
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "307").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )

    def test_feature_flag_with_greater_than_filter(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"$some_prop": 5},
        )
        feature_flag = self.create_feature_flag(
            key="flag-with-gt-filter",
            filters={
                "groups": [{"properties": [{"key": "$some_prop", "value": 4, "type": "person", "operator": "gt"}]}]
            },
        )

        with self.assertNumQueries(4):
            self.assertEqual(
                self.match_flag(feature_flag, "example_id"),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )

    def test_feature_flag_with_greater_than_filter_no_match(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"$some_prop": 3},
        )
        feature_flag = self.create_feature_flag(
            key="flag-with-gt-filter",
            filters={
                "groups": [{"properties": [{"key": "$some_prop", "value": 4, "type": "person", "operator": "gt"}]}]
            },
        )

        with self.assertNumQueries(4):
            self.assertEqual(
                self.match_flag(feature_flag, "example_id"),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )

    def test_feature_flag_with_greater_than_filter_invalid_value(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"$some_prop": 3},
        )
        feature_flag = self.create_feature_flag(
            key="flag-with-gt-filter",
            filters={
                "groups": [{"properties": [{"key": "$some_prop", "value": ["4"], "type": "person", "operator": "gt"}]}]
            },
        )

        with self.assertNumQueries(3):
            self.assertEqual(
                self.match_flag(feature_flag, "example_id"),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )

    def test_feature_flag_with_holdout_filter(self):
        # example_id is outside 70% holdout
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"$some_prop": 5},
        )
        # example_id2 is within 70% holdout
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id2"],
            properties={"$some_prop": 5},
        )

        multivariate_json = {
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
        }
        feature_flag = self.create_feature_flag(
            key="flag-with-gt-filter",
            filters={
                "groups": [{"properties": [{"key": "$some_prop", "value": 4, "type": "person", "operator": "gt"}]}],
                "holdout_groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 70,
                        "variant": "holdout",
                    }
                ],
                "multivariate": multivariate_json,
            },
        )

        other_feature_flag = self.create_feature_flag(
            key="other-flag-with-gt-filter",
            filters={
                "groups": [{"properties": [{"key": "$some_prop", "value": 4, "type": "person", "operator": "gt"}]}],
                "holdout_groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 70,
                        "variant": "holdout",
                    }
                ],
                "multivariate": multivariate_json,
            },
        )

        other_flag_without_holdout = self.create_feature_flag(
            key="other-flag-without-holdout-with-gt-filter",
            filters={
                "groups": [{"properties": [{"key": "$some_prop", "value": 4, "type": "person", "operator": "gt"}]}],
                "holdout_groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 0,
                        "variant": "holdout",
                    }
                ],
                "multivariate": multivariate_json,
            },
        )

        # regular flag evaluation when outside holdout
        with self.assertNumQueries(4):
            self.assertEqual(
                self.match_flag(feature_flag, "example_id"),
                FeatureFlagMatch(True, "second-variant", FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )

        # inside holdout, get holdout variant override.
        # also, should have no db queries here.
        with self.assertNumQueries(0):
            self.assertEqual(
                self.match_flag(feature_flag, "example_id2"),
                FeatureFlagMatch(True, "holdout", FeatureFlagMatchReason.HOLDOUT_CONDITION_VALUE, 0),
            )

        # same should hold true for a different feature flag when within holdout
        self.assertEqual(
            self.match_flag(other_feature_flag, "example_id2"),
            FeatureFlagMatch(True, "holdout", FeatureFlagMatchReason.HOLDOUT_CONDITION_VALUE, 0),
        )
        # but the variants may change outside holdout since different flag
        self.assertEqual(
            self.match_flag(other_feature_flag, "example_id"),
            FeatureFlagMatch(True, "third-variant", FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        # when holdout exists but is zero, should default to regular flag evaluation
        self.assertEqual(
            self.match_flag(other_flag_without_holdout, "example_id"),
            FeatureFlagMatch(True, "second-variant", FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(other_flag_without_holdout, "example_id2"),
            FeatureFlagMatch(True, "second-variant", FeatureFlagMatchReason.CONDITION_MATCH, 0),
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
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "307").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        # confirm it works with overrides as well, which are computed locally
        self.assertEqual(
            FeatureFlagMatcher(
                self.team.id, self.project.id, [feature_flag], "307", property_value_overrides={"Organizer Id": "307"}
            ).get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        self.assertEqual(
            FeatureFlagMatcher(
                self.team.id, self.project.id, [feature_flag], "307", property_value_overrides={"Organizer Id": 307}
            ).get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        # test with a flag where the property is a number

        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag2], "307").get_match(feature_flag2),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        # confirm it works with overrides as well, which are computed locally
        self.assertEqual(
            FeatureFlagMatcher(
                self.team.id, self.project.id, [feature_flag2], "307", property_value_overrides={"Distinct Id": "307"}
            ).get_match(feature_flag2),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        self.assertEqual(
            FeatureFlagMatcher(
                self.team.id, self.project.id, [feature_flag2], "307", property_value_overrides={"Distinct Id": 307}
            ).get_match(feature_flag2),
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

        with snapshot_postgres_queries_context(self), self.assertNumQueries(5):
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
        with snapshot_postgres_queries_context(self), self.assertNumQueries(5):
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
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag1], "307").get_match(feature_flag1),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag2], "307").get_match(feature_flag2),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag3], "307").get_match(feature_flag3),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag4], "307").get_match(feature_flag4),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        # confirm it works with overrides as well, which are computed locally
        self.assertEqual(
            FeatureFlagMatcher(
                self.team.id, self.project.id, [feature_flag1], "307", property_value_overrides={"enabled": True}
            ).get_match(feature_flag1),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(
                self.team.id, self.project.id, [feature_flag2], "307", property_value_overrides={"enabled": True}
            ).get_match(feature_flag2),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(
                self.team.id,
                self.project.id,
                [feature_flag3],
                "307",
                property_value_overrides={"string_enabled": True},
            ).get_match(feature_flag3),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(
                self.team.id,
                self.project.id,
                [feature_flag4],
                "307",
                property_value_overrides={"string_enabled": True},
            ).get_match(feature_flag4),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        self.assertEqual(
            FeatureFlagMatcher(
                self.team.id, self.project.id, [feature_flag1], "307", property_value_overrides={"enabled": "true"}
            ).get_match(feature_flag1),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(
                self.team.id, self.project.id, [feature_flag2], "307", property_value_overrides={"enabled": "true"}
            ).get_match(feature_flag2),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(
                self.team.id,
                self.project.id,
                [feature_flag3],
                "307",
                property_value_overrides={"string_enabled": "true"},
            ).get_match(feature_flag3),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(
                self.team.id,
                self.project.id,
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

        with snapshot_postgres_queries_context(self), self.assertNumQueries(5):
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
        Person.objects.create(
            team=self.team,
            distinct_ids=["309"],
            properties={"Distinct Id": "307"},
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

        # person doesn't exist, meaning the property doesn't exist, so it should pass the is_not check
        self.assertEqual(
            self.match_flag(feature_flag, "308"),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        self.assertEqual(
            self.match_flag(feature_flag, "309"),
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
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "307").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        # don't require explicit type correctness for overrides when you're already at /decide
        self.assertEqual(
            FeatureFlagMatcher(
                self.team.id, self.project.id, [feature_flag], "307", property_value_overrides={"Distinct Id": 307}
            ).get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        # test with a flag where the property is a number
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag2], "307").get_match(feature_flag2),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        self.assertEqual(
            FeatureFlagMatcher(
                self.team.id, self.project.id, [feature_flag2], "307", property_value_overrides={"Distinct Id": 307}
            ).get_match(feature_flag2),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        # test with a flag where the property is a non-array number
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag3], "307").get_match(feature_flag3),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

    def test_rollout_percentage(self):
        feature_flag = self.create_feature_flag(filters={"groups": [{"rollout_percentage": 50}]})
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 0),
        )

    def test_empty_group(self):
        feature_flag = self.create_feature_flag(filters={"groups": [{}]})
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

    def test_null_rollout_percentage(self):
        feature_flag = self.create_feature_flag(filters={"groups": [{"properties": [], "rollout_percentage": None}]})
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

    def test_zero_rollout_percentage(self):
        feature_flag = self.create_feature_flag(filters={"groups": [{"properties": [], "rollout_percentage": 0}]})
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "example_id").get_match(feature_flag),
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
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "test_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 1),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "another_id").get_match(feature_flag),
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
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "test_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.SUPER_CONDITION_VALUE, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 2),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "another_id").get_match(feature_flag),
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
                FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "test_id").get_match(feature_flag),
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
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "test_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.SUPER_CONDITION_VALUE, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 2),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "another_id").get_match(feature_flag),
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
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "test_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 1),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 2),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "another_id").get_match(feature_flag),
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
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "test_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.SUPER_CONDITION_VALUE, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.SUPER_CONDITION_VALUE, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "another_id").get_match(feature_flag),
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
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "test_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.SUPER_CONDITION_VALUE, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "another_id").get_match(feature_flag),
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
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "test_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.SUPER_CONDITION_VALUE, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(
                self.team.id, self.project.id, [feature_flag], "test_id", property_value_overrides={"is_enabled": True}
            ).get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.SUPER_CONDITION_VALUE, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 2),
        )
        self.assertEqual(
            FeatureFlagMatcher(
                self.team.id,
                self.project.id,
                [feature_flag],
                "example_id",
                property_value_overrides={"is_enabled": True},
            ).get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.SUPER_CONDITION_VALUE, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 2),
        )
        self.assertEqual(
            FeatureFlagMatcher(
                self.team.id,
                self.project.id,
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
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "test_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 1),
        )
        self.assertEqual(
            FeatureFlagMatcher(
                self.team.id, self.project.id, [feature_flag], "test_id", property_value_overrides={"is_enabled": True}
            ).get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.SUPER_CONDITION_VALUE, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 2),
        )
        self.assertEqual(
            FeatureFlagMatcher(
                self.team.id,
                self.project.id,
                [feature_flag],
                "example_id",
                property_value_overrides={"is_enabled": True},
            ).get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.SUPER_CONDITION_VALUE, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 2),
        )
        self.assertEqual(
            FeatureFlagMatcher(
                self.team.id,
                self.project.id,
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
                    self.team.id,
                    self.project.id,
                    [feature_flag],
                    "test_id",
                    property_value_overrides={"is_enabled": True},
                ).get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.SUPER_CONDITION_VALUE, 0),
            )
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
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
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "test_id").get_match(feature_flag),
            FeatureFlagMatch(True, "second-variant", FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        # would've been `second-variant` if not for the override
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, "first-variant", FeatureFlagMatchReason.CONDITION_MATCH, 1),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "another_id").get_match(feature_flag),
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
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "test_id").get_match(feature_flag),
            FeatureFlagMatch(True, "second-variant", FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, "second-variant", FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "another_id").get_match(feature_flag),
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
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "test_id").get_match(feature_flag),
            FeatureFlagMatch(True, "third-variant", FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        # would've been `second-variant` if not for the override
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, "second-variant", FeatureFlagMatchReason.CONDITION_MATCH, 1),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "another_id").get_match(feature_flag),
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
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "test_id").get_match(feature_flag),
            FeatureFlagMatch(True, "second-variant", FeatureFlagMatchReason.CONDITION_MATCH, 1),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, "third-variant", FeatureFlagMatchReason.CONDITION_MATCH, 2),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "another_id").get_match(feature_flag),
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

        with (
            self.assertNumQueries(10),
            snapshot_postgres_queries_context(self),
        ):  # 1 to fill group cache, 2 to match feature flags with group properties (of each type), 1 to match feature flags with person properties
            matches, reasons, payloads, _, _ = FeatureFlagMatcher(
                self.team.id,
                self.project.id,
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
            ).get_matches_with_details()

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

        with (
            self.assertNumQueries(9),
            snapshot_postgres_queries_context(self),
        ):  # 1 to fill group cache, 1 to match feature flags with group properties (only 1 group provided), 1 to match feature flags with person properties
            matches, reasons, payloads, _, _ = FeatureFlagMatcher(
                self.team.id,
                self.project.id,
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
            ).get_matches_with_details()

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
                FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "example_id").get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )
        with self.assertNumQueries(4):
            self.assertEqual(
                FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "another_id").get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 1),
            )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "false_id").get_match(feature_flag),
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
                FeatureFlagMatcher(
                    self.team.id, self.project.id, [feature_flag], "example_id", property_value_overrides={}
                ).get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )
            # can be computed locally
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag],
                    "example_id",
                    property_value_overrides={"email": "bzz"},
                ).get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 1),
            )

        with self.assertNumQueries(4):
            self.assertEqual(
                FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "random_id").get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 1),
            )

            # can be computed locally
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
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
                    self.team.id,
                    self.project.id,
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
                    self.team.id,
                    self.project.id,
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
                    self.team.id,
                    self.project.id,
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
                FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "random_id", cache=cache).get_match(
                    feature_flag
                ),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_GROUP_TYPE),
            )

            # can be computed locally
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
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
                    self.team.id,
                    self.project.id,
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
                    self.team.id,
                    self.project.id,
                    [feature_flag],
                    "example_id",
                    property_value_overrides={"email": "tim@posthog.com"},
                ).get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag],
                    "example_id",
                    property_value_overrides={"email": "bzz"},
                ).get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 1),
            )

        with self.assertNumQueries(4):
            self.assertEqual(
                FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "random_id").get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 1),
            )

        with self.assertNumQueries(0):
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
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
                    self.team.id,
                    self.project.id,
                    [feature_flag],
                    "example_id",
                    property_value_overrides={"email": "tim@posthog.com"},
                ).get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag],
                    "example_id",
                    property_value_overrides={"email": "bzz"},
                ).get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )

        with self.assertNumQueries(4):
            self.assertEqual(
                FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "random_id").get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )

        with self.assertNumQueries(0):
            # Both of these match properties, but second one is outside rollout %.
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
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
                    self.team.id,
                    self.project.id,
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
                    self.team.id,
                    self.project.id,
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
                    self.team.id,
                    self.project.id,
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
        with self.assertNumQueries(5):
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id, self.project.id, [feature_flag], "example_id", property_value_overrides={}
                ).get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )
        with self.assertNumQueries(0):
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag],
                    "example_id",
                    property_value_overrides={"email": "bzz"},
                ).get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )

        with self.assertNumQueries(5):
            self.assertEqual(
                FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "random_id").get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )
        with self.assertNumQueries(0):
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag],
                    "random_id",
                    property_value_overrides={"email": "example@example.com"},
                ).get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )

    def test_non_existing_person_with_is_not_set(self):
        feature_flag = self.create_feature_flag(
            filters={"groups": [{"properties": [{"key": "email", "operator": "is_not_set"}]}]}
        )

        # one extra query to check existence
        with self.assertNumQueries(5):
            self.assertEqual(
                FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "not-seen-person").get_match(
                    feature_flag
                ),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag],
                    "not-seen-person",
                    property_value_overrides={"email": "example@example.com"},
                ).get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )

    def test_is_not_equal_with_non_existing_person(self):
        feature_flag = self.create_feature_flag(
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": "$initial_utm_source", "type": "person", "value": ["fb"], "operator": "is_not"}
                        ]
                    }
                ]
            }
        )

        # one extra query to check existence
        with self.assertNumQueries(5):
            self.assertEqual(
                FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "not-seen-person").get_match(
                    feature_flag
                ),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )

            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag],
                    "not-seen-person",
                    property_value_overrides={"$initial_utm_source": "fb"},
                ).get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag],
                    "not-seen-person",
                    property_value_overrides={"$initial_utm_source": "fbx"},
                ).get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )

    def test_is_not_set_operator_with_overrides(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["another_id"],
            properties={"company": "example.com"},
        )
        feature_flag1 = self.create_feature_flag(
            key="x1",
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": "email", "operator": "is_not_set"},
                            {"key": "company", "operator": "is_set"},
                        ]
                    }
                ]
            },
        )

        # no extra query to check existence because it doesn't matter - since not a pure condition
        with self.assertNumQueries(4):
            self.assertEqual(
                FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag1], "not-seen-person").get_match(
                    feature_flag1
                ),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )
        # still goes to DB because no company override, and then fails because person doesn't exist
        with self.assertNumQueries(4):
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag1],
                    "not-seen-person",
                    property_value_overrides={"email": "example@example.com"},
                ).get_match(feature_flag1),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )
        # :TRICKY: For optimising queries, we're not supporting this case yet - because it should be pretty
        # rare in practice: One property is overridden, another property doesn't exist, and the person doesn't exist yet either
        # This will get sorted in the rewrite.
        #
        # goes to DB because no email override, and then FAILS because person doesn't exist (should pass ideally)
        with self.assertNumQueries(4):
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag1],
                    "not-seen-person",
                    property_value_overrides={"company": "x.com"},
                ).get_match(feature_flag1),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )
        # doesn't go to DB
        with self.assertNumQueries(0):
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag1],
                    "not-seen-person",
                    property_value_overrides={"company": "x.com", "email": "k"},
                ).get_match(feature_flag1),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )

        # now dealing with existing person
        with self.assertNumQueries(4):
            self.assertEqual(
                FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag1], "another_id").get_match(
                    feature_flag1
                ),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )
        # since not all conditions are available in overrides, goes to DB, but then correctly matches is_not_set condition
        # using the given override
        with self.assertNumQueries(4):
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag1],
                    "another_id",
                    property_value_overrides={"email": "example@example.com"},
                ).get_match(feature_flag1),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )

    def test_is_not_set_operator_with_pure_multiple_conditions(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["another_id"],
            properties={"email": "example@example.com"},
        )
        Person.objects.create(
            team=self.team,
            distinct_ids=["another_id_without_email"],
            properties={},
        )
        feature_flag1 = self.create_feature_flag(
            key="x2",
            filters={
                "groups": [
                    {"properties": [{"key": "email", "operator": "is_not_set"}]},
                    {"properties": [{"key": "email", "operator": "icontains", "type": "person", "value": "example"}]},
                ]
            },
        )

        # 1 extra query to get existence clause
        with self.assertNumQueries(5):
            self.assertEqual(
                FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag1], "not-seen-person").get_match(
                    feature_flag1
                ),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )

        with self.assertNumQueries(0):
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag1],
                    "not-seen-person",
                    property_value_overrides={"email": "x"},
                ).get_match(feature_flag1),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 1),
            )

        with self.assertNumQueries(0):
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag1],
                    "not-seen-person",
                    property_value_overrides={"email": "example.com"},
                ).get_match(feature_flag1),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 1),
            )

        # now dealing with existing person
        # one extra query to check existence
        with self.assertNumQueries(5):
            self.assertEqual(
                FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag1], "another_id").get_match(
                    feature_flag1
                ),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 1),
            )

        with self.assertNumQueries(0):
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag1],
                    "another_id",
                    property_value_overrides={"email": "x"},
                ).get_match(feature_flag1),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 1),
            )

        # without email, person exists though, should thus return True
        with self.assertNumQueries(5):
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id, self.project.id, [feature_flag1], "another_id_without_email"
                ).get_match(feature_flag1),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )

    def test_is_not_set_operator_with_groups(self):
        self.create_groups()
        Group.objects.create(
            team=self.team,
            group_type_index=0,
            group_key="target_group",
            group_properties={},
            version=1,
        )
        feature_flag = self.create_feature_flag(
            filters={
                "aggregation_group_type_index": 0,
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "name",
                                "operator": "is_not_set",
                                "type": "group",
                                "group_type_index": 0,
                            }
                        ]
                    }
                ],
            }
        )
        feature_flag_different_group = self.create_feature_flag(
            key="x1_group2",
            filters={
                "aggregation_group_type_index": 1,
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "name",
                                "operator": "is_not_set",
                                "type": "group",
                                "group_type_index": 1,
                            }
                        ]
                    }
                ],
            },
        )
        feature_flag_unknown_group_type = self.create_feature_flag(
            key="x_unkown",
            filters={
                "aggregation_group_type_index": 5,
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "name",
                                "operator": "is_not_set",
                                "type": "group",
                                "group_type_index": 5,
                            }
                        ]
                    }
                ],
            },
        )
        feature_flag_with_no_person_is_not_set = self.create_feature_flag(
            key="x1",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "name",
                                "operator": "is_set",
                                "type": "person",
                            }
                        ]
                    }
                ],
            },
        )
        feature_flag_with_person_is_not_set = self.create_feature_flag(
            key="x2",
            filters={
                "groups": [
                    {"properties": [{"key": "email", "operator": "is_not_set"}]},
                    {"properties": [{"key": "email", "operator": "icontains", "type": "person", "value": "example"}]},
                ]
            },
        )

        # one extra query for existence clause
        with self.assertNumQueries(9):
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id, self.project.id, [feature_flag], "", {"organization": "target_group"}
                ).get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )

        with self.assertNumQueries(9):
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id, self.project.id, [feature_flag], "", {"organization": "foo"}
                ).get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )
        with self.assertNumQueries(9):
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id, self.project.id, [feature_flag], "", {"organization": "unknown-new-org"}
                ).get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )

        # now with overrides - only query to get group type mappings
        with self.assertNumQueries(4):
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag],
                    "",
                    {"organization": "target_group"},
                    group_property_value_overrides={"organization": {"name": "x"}},
                ).get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )
        with self.assertNumQueries(4):
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag],
                    "",
                    {"organization": "unknown-new-org"},
                    group_property_value_overrides={"organization": {"name": "x"}},
                ).get_match(feature_flag),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )

        # now queries with additional flags - check if existence queries are made for different group types / persons

        # no extra query for second group type because groups not passed in
        with self.assertNumQueries(9):
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag, feature_flag_different_group],
                    "",
                    {"organization": "target_group"},
                ).get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )

        # no extra query for second group type because unknown group not passed in
        with self.assertNumQueries(9):
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag, feature_flag_unknown_group_type],
                    "",
                    {"organization": "target_group"},
                ).get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )
        # 4 extra query to query group (including setting timeout)
        # second extra query to check existence
        with self.assertNumQueries(11):
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag, feature_flag_different_group],
                    "",
                    {"organization": "target_group", "project": "shazam"},
                ).get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )

        # override means one less query to fetch group property values
        # TODO: We still make a query for existence check, but this is unnecessary. Consider optimising.
        with self.assertNumQueries(10):
            matcher = FeatureFlagMatcher(
                self.team.id,
                self.project.id,
                [feature_flag, feature_flag_different_group],
                "",
                {"organization": "target_group", "project": "shazam"},
                group_property_value_overrides={"project": {"name": "x"}},
            )
            self.assertEqual(
                matcher.get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )
            self.assertEqual(
                matcher.get_match(feature_flag_different_group),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )

        # 9 queries same as before for groups, 4 extra for person existence check (including timeouts), 1 extra for person query
        with self.assertNumQueries(11):
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag, feature_flag_with_person_is_not_set],
                    "random_id",
                    {"organization": "target_group"},
                ).get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )

        # 9 queries same as before for groups, 1 extra for person existence check, no person query because overrides
        # TODO: We still make a query for existence check, but this is unnecessary. Consider optimising.
        with self.assertNumQueries(10):
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag, feature_flag_with_person_is_not_set],
                    "random_id",
                    {"organization": "target_group"},
                    property_value_overrides={"email": "x"},
                ).get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )

        # no existence check for person because flag has not is_not_set condition
        with self.assertNumQueries(10):
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag, feature_flag_with_no_person_is_not_set],
                    "random_id",
                    {"organization": "target_group"},
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

        with self.assertNumQueries(8):
            # single query for all cohorts
            # no team queries
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
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

        with self.assertNumQueries(8):
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag1, feature_flag2],
                    "example_id",
                    property_value_overrides={},
                ).get_match(feature_flag1),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )

        with self.assertNumQueries(7):
            # no local computation because cohort lookup is required
            # no postgres person query required here to get the person, because email is sufficient
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag1, feature_flag2],
                    "example_id",
                    property_value_overrides={"email": "bzz"},
                ).get_match(feature_flag1),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )

        with self.assertNumQueries(7):
            # no postgres query required here to get the person
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag1, feature_flag2],
                    "example_id",
                    property_value_overrides={"email": "neil@posthog.com"},
                ).get_match(feature_flag1),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )

        with self.assertNumQueries(7):
            # Random person doesn't yet exist, but still should resolve thanks to overrides
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag1, feature_flag2],
                    "random_id",
                    property_value_overrides={"email": "xxx"},
                ).get_match(feature_flag2),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )

        with self.assertNumQueries(7):
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag1, feature_flag2],
                    "random_id",
                    property_value_overrides={"email": "example@posthog.com"},
                ).get_match(feature_flag2),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )

    def test_cohort_filters_with_override_id_property(self):
        cohort1 = Cohort.objects.create(
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
            name="cohort1",
        )

        feature_flag1: FeatureFlag = self.create_feature_flag(
            key="x1",
            filters={"groups": [{"properties": [{"key": "id", "value": cohort1.pk, "type": "cohort"}]}]},
        )
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com"},
        )

        with self.assertNumQueries(8):
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag1],
                    "example_id",
                    property_value_overrides={},
                ).get_match(feature_flag1),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )

        with self.assertNumQueries(7):
            # no local computation because cohort lookup is required
            # no postgres person query required here to get the person, because email is sufficient
            # property id override shouldn't confuse the matcher
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag1],
                    "example_id",
                    property_value_overrides={"id": "example_id", "email": "bzz"},
                ).get_match(feature_flag1),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )

        with self.assertNumQueries(7):
            # no postgres query required here to get the person
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag1],
                    "example_id",
                    property_value_overrides={"id": "second_id", "email": "neil@posthog.com"},
                ).get_match(feature_flag1),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )

        with self.assertNumQueries(8):
            # postgres query required here to get the person
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag1],
                    "example_id",
                    property_value_overrides={"id": "second_id"},
                ).get_match(feature_flag1),
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
                    self.team.id,
                    self.project.id,
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
                    self.team.id,
                    self.project.id,
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

        with self.assertNumQueries(8):
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id, self.project.id, [feature_flag1], "example_id", property_value_overrides={}
                ).get_match(feature_flag1),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )

        with self.assertNumQueries(8):
            # no local computation because cohort lookup is required
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
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
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "example_id_1").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "another_id").get_match(feature_flag),
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
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "example_id_4").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "example_id_5").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )

        matches = []
        for i in range(1, 7):
            distinct_id = f"example_id_{i}"
            match = FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], distinct_id).get_match(
                feature_flag
            )
            matches.append((match.match, match.reason))

        expanded_filters = feature_flag.transform_cohort_filters_for_easy_evaluation()
        feature_flag.delete()

        feature_flag_expanded: FeatureFlag = self.create_feature_flag(key=ff_key, filters={"groups": expanded_filters})

        expanded_matches = []
        for i in range(1, 7):
            distinct_id = f"example_id_{i}"
            match = FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag_expanded], distinct_id).get_match(
                feature_flag_expanded
            )
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
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "example_id_1").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "3").get_match(feature_flag),
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
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "example_id_1").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )

    def test_legacy_rollout_percentage(self):
        feature_flag = self.create_feature_flag(rollout_percentage=50)
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "another_id").get_match(feature_flag),
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
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "another_id").get_match(feature_flag),
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
                FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "example_id").get_match(feature_flag),
                FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
            )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "another_id").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "id_number_3").get_match(feature_flag),
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
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "example_id_2").get_match(feature_flag),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "another_id").get_match(feature_flag),
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
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "11").get_match(feature_flag),
            FeatureFlagMatch(
                True,
                variant="first-variant",
                reason=FeatureFlagMatchReason.CONDITION_MATCH,
                condition_index=0,
            ),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "example_id").get_match(feature_flag),
            FeatureFlagMatch(
                True,
                variant="second-variant",
                reason=FeatureFlagMatchReason.CONDITION_MATCH,
                condition_index=0,
            ),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "3").get_match(feature_flag),
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
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "").get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_GROUP_TYPE),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "", {"unknown": "group_key"}).get_match(
                feature_flag
            ),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_GROUP_TYPE),
        )
        self.assertEqual(
            FeatureFlagMatcher(
                self.team.id, self.project.id, [feature_flag], "", {"organization": "group_key"}
            ).get_match(feature_flag),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_GROUP_TYPE),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "", {"project": "group_key"}).get_match(
                feature_flag
            ),
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
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "", {"project": "1"}).get_match(
                feature_flag
            ),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.OUT_OF_ROLLOUT_BOUND, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "", {"project": "4"}).get_match(
                feature_flag
            ),
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
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "", {"organization": "foo"}).get_match(
                feature_flag
            ),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            FeatureFlagMatcher(self.team.id, self.project.id, [feature_flag], "", {"organization": "bar"}).get_match(
                feature_flag
            ),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )

    def create_groups(self):
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="project", group_type_index=1
        )

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

    @pytest.mark.skip("This case doesn't work yet, which is a bit problematic")
    @snapshot_postgres_queries
    def test_property_with_double_underscores(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["307"],
            properties={"org__member_count": 15},
        )
        # double scores in key name are interpreted in the ORM as a nested property.
        # Unclear if there's a way to solve this, other than moving away from the ORM.
        # But, we're doing that anyway with the rust rewrite, so not fixing for now.

        feature_flag1 = self.create_feature_flag(
            key="random1",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "org__member_count",
                                "value": "9",
                                "operator": "gt",
                                "type": "person",
                            },
                        ]
                    }
                ]
            },
        )

        self.assertEqual(
            self.match_flag(feature_flag1, "307"),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

    def test_numeric_operator(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["307"],
            properties={"number": 30, "string_number": "30", "version": "1.24"},
        )

        feature_flag1 = self.create_feature_flag(
            key="random1",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "number",
                                "value": "100",
                                "operator": "gt",
                                "type": "person",
                            },
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
                                "key": "number",
                                "value": "100b2c",
                                "operator": "gt",
                                "type": "person",
                            },
                        ]
                    }
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
                                "key": "number",
                                "value": "3.1x00b2c",
                                "operator": "gt",
                                "type": "person",
                            },
                        ]
                    }
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
                                "key": "number",
                                "value": "20",
                                "operator": "gt",
                                "type": "person",
                            },
                        ]
                    }
                ]
            },
        )

        feature_flag5 = self.create_feature_flag(
            key="random5",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "version",
                                "value": "1.05",
                                "operator": "gt",
                                "type": "person",
                            },
                        ]
                    },
                    {
                        "properties": [
                            {
                                "key": "version",
                                "value": "1.15",
                                "operator": "gt",
                                "type": "person",
                            },
                        ]
                    },
                    {
                        "properties": [
                            {
                                "key": "version",
                                "value": "1.1200",
                                "operator": "gt",
                                "type": "person",
                            },
                        ]
                    },
                ]
            },
        )

        feature_flag6 = self.create_feature_flag(
            key="random6",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "version",
                                "value": "1.206.0",
                                "operator": "lt",
                                "type": "person",
                            },
                        ]
                    }
                ]
            },
        )

        self.assertEqual(
            self.match_flag(feature_flag1, "307"),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(feature_flag2, "307"),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(feature_flag3, "307"),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(feature_flag4, "307"),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        # even though we can parse as a number, only do string comparison
        self.assertEqual(
            self.match_flag(feature_flag5, "307"),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(feature_flag6, "307"),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )

    def test_numeric_operator_with_groups_and_person_flags(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["307"],
            properties={"number": 30, "string_number": "30", "version": "1.24"},
        )
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="project", group_type_index=1
        )

        Group.objects.create(
            team=self.team,
            group_type_index=0,
            group_key="foo",
            group_properties={"name": "foo.inc", "number": 50, "string_number": "50"},
            version=1,
        )
        Group.objects.create(
            team=self.team,
            group_type_index=1,
            group_key="foo-project",
            group_properties={"name": "foo-project", "number": 20, "string_number": "20"},
            version=1,
        )

        feature_flag1 = self.create_feature_flag(
            key="random1",
            filters={
                "aggregation_group_type_index": 0,
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "number",
                                "value": "100",
                                "operator": "gt",
                                "group_type_index": 0,
                                "type": "group",
                            },
                        ]
                    }
                ],
            },
        )

        feature_flag2 = self.create_feature_flag(
            key="random2",
            filters={
                "aggregation_group_type_index": 1,
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "number",
                                "value": "100b2c",
                                "operator": "gt",
                                "group_type_index": 1,
                                "type": "group",
                            },
                        ]
                    }
                ],
            },
        )

        feature_flag3 = self.create_feature_flag(
            key="random3",
            filters={
                "aggregation_group_type_index": 0,
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "number",
                                "value": "3.1x00b2c",
                                "operator": "gte",
                                "type": "person",
                                "group_type_index": 0,
                                "type": "group",
                            },
                        ]
                    }
                ],
            },
        )

        feature_flag4 = self.create_feature_flag(
            key="random4",
            filters={
                "aggregation_group_type_index": 0,
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "number",
                                "value": "20",
                                "operator": "gt",
                                "group_type_index": 0,
                                "type": "group",
                            },
                        ]
                    }
                ],
            },
        )

        feature_flag4_person = self.create_feature_flag(
            key="random4_person",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "number",
                                "value": "20",
                                "operator": "gte",
                                "type": "person",
                            },
                        ]
                    }
                ]
            },
        )

        feature_flag5 = self.create_feature_flag(
            key="random5",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "version",
                                "value": "1.05",
                                "operator": "gt",
                                "type": "person",
                            },
                        ]
                    },
                    {
                        "properties": [
                            {
                                "key": "version",
                                "value": "1.15",
                                "operator": "gt",
                                "type": "person",
                            },
                        ]
                    },
                    {
                        "properties": [
                            {
                                "key": "version",
                                "value": "1.1200",
                                "operator": "gte",
                                "type": "person",
                            },
                        ]
                    },
                ]
            },
        )

        feature_flag6 = self.create_feature_flag(
            key="random6",
            filters={
                "aggregation_group_type_index": 0,
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "version",
                                "value": "1.206.0",
                                "operator": "lt",
                                "group_type_index": 0,
                                "type": "group",
                            },
                        ]
                    }
                ],
            },
        )

        self.assertEqual(
            self.match_flag(feature_flag1, "307", groups={"organization": "foo", "project": "foo-project"}),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(feature_flag2, "307", groups={"organization": "foo", "project": "foo-project"}),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(feature_flag3, "307", groups={"organization": "foo", "project": "foo-project"}),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(feature_flag4, "307", groups={"organization": "foo", "project": "foo-project"}),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        # even though we can parse as a number, only do string comparison
        self.assertEqual(
            self.match_flag(feature_flag5, "307", groups={"organization": "foo", "project": "foo-project"}),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(feature_flag6, "307", groups={"organization": "foo", "project": "foo-project"}),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )

        # Make sure clashes on property name doesn't affect computation
        with snapshot_postgres_queries_context(self, replace_all_numbers=False):
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag1, feature_flag2, feature_flag4_person],
                    "307",
                    groups={"organization": "foo", "project": "foo-project"},
                ).get_matches_with_details()[1],
                {
                    "random1": {
                        "condition_index": 0,
                        "reason": FeatureFlagMatchReason.NO_CONDITION_MATCH,
                    },
                    "random2": {
                        "condition_index": 0,
                        "reason": FeatureFlagMatchReason.CONDITION_MATCH,
                    },
                    "random4_person": {
                        "condition_index": 0,
                        "reason": FeatureFlagMatchReason.CONDITION_MATCH,
                    },
                },
            )

        # handle overrides in group properties
        self.assertEqual(
            self.match_flag(
                feature_flag1,
                "307",
                groups={"organization": "foo", "project": "foo-project"},
                group_property_value_overrides={"organization": {"number": 200}, "project": {"number": 1}},
            ),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        # string '30' > string '100' (lexicographically)
        self.assertEqual(
            self.match_flag(
                feature_flag1,
                "307",
                groups={"organization": "foo", "project": "foo-project"},
                group_property_value_overrides={"organization": {"number": "30"}, "project": {"number": 1}},
            ),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(
                feature_flag1,
                "307",
                groups={"organization": "foo", "project": "foo-project"},
                group_property_value_overrides={"organization": {"number": "01323"}, "project": {"number": 1}},
            ),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(
                feature_flag1,
                "307",
                groups={"organization": "foo", "project": "foo-project"},
                group_property_value_overrides={"organization": {"number": 0}, "project": {"number": 1}},
            ),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(
                feature_flag2,
                "307",
                groups={"organization": "foo", "project": "foo-project"},
                group_property_value_overrides={"organization": {"number": "0"}, "project": {"number": 19.999999}},
            ),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

    def test_numeric_operator_with_cohorts_and_nested_cohorts(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["307"],
            properties={"number": 30, "string_number": "30", "version": "1.24", "nested_prop": 21},
        )
        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "number",
                            "value": "100",
                            "type": "person",
                            "operator": "gt",
                        }
                    ]
                }
            ],
        )
        feature_flag1 = self.create_feature_flag(
            key="random1",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "id",
                                "value": cohort1.pk,
                                "type": "cohort",
                            },
                        ]
                    }
                ]
            },
        )

        self.assertEqual(
            self.match_flag(feature_flag1, "307"),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )

        cohort2 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "version",
                            "value": "1.05",
                            "operator": "gt",
                            "type": "person",
                        },
                    ]
                }
            ],
        )
        feature_flag2 = self.create_feature_flag(
            key="random2",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "id",
                                "value": cohort2.pk,
                                "type": "cohort",
                            },
                        ]
                    }
                ]
            },
        )

        self.assertEqual(
            self.match_flag(feature_flag2, "307"),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        cohort_nest = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "nested_prop",
                            "value": "20",
                            "operator": "gt",
                            "type": "person",
                        },
                    ]
                }
            ],
        )

        cohort3 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "number",
                            "value": "31",
                            "operator": "lt",
                            "type": "person",
                        },
                        {
                            "key": "id",
                            "value": str(cohort_nest.pk),
                            "type": "cohort",
                        },
                    ]
                }
            ],
        )
        feature_flag3 = self.create_feature_flag(
            key="random3",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "id",
                                "value": str(cohort3.pk),
                                "type": "cohort",
                            },
                        ]
                    }
                ]
            },
        )

        self.assertEqual(
            self.match_flag(feature_flag3, "307"),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        # Make sure clashes on property name doesn't affect computation
        with snapshot_postgres_queries_context(self, replace_all_numbers=False):
            self.assertEqual(
                FeatureFlagMatcher(
                    self.team.id,
                    self.project.id,
                    [feature_flag1, feature_flag2, feature_flag3],
                    "307",
                ).get_matches_with_details()[1],
                {
                    "random1": {
                        "condition_index": 0,
                        "reason": FeatureFlagMatchReason.NO_CONDITION_MATCH,
                    },
                    "random2": {
                        "condition_index": 0,
                        "reason": FeatureFlagMatchReason.CONDITION_MATCH,
                    },
                    "random3": {
                        "condition_index": 0,
                        "reason": FeatureFlagMatchReason.CONDITION_MATCH,
                    },
                },
            )

    @snapshot_postgres_queries
    def test_with_sql_injection_properties_and_other_aliases(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["307"],
            properties={
                "number space": 30,
                ";'\" SELECT 1; DROP TABLE posthog_featureflag;": "30",
                "version!!!": "1.24",
                "nested_prop --random #comment //test": 21,
            },
        )
        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "number space",
                            "value": "100",
                            "type": "person",
                            "operator": "gt",
                        },
                        {
                            "key": ";'\" SELECT 1; DROP TABLE posthog_featureflag;",
                            "value": "100",
                            "type": "person",
                            "operator": "gt",
                        },
                    ]
                }
            ],
        )
        feature_flag1 = self.create_feature_flag(
            key="random1",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "id",
                                "value": cohort1.pk,
                                "type": "cohort",
                            },
                        ]
                    },
                    {
                        "properties": [
                            {
                                "key": ";'\" SELECT 1; DROP TABLE posthog_featureflag;",
                                "value": "100",
                                "type": "person",
                                "operator": "gt",
                            },
                        ]
                    },
                    {
                        "properties": [
                            {
                                "key": "version!!!",
                                "value": "1.05",
                                "operator": "gt",
                                "type": "person",
                            },
                        ]
                    },
                    {
                        "properties": [
                            {
                                "key": "nested_prop --random #comment //test",
                                "value": "21",
                                "type": "person",
                            },
                        ],
                    },
                ]
            },
        )

        self.assertEqual(
            self.match_flag(feature_flag1, "307"),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 1),
        )

    @freeze_time("2022-05-01")
    def test_relative_date_operator(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["307"],
            properties={
                "date_1": "2022-04-30",
                "date_2": "2022-03-01",
                "date_3": "2022-04-30T12:00:00-10:00",
                "date_invalid": "2022-3443",
            },
        )

        feature_flag1 = self.create_feature_flag(
            key="random1",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "date_1",
                                "value": "6h",
                                "operator": "is_date_before",
                                "type": "person",
                            },
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
                                "key": "date_3",
                                "value": "2d",
                                "operator": "is_date_after",
                                "type": "person",
                            },
                        ]
                    }
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
                                "key": "date_3",
                                "value": "2h",
                                "operator": "is_date_after",
                                "type": "person",
                            },
                        ]
                    }
                ]
            },
        )

        feature_flag4_invalid_prop = self.create_feature_flag(
            key="random4",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "date_invalid",
                                "value": "2h",
                                "operator": "is_date_after",
                                "type": "person",
                            },
                        ]
                    }
                ]
            },
        )

        feature_flag5_invalid_flag = self.create_feature_flag(
            key="random5",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "date_1",
                                "value": "bazinga",
                                "operator": "is_date_after",
                                "type": "person",
                            },
                        ]
                    }
                ]
            },
        )

        self.assertEqual(
            self.match_flag(feature_flag1, "307"),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        self.assertEqual(
            self.match_flag(feature_flag2, "307"),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        # now move current date to 2022-05-02
        with freeze_time("2022-05-02T08:00:00-10:00"):
            self.assertEqual(
                self.match_flag(feature_flag2, "307"),
                FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
            )

        self.assertEqual(
            self.match_flag(feature_flag3, "307"),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )
        # :TRICKY: String matching means invalid props can be appropriately targeted
        self.assertEqual(
            self.match_flag(feature_flag4_invalid_prop, "307"),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        # invalid flags never return True
        self.assertEqual(
            self.match_flag(feature_flag5_invalid_flag, "307"),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )

        # try matching all together, invalids don't interfere with regular flags
        featureFlags, _, payloads, errors, _ = FeatureFlagMatcher(
            self.team.id,
            self.project.id,
            [feature_flag1, feature_flag2, feature_flag3, feature_flag4_invalid_prop, feature_flag5_invalid_flag],
            "307",
        ).get_matches_with_details()

        self.assertEqual(
            featureFlags,
            {"random1": True, "random2": True, "random3": False, "random4": True, "random5": False},
            {
                "random1": {
                    "condition_index": 0,
                    "reason": FeatureFlagMatchReason.CONDITION_MATCH,
                },
                "random2": {
                    "condition_index": 0,
                    "reason": FeatureFlagMatchReason.CONDITION_MATCH,
                },
                "random3": {
                    "condition_index": 0,
                    "reason": FeatureFlagMatchReason.NO_CONDITION_MATCH,
                },
                "random4": {
                    "condition_index": 0,
                    "reason": FeatureFlagMatchReason.CONDITION_MATCH,
                },
                "random5": {
                    "condition_index": 0,
                    "reason": FeatureFlagMatchReason.NO_CONDITION_MATCH,
                },
            },
        )
        self.assertEqual(payloads, {})
        self.assertEqual(errors, False)

        # confirm it works with overrides as well, which are computed locally
        self.assertEqual(
            self.match_flag(feature_flag1, "307", property_value_overrides={"date_1": "2021-01-04"}),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(feature_flag1, "307", property_value_overrides={"date_1": "2023-01-04"}),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(feature_flag1, "307", property_value_overrides={"date_1": "2022-04-30T08:01:00-10:00"}),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(feature_flag1, "307", property_value_overrides={"date_1": "2022-04-30T07:59:00-10:00"}),
            FeatureFlagMatch(True, None, FeatureFlagMatchReason.CONDITION_MATCH, 0),
        )

        # test with invalid date
        self.assertEqual(
            self.match_flag(feature_flag1, "307", property_value_overrides={"date_1": "bazinga"}),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(
                feature_flag5_invalid_flag, "307", property_value_overrides={"date_1": "2022-04-30T07:59:00-10:00"}
            ),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(feature_flag5_invalid_flag, "307", property_value_overrides={"date_1": "2022-04-30"}),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )
        self.assertEqual(
            self.match_flag(feature_flag5_invalid_flag, "307", property_value_overrides={"date_1": datetime.now()}),
            FeatureFlagMatch(False, None, FeatureFlagMatchReason.NO_CONDITION_MATCH, 0),
        )

    def test_date_string_property_matching_iso8601(self):
        """Test that date string properties in ISO8601 format are correctly compared with is_date_after operator.

        This test reproduces a scenario where:
        - A person has last_active_date: "2024-03-15T19:17:07.083Z"
        - Flag condition checks if this is after "2024-03-15 19:37:00"
        - Expected: Should NOT match since 19:17 is before 19:37
        """
        # First, test a simple case with just the date condition
        Person.objects.create(
            team=self.team,
            distinct_ids=["test_user_123"],
            properties={
                "last_active_date": "2024-03-15T19:17:07.083Z",
            },
        )

        simple_flag = self.create_feature_flag(
            key="date-comparison-test",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "last_active_date",
                                "type": "person",
                                "value": "2024-03-15 19:37:00",
                                "operator": "is_date_after",
                            }
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

        # This should NOT match because 19:17 is NOT after 19:37
        simple_match = self.match_flag(simple_flag, "test_user_123")
        self.assertEqual(
            simple_match.match, False, f"Flag should NOT match: 19:17:07 is not after 19:37:00. Got: {simple_match}"
        )

        # Now test the full multivariate scenario
        Person.objects.create(
            team=self.team,
            distinct_ids=["test_user_456"],
            properties={
                "user_id": "test_456",
                "last_active_date": "2024-03-15T19:17:07.083Z",
                "segment": None,
            },
        )

        # Create flag with multivariate structure
        feature_flag = self.create_feature_flag(
            key="multivariate-date-test",
            filters={
                "groups": [
                    {"variant": None, "properties": [], "rollout_percentage": 100},
                    {
                        "variant": "experimental",
                        "properties": [{"key": "segment", "type": "person", "value": ["premium"], "operator": "exact"}],
                        "rollout_percentage": 100,
                    },
                    {
                        "variant": "experimental",
                        "properties": [
                            {
                                "key": "last_active_date",
                                "type": "person",
                                "value": "2024-03-15 19:37:00",  # 20 minutes after the person's time
                                "operator": "is_date_after",
                            }
                        ],
                        "rollout_percentage": 100,
                    },
                ],
                "payloads": {},
                "multivariate": {
                    "variants": [
                        {
                            "key": "control",
                            "name": "Control variant",
                            "rollout_percentage": 50,
                        },
                        {"key": "experimental", "name": "Experimental variant", "rollout_percentage": 50},
                    ]
                },
            },
        )

        # Test the match
        match_result = self.match_flag(feature_flag, "test_user_456")

        # The first group (100% rollout, no conditions) should match
        self.assertEqual(match_result.match, True)
        # But the variant should NOT be "experimental" since the date condition doesn't match
        # (19:17 is before 19:37)
        self.assertNotEqual(match_result.variant, "experimental")
        # It should match the first condition group (index 0)
        self.assertEqual(match_result.condition_index, 0)

        # Test with different date formats to ensure parsing works correctly
        test_cases = [
            # Person's time is before filter time - should NOT get "experimental" variant
            ("2024-03-15T19:17:07.083Z", "2024-03-15 19:37:00", False),
            # Person's time is after filter time - should get "experimental" variant
            ("2024-03-15T19:45:00.000Z", "2024-03-15 19:37:00", True),
            # Same time - should NOT match (is_date_after requires strictly after)
            ("2024-03-15T19:37:00.000Z", "2024-03-15 19:37:00", False),
            # Test with timezone offset
            ("2024-03-15T19:17:07.083+00:00", "2024-03-15 19:37:00", False),
        ]

        for person_date, filter_date, should_match_date_condition in test_cases:
            with self.subTest(person_date=person_date, filter_date=filter_date):
                # Update the flag's filter value
                feature_flag.filters["groups"][2]["properties"][0]["value"] = filter_date
                feature_flag.save()

                # Test with property override (simulates real-time evaluation)
                match_result = self.match_flag(
                    feature_flag,
                    "test_user_456",
                    property_value_overrides={"last_active_date": person_date},
                )

                # First group always matches
                self.assertEqual(match_result.match, True)

                if should_match_date_condition:
                    # Should get "experimental" variant from the third group
                    self.assertEqual(match_result.variant, "experimental")
                    self.assertEqual(match_result.condition_index, 2)
                else:
                    # Should NOT get "experimental" variant
                    self.assertNotEqual(match_result.variant, "experimental")
                    # Should match first group
                    self.assertEqual(match_result.condition_index, 0)


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
            team=self.team,
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
            team=self.team,
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

        set_feature_flag_hash_key_overrides(team=self.team, distinct_ids=["1"], hash_key_override="other_id1")
        set_feature_flag_hash_key_overrides(team=self.team, distinct_ids=["2"], hash_key_override="aother_id2")

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
            team=self.team,
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
            team=self.team,
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
        flags, reasons, payloads, _ = get_all_feature_flags(self.team, "other_id", {}, "example_id")
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
                    team,
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
                team, "other_id", {}, hash_key_override="example_id"
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

        with (
            snapshot_postgres_queries_context(self, capture_all_queries=True),
            connection.execute_wrapper(InsertFailOnce()),
        ):
            flags, reasons, payloads, errors = get_all_feature_flags(
                team, "other_id", {}, hash_key_override="example_id"
            )
            assert errors is False
            # overrides succeeded on second try
            assert flags == {
                "beta-feature": True,
                "multivariate-flag": "first-variant",
                "default-flag": True,
            }

    @flaky(max_runs=3, min_passes=1)
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
                    team,
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

            feature_flag_match = FeatureFlagMatcher(
                self.team.id, self.project.id, [feature_flag], distinctID
            ).get_match(feature_flag)

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

            feature_flag_match = FeatureFlagMatcher(
                self.team.id, self.project.id, [feature_flag], distinctID
            ).get_match(feature_flag)

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
