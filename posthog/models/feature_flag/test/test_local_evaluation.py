from decimal import Decimal
from unittest.mock import patch

from parameterized import parameterized
from django.test import RequestFactory
from inline_snapshot import snapshot
import pytest
from posthog.models.action.action import Action
from posthog.models.cohort.cohort import Cohort
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.surveys.survey import Survey
from posthog.models.hog_functions.hog_function import HogFunction, HogFunctionType
from posthog.models.plugin import Plugin, PluginConfig, PluginSourceFile
from posthog.models.project import Project
from posthog.models.feature_flag.local_evaluation import FeatureFlagLocalEvaluationCache
from posthog.models.team.team import Team
from posthog.test.base import BaseTest
from django.core.cache import cache
from django.utils import timezone

CONFIG_REFRESH_QUERY_COUNT = 5


class TestLocalEvaluationCache(BaseTest):
    def setUp(self):
        super().setUp()
        project, team = Project.objects.create_with_team(
            initiating_user=self.user,
            organization=self.organization,
            name="Test project",
        )
        self.team = team
        self._create_examples(self.team)
        FeatureFlagLocalEvaluationCache.clear_cache(self.team)

    def _create_examples(self, team: Team):
        FeatureFlag.objects.all().delete()

        cohorts = []
        flags = []

        GroupTypeMapping.objects.create(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )

        cohort_valid_for_ff = Cohort.objects.create(
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
        cohorts.append(cohort_valid_for_ff)

        cohort2 = Cohort.objects.create(
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
                                    "key": "id",
                                    "value": cohort_valid_for_ff.pk,
                                    "type": "cohort",
                                    "negation": True,
                                },
                            ],
                        }
                    ],
                }
            },
            name="cohort2",
        )
        cohorts.append(cohort2)

        ff1 = FeatureFlag.objects.create(
            team=self.team,
            key="alpha-feature",
            filters={
                "groups": [
                    {
                        "rollout_percentage": 20,
                        "properties": [{"key": "id", "type": "cohort", "value": cohort2.pk}],
                    }
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
            },
        )
        flags.append(ff1)

        ff2 = FeatureFlag.objects.create(
            team=self.team,
            key="alpha-feature-2",
            filters={
                "groups": [
                    {
                        "rollout_percentage": 20,
                        "properties": [{"key": "id", "type": "cohort", "value": cohort_valid_for_ff.pk}],
                    }
                ],
            },
        )

        flags.append(ff2)

        return flags, cohorts

    def _assert_payload_valid_with_cohorts(self, response: dict):
        assert len(response.get("flags", [])) == 2
        assert response.get("group_type_mapping", {}) == {"0": "organization"}
        assert len(response.get("cohorts", {})) == 2

    def test_generates_correct_local_evaluation_response_with_cohorts(self):
        response = FeatureFlagLocalEvaluationCache.get_flags_response_for_local_evaluation(
            self.team, include_cohorts=True
        )

        assert len(response.get("flags", [])) == 2
        assert response.get("group_type_mapping", {}) == {"0": "organization"}
        assert len(response.get("cohorts", {})) == 2

    def test_generates_correct_local_evaluation_response_without_cohorts(self):
        response = FeatureFlagLocalEvaluationCache.get_flags_response_for_local_evaluation(
            self.team, include_cohorts=False
        )

        assert len(response.get("flags", [])) == 2
        assert response.get("group_type_mapping", {}) == {"0": "organization"}
        assert len(response.get("cohorts", {})) == 0

    def test_get_flags_cache_hot(self):
        FeatureFlagLocalEvaluationCache.update_cache(self.team)
        response, source = FeatureFlagLocalEvaluationCache.get_flags_response_for_local_evaluation_from_cache(
            self.team, include_cohorts=True
        )
        assert source == "redis"
        self._assert_payload_valid_with_cohorts(response)

    def test_get_flags_cache_warm(self):
        FeatureFlagLocalEvaluationCache.update_cache(self.team)
        FeatureFlagLocalEvaluationCache.clear_cache(self.team, kinds=["redis"])
        response, source = FeatureFlagLocalEvaluationCache.get_flags_response_for_local_evaluation_from_cache(
            self.team, include_cohorts=True
        )
        assert source == "s3"
        self._assert_payload_valid_with_cohorts(response)

    def test_get_flags_cold(self):
        FeatureFlagLocalEvaluationCache.clear_cache(self.team, kinds=["redis", "s3"])
        response, source = FeatureFlagLocalEvaluationCache.get_flags_response_for_local_evaluation_from_cache(
            self.team, include_cohorts=True
        )

        assert source == "postgres"
        self._assert_payload_valid_with_cohorts(response)

        # second request should be cached in redis

        response, source = FeatureFlagLocalEvaluationCache.get_flags_response_for_local_evaluation_from_cache(
            self.team, include_cohorts=True
        )

        assert source == "redis"
        self._assert_payload_valid_with_cohorts(response)
