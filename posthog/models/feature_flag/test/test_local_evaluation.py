from posthog.test.base import BaseTest
from unittest.mock import patch

from django.conf import settings
from django.core.cache import caches
from django.test import override_settings

from parameterized import parameterized

from posthog.caching.flags_redis_cache import FLAGS_DEDICATED_CACHE_ALIAS
from posthog.models.cohort.cohort import Cohort
from posthog.models.feature_flag.feature_flag import FeatureFlag, FeatureFlagEvaluationTag
from posthog.models.feature_flag.local_evaluation import (
    FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG,
    FLAG_DEFINITIONS_NO_COHORTS_HYPERCACHE_MANAGEMENT_CONFIG,
    _get_flags_for_local_evaluation,
    clear_flag_caches,
    clear_flag_definition_caches,
    flags_hypercache,
    flags_without_cohorts_hypercache,
    get_flags_response_for_local_evaluation,
    update_flag_caches,
    update_flag_definitions_cache,
    verify_team_flag_definitions,
)
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.project import Project
from posthog.models.surveys.survey import Survey
from posthog.models.tag import Tag
from posthog.models.team.team import Team
from posthog.test.test_utils import create_group_type_mapping_without_created_at


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
        clear_flag_caches(self.team)

    def _create_examples(self, team: Team):
        FeatureFlag.objects.all().delete()

        cohorts = []
        flags = []

        create_group_type_mapping_without_created_at(
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

    def _assert_payload_valid_with_cohorts(self, response: dict | None):
        assert response is not None
        assert len(response.get("flags", [])) == 2
        assert response.get("group_type_mapping", {}) == {"0": "organization"}
        assert len(response.get("cohorts", {})) == 2

    def test_generates_correct_local_evaluation_response_with_cohorts(self):
        response = get_flags_response_for_local_evaluation(self.team, include_cohorts=True)
        assert response
        assert len(response.get("flags", [])) == 2
        assert response.get("group_type_mapping", {}) == {"0": "organization"}
        assert len(response.get("cohorts", {})) == 2

    def test_generates_correct_local_evaluation_response_without_cohorts(self):
        response = get_flags_response_for_local_evaluation(self.team, include_cohorts=False)
        assert response
        assert len(response.get("flags", [])) == 2
        assert response.get("group_type_mapping", {}) == {"0": "organization"}
        assert len(response.get("cohorts", {})) == 0

    def test_get_flags_cache_hot(self):
        update_flag_caches(self.team)
        response, source = flags_hypercache.get_from_cache_with_source(self.team)
        assert source == "redis"
        self._assert_payload_valid_with_cohorts(response)

    def test_get_flags_cache_warm(self):
        update_flag_caches(self.team)
        clear_flag_caches(self.team, kinds=["redis"])
        response, source = flags_hypercache.get_from_cache_with_source(self.team)
        assert source == "s3"
        self._assert_payload_valid_with_cohorts(response)

    def test_get_flags_cold(self):
        clear_flag_caches(self.team, kinds=["redis", "s3"])
        response, source = flags_hypercache.get_from_cache_with_source(self.team)
        assert source == "db"
        self._assert_payload_valid_with_cohorts(response)

        # second request should be cached in redis
        response, source = flags_hypercache.get_from_cache_with_source(self.team)
        assert source == "redis"
        self._assert_payload_valid_with_cohorts(response)


class TestLocalEvaluationSignals(BaseTest):
    @patch("posthog.tasks.feature_flags.update_team_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_signal_fired_on_evaluation_tag_create(self, mock_task):
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        mock_task.reset_mock()

        tag = Tag.objects.create(team=self.team, name="docs-page")
        FeatureFlagEvaluationTag.objects.create(feature_flag=flag, tag=tag)

        mock_task.delay.assert_called_once_with(self.team.id)

    @patch("posthog.tasks.feature_flags.update_team_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_signal_fired_on_evaluation_tag_delete(self, mock_task):
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        tag = Tag.objects.create(team=self.team, name="docs-page")
        eval_tag = FeatureFlagEvaluationTag.objects.create(feature_flag=flag, tag=tag)

        mock_task.reset_mock()

        eval_tag.delete()

        mock_task.delay.assert_called_once_with(self.team.id)

    @patch("posthog.tasks.feature_flags.update_team_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_signal_fired_on_tag_rename(self, mock_task):
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        tag = Tag.objects.create(team=self.team, name="docs-page")
        FeatureFlagEvaluationTag.objects.create(feature_flag=flag, tag=tag)

        mock_task.reset_mock()

        # Rename the tag
        tag.name = "landing-page"
        tag.save()

        mock_task.delay.assert_called_once_with(self.team.id)

    @patch("posthog.tasks.feature_flags.update_team_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_signal_not_fired_on_tag_rename_when_not_used_by_flags(self, mock_task):
        # Create a tag that is not used by any flag
        tag = Tag.objects.create(team=self.team, name="unused-tag")

        mock_task.reset_mock()

        # Rename the tag
        tag.name = "still-unused-tag"
        tag.save()

        # Signal should NOT trigger the Celery task since no flags use this tag
        mock_task.delay.assert_not_called()

    @patch("posthog.tasks.feature_flags.update_team_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_signal_fired_once_when_tag_used_by_multiple_flags(self, mock_task):
        """Tag used by multiple flags should trigger cache update once per team."""
        tag = Tag.objects.create(team=self.team, name="shared-tag")

        for i in range(3):
            flag = FeatureFlag.objects.create(
                team=self.team,
                key=f"flag-{i}",
                created_by=self.user,
                filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
            )
            FeatureFlagEvaluationTag.objects.create(feature_flag=flag, tag=tag)

        mock_task.reset_mock()

        tag.name = "renamed-shared-tag"
        tag.save()

        # Should fire once (team-level), not 3 times (flag-level)
        mock_task.delay.assert_called_once_with(self.team.id)

    @patch("posthog.tasks.feature_flags.update_team_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_signal_not_fired_on_tag_creation(self, mock_task):
        """Signal should not fire when a new tag is created."""
        mock_task.reset_mock()

        # Create a new tag
        Tag.objects.create(team=self.team, name="brand-new-tag")

        # Signal should NOT trigger because new tags can't be used by any flags yet
        mock_task.delay.assert_not_called()


class TestSurveyFlagExclusion(BaseTest):
    """Tests for excluding survey-linked flags from local evaluation (GitHub issue #43631)."""

    def setUp(self):
        super().setUp()
        # Clear existing flags and caches to ensure test isolation
        FeatureFlag.objects.filter(team=self.team).delete()
        Survey.objects.filter(team=self.team).delete()
        clear_flag_caches(self.team)
        clear_flag_definition_caches(self.team)

    @parameterized.expand(
        [
            ("targeting_flag", "targeting_flag"),
            ("internal_targeting_flag", "internal_targeting_flag"),
            ("internal_response_sampling_flag", "internal_response_sampling_flag"),
        ]
    )
    def test_survey_linked_flag_excluded_from_local_evaluation(self, _name: str, flag_field: str):
        regular_flag = FeatureFlag.objects.create(
            team=self.team,
            key="regular-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        survey_flag = FeatureFlag.objects.create(
            team=self.team,
            key=f"survey-{flag_field}-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        Survey.objects.create(
            team=self.team,
            name="Test Survey",
            type="popover",
            **{flag_field: survey_flag},
        )

        flags, _ = _get_flags_for_local_evaluation(self.team, include_cohorts=True)
        flag_keys = [f.key for f in flags]

        assert regular_flag.key in flag_keys
        assert survey_flag.key not in flag_keys

    def test_linked_flag_not_excluded_from_local_evaluation(self):
        """The linked_flag field is user-created and should NOT be excluded."""
        user_linked_flag = FeatureFlag.objects.create(
            team=self.team,
            key="user-linked-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        Survey.objects.create(
            team=self.team,
            name="Test Survey",
            type="popover",
            linked_flag=user_linked_flag,
        )

        flags, _ = _get_flags_for_local_evaluation(self.team, include_cohorts=True)
        flag_keys = [f.key for f in flags]

        assert user_linked_flag.key in flag_keys

    def test_deleted_survey_does_not_affect_flag_exclusion(self):
        """Flags from deleted surveys should be included in local evaluation."""
        survey_flag = FeatureFlag.objects.create(
            team=self.team,
            key="was-survey-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        survey = Survey.objects.create(
            team=self.team,
            name="Test Survey",
            type="popover",
            targeting_flag=survey_flag,
        )

        flags, _ = _get_flags_for_local_evaluation(self.team, include_cohorts=True)
        assert survey_flag.key not in [f.key for f in flags]

        survey.delete()

        flags, _ = _get_flags_for_local_evaluation(self.team, include_cohorts=True)
        assert survey_flag.key in [f.key for f in flags]

    def test_survey_flags_excluded_from_api_response(self):
        """Verify the full API response excludes survey flags."""
        regular_flag = FeatureFlag.objects.create(
            team=self.team,
            key="regular-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        survey_flag = FeatureFlag.objects.create(
            team=self.team,
            key="survey-targeting-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        Survey.objects.create(
            team=self.team,
            name="Test Survey",
            type="popover",
            internal_targeting_flag=survey_flag,
        )

        response = get_flags_response_for_local_evaluation(self.team, include_cohorts=True)
        assert response is not None
        flag_keys = [f["key"] for f in response["flags"]]

        assert regular_flag.key in flag_keys
        assert survey_flag.key not in flag_keys

    @patch("posthog.tasks.feature_flags.update_team_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_flag_cache_invalidated_on_survey_change(self, mock_task):
        """Creating/deleting a survey should invalidate the flag cache."""
        survey_flag = FeatureFlag.objects.create(
            team=self.team,
            key="survey-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        mock_task.reset_mock()

        survey = Survey.objects.create(
            team=self.team,
            name="Test Survey",
            type="popover",
            targeting_flag=survey_flag,
        )

        mock_task.delay.assert_called_with(self.team.id)

        mock_task.reset_mock()

        survey.delete()

        mock_task.delay.assert_called_with(self.team.id)

    @patch("posthog.tasks.feature_flags.update_team_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_flag_cache_invalidated_on_survey_update(self, mock_task):
        """Updating a survey should invalidate the flag cache."""
        survey_flag = FeatureFlag.objects.create(
            team=self.team,
            key="survey-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        survey = Survey.objects.create(
            team=self.team,
            name="Test Survey",
            type="popover",
            targeting_flag=survey_flag,
        )

        mock_task.reset_mock()

        survey.name = "Updated Survey Name"
        survey.save()

        mock_task.delay.assert_called_with(self.team.id)

    def test_archived_survey_flag_still_excluded(self):
        """Flags from archived surveys should still be excluded from local evaluation."""
        survey_flag = FeatureFlag.objects.create(
            team=self.team,
            key="archived-survey-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        survey = Survey.objects.create(
            team=self.team,
            name="Test Survey",
            type="popover",
            targeting_flag=survey_flag,
        )

        flags, _ = _get_flags_for_local_evaluation(self.team, include_cohorts=True)
        assert survey_flag.key not in [f.key for f in flags]

        # Archive the survey (not delete)
        survey.archived = True
        survey.save()

        # Flag should still be excluded since the survey still exists
        flags, _ = _get_flags_for_local_evaluation(self.team, include_cohorts=True)
        assert survey_flag.key not in [f.key for f in flags]

    def test_survey_flag_reassignment_updates_exclusions(self):
        """When a survey changes which flags it uses, both old and new flags should update correctly."""
        flag_a = FeatureFlag.objects.create(
            team=self.team,
            key="flag-a",
            filters={"groups": [{"rollout_percentage": 100}]},
        )
        flag_b = FeatureFlag.objects.create(
            team=self.team,
            key="flag-b",
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        survey = Survey.objects.create(
            team=self.team,
            name="Test Survey",
            type="popover",
            targeting_flag=flag_a,
        )

        flags, _ = _get_flags_for_local_evaluation(self.team, include_cohorts=True)
        flag_keys = [f.key for f in flags]
        assert flag_a.key not in flag_keys
        assert flag_b.key in flag_keys

        survey.targeting_flag = flag_b
        survey.save()

        flags, _ = _get_flags_for_local_evaluation(self.team, include_cohorts=True)
        flag_keys = [f.key for f in flags]
        assert flag_a.key in flag_keys
        assert flag_b.key not in flag_keys

    def test_multiple_surveys_sharing_same_flag(self):
        """When multiple surveys use the same flag, it should be excluded once."""
        shared_flag = FeatureFlag.objects.create(
            team=self.team,
            key="shared-targeting-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        for i in range(3):
            Survey.objects.create(
                team=self.team,
                name=f"Survey {i}",
                type="popover",
                targeting_flag=shared_flag,
            )

        flags, _ = _get_flags_for_local_evaluation(self.team, include_cohorts=True)
        flag_keys = [f.key for f in flags]

        assert shared_flag.key not in flag_keys

    def test_survey_with_partial_flag_assignment(self):
        """Survey with some flags set and others None should only exclude the set flags."""
        flag_a = FeatureFlag.objects.create(
            team=self.team,
            key="targeting-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )
        flag_b = FeatureFlag.objects.create(
            team=self.team,
            key="sampling-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )
        regular_flag = FeatureFlag.objects.create(
            team=self.team,
            key="regular-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        Survey.objects.create(
            team=self.team,
            name="Test Survey",
            type="popover",
            targeting_flag=flag_a,
            internal_targeting_flag=None,
            internal_response_sampling_flag=flag_b,
        )

        flags, _ = _get_flags_for_local_evaluation(self.team, include_cohorts=True)
        flag_keys = [f.key for f in flags]

        assert flag_a.key not in flag_keys
        assert flag_b.key not in flag_keys
        assert regular_flag.key in flag_keys


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestFlagDefinitionsCache(BaseTest):
    """Tests for flag definitions HyperCache operations with dual-write support."""

    def setUp(self):
        super().setUp()
        clear_flag_definition_caches(self.team, kinds=["redis", "s3"])

    def test_update_flag_definitions_cache_updates_both_variants(self):
        """Test that update_flag_definitions_cache updates both with/without cohorts variants."""
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        result = update_flag_definitions_cache(self.team)
        assert result is True

        # Both variants should be cached
        with_cohorts, source1 = flags_hypercache.get_from_cache_with_source(self.team)
        without_cohorts, source2 = flags_without_cohorts_hypercache.get_from_cache_with_source(self.team)

        assert source1 == "redis"
        assert source2 == "redis"
        assert with_cohorts is not None
        assert without_cohorts is not None
        assert len(with_cohorts["flags"]) == 1
        assert len(without_cohorts["flags"]) == 1

    def test_update_flag_definitions_cache_accepts_team_id(self):
        """Test that update_flag_definitions_cache accepts team ID instead of Team object."""
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        result = update_flag_definitions_cache(self.team.id)
        assert result is True

        data, source = flags_hypercache.get_from_cache_with_source(self.team)
        assert source == "redis"
        assert data is not None
        assert len(data["flags"]) == 1

    def test_update_flag_definitions_cache_returns_false_for_nonexistent_team(self):
        """Test that update_flag_definitions_cache returns False for non-existent team ID."""
        result = update_flag_definitions_cache(999999)
        assert result is False

    def test_clear_flag_definition_caches_clears_both_variants(self):
        """Test that clearing caches removes both with/without cohorts variants."""
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Warm both caches
        update_flag_definitions_cache(self.team)

        # Verify caches exist
        _, source1 = flags_hypercache.get_from_cache_with_source(self.team)
        _, source2 = flags_without_cohorts_hypercache.get_from_cache_with_source(self.team)
        assert source1 == "redis"
        assert source2 == "redis"

        # Clear caches
        clear_flag_definition_caches(self.team, kinds=["redis", "s3"])

        # Both should now load from DB
        _, source1 = flags_hypercache.get_from_cache_with_source(self.team)
        _, source2 = flags_without_cohorts_hypercache.get_from_cache_with_source(self.team)
        assert source1 == "db"
        assert source2 == "db"

    def test_hypercache_configs_are_properly_configured(self):
        """Test that HyperCacheManagementConfigs have correct settings."""
        # With cohorts config
        config1 = FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG
        assert config1.cache_name == "flag_definitions"
        assert config1.hypercache == flags_hypercache
        assert config1.update_fn == update_flag_definitions_cache

        # Without cohorts config
        config2 = FLAG_DEFINITIONS_NO_COHORTS_HYPERCACHE_MANAGEMENT_CONFIG
        assert config2.cache_name == "flag_definitions_no_cohorts"
        assert config2.hypercache == flags_without_cohorts_hypercache
        assert config2.update_fn == update_flag_definitions_cache


@override_settings(
    FLAGS_REDIS_URL="redis://test",
    CACHES={
        **settings.CACHES,
        FLAGS_DEDICATED_CACHE_ALIAS: {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "flags-dedicated-dual-write-test",
        },
    },
)
class TestFlagDefinitionsDualWrite(BaseTest):
    """Tests for flag definitions dual-write to dedicated cache."""

    def setUp(self):
        super().setUp()
        clear_flag_definition_caches(self.team, kinds=["redis", "s3"])
        # Clear dedicated cache
        if FLAGS_DEDICATED_CACHE_ALIAS in settings.CACHES:
            caches[FLAGS_DEDICATED_CACHE_ALIAS].clear()

    def test_update_writes_to_dedicated_cache(self):
        """Test that update_flag_definitions_cache writes to dedicated cache."""
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        update_flag_definitions_cache(self.team)

        # Verify data in dedicated cache
        dedicated_cache = caches[FLAGS_DEDICATED_CACHE_ALIAS]
        for hypercache in [flags_hypercache, flags_without_cohorts_hypercache]:
            cache_key = hypercache.get_cache_key(self.team)
            cached_data = dedicated_cache.get(cache_key)
            assert cached_data is not None
            # Data is stored as JSON string in dedicated cache
            import json

            parsed = json.loads(cached_data)
            assert len(parsed["flags"]) == 1
            assert parsed["flags"][0]["key"] == "test-flag"

    def test_update_writes_etag_to_dedicated_cache(self):
        """Test that ETag is written to dedicated cache when enable_etag=True."""
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        update_flag_definitions_cache(self.team)

        # Verify ETag in dedicated cache
        dedicated_cache = caches[FLAGS_DEDICATED_CACHE_ALIAS]
        for hypercache in [flags_hypercache, flags_without_cohorts_hypercache]:
            etag_key = hypercache.get_etag_key(self.team)
            etag = dedicated_cache.get(etag_key)
            # ETag should be a hash string
            assert etag is not None
            assert len(etag) > 0

    def test_dedicated_cache_failure_does_not_abort_update(self):
        """Test that dedicated cache write failure doesn't prevent shared cache update."""
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Mock dedicated cache to raise exception
        with patch.object(caches[FLAGS_DEDICATED_CACHE_ALIAS], "set", side_effect=Exception("Cache write failed")):
            with patch.object(
                caches[FLAGS_DEDICATED_CACHE_ALIAS], "set_many", side_effect=Exception("Cache write failed")
            ):
                result = update_flag_definitions_cache(self.team)

        # Update should still succeed (shared cache was written)
        assert result is True

        # Shared cache should have the data
        data, source = flags_hypercache.get_from_cache_with_source(self.team)
        assert source == "redis"
        assert data is not None
        assert len(data["flags"]) == 1


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestVerifyFlagDefinitions(BaseTest):
    """Tests for flag definitions cache verification."""

    def setUp(self):
        super().setUp()
        clear_flag_definition_caches(self.team, kinds=["redis", "s3"])

    def test_verify_returns_miss_when_cache_empty(self):
        """Test that verification detects cache miss."""
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        result = verify_team_flag_definitions(self.team, include_cohorts=True)

        assert result["status"] == "miss"
        assert result["issue"] == "CACHE_MISS"

    def test_verify_returns_match_when_cache_matches(self):
        """Test that verification returns match when cache is correct."""
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Warm the cache
        update_flag_definitions_cache(self.team)

        result = verify_team_flag_definitions(self.team, include_cohorts=True)

        assert result["status"] == "match"
        assert result["issue"] == ""

    def test_verify_returns_mismatch_when_flag_changed(self):
        """Test that verification detects when flag has changed."""
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Warm the cache
        update_flag_definitions_cache(self.team)

        # Change the flag
        flag.key = "modified-flag"
        flag.save()

        result = verify_team_flag_definitions(self.team, include_cohorts=True, verbose=True)

        assert result["status"] == "mismatch"
        assert result["issue"] == "DATA_MISMATCH"
        assert "diffs" in result

    def test_verify_both_variants_independently(self):
        """Test that each variant can be verified independently."""
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Warm both caches
        update_flag_definitions_cache(self.team)

        # Verify both variants match
        result_with = verify_team_flag_definitions(self.team, include_cohorts=True)
        result_without = verify_team_flag_definitions(self.team, include_cohorts=False)

        assert result_with["status"] == "match"
        assert result_without["status"] == "match"

    def test_verify_returns_mismatch_when_cohort_changed(self):
        """Test that verification detects cohort definition changes."""
        # Create a cohort
        cohort = Cohort.objects.create(
            team=self.team,
            name="Test Cohort",
            groups=[{"properties": [{"key": "email", "value": "test@example.com", "type": "person"}]}],
        )

        # Create a flag that uses the cohort
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={
                "groups": [
                    {
                        "properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

        # Warm the cache (with cohorts variant)
        update_flag_definitions_cache(self.team)

        # Change the cohort definition
        cohort.groups = [{"properties": [{"key": "email", "value": "changed@example.com", "type": "person"}]}]
        cohort.save()

        result = verify_team_flag_definitions(self.team, include_cohorts=True, verbose=True)

        assert result["status"] == "mismatch"
        assert result["issue"] == "DATA_MISMATCH"
        # Should detect cohorts mismatch
        assert "diffs" in result
        cohorts_diff = [d for d in result["diffs"] if d.get("type") == "COHORTS_MISMATCH"]
        assert len(cohorts_diff) == 1

    def test_verify_returns_mismatch_when_group_type_mapping_changed(self):
        """Test that verification detects group type mapping changes."""
        # Create group type mapping
        GroupTypeMapping.objects.create(
            team=self.team,
            project_id=self.team.project_id,
            group_type="company",
            group_type_index=0,
        )

        # Create a flag with group-based targeting
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={
                "aggregation_group_type_index": 0,
                "groups": [{"properties": [], "rollout_percentage": 100}],
            },
        )

        # Warm the cache
        update_flag_definitions_cache(self.team)

        # Change the group type mapping
        mapping = GroupTypeMapping.objects.get(team=self.team, group_type_index=0)
        mapping.group_type = "organization"
        mapping.save()

        result = verify_team_flag_definitions(self.team, include_cohorts=True, verbose=True)

        assert result["status"] == "mismatch"
        assert result["issue"] == "DATA_MISMATCH"
        # Should detect group type mapping mismatch
        assert "diffs" in result
        mapping_diff = [d for d in result["diffs"] if d.get("type") == "GROUP_TYPE_MAPPING_MISMATCH"]
        assert len(mapping_diff) == 1


@override_settings(
    FLAGS_REDIS_URL="redis://test",
    CACHES={
        **settings.CACHES,
        "flags_dedicated": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "flags-definitions-test",
        },
    },
)
class TestFlagDefinitionsManagementCommands(BaseTest):
    """Tests for flag definitions cache management commands."""

    def setUp(self):
        super().setUp()
        clear_flag_definition_caches(self.team, kinds=["redis", "s3"])

    def test_verify_command_specific_teams(self):
        """Test verify_flag_definitions_cache command with specific teams."""
        from io import StringIO

        from django.core.management import call_command

        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        out = StringIO()
        call_command("verify_flag_definitions_cache", f"--team-ids={self.team.id}", stdout=out)

        output = out.getvalue()
        assert "Verification Results" in output
        assert "Total teams verified: 1" in output

    def test_verify_command_with_variant_flag(self):
        """Test verify command with --variant flag for single variant verification."""
        from io import StringIO

        from django.core.management import call_command

        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Test with-cohorts variant
        out = StringIO()
        call_command(
            "verify_flag_definitions_cache",
            f"--team-ids={self.team.id}",
            "--variant=with-cohorts",
            stdout=out,
        )

        output = out.getvalue()
        assert "with cohorts" in output
        # Should only verify one variant, not both
        assert output.count("Verification Results") == 1

    def test_warm_command_specific_teams(self):
        """Test warm_flag_definitions_cache command with specific teams."""
        from io import StringIO

        from django.core.management import call_command

        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        out = StringIO()
        call_command("warm_flag_definitions_cache", f"--team-ids={self.team.id}", stdout=out)

        output = out.getvalue()
        assert "Flag definitions cache warm completed" in output or "Total teams: 1" in output

    def test_warm_command_with_variant_flag(self):
        """Test warm command with --variant flag for single variant warming."""
        from io import StringIO

        from django.core.management import call_command

        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Test with-cohorts variant only
        out = StringIO()
        call_command(
            "warm_flag_definitions_cache",
            f"--team-ids={self.team.id}",
            "--variant=with-cohorts",
            stdout=out,
        )

        output = out.getvalue()
        assert "with cohorts" in output


@override_settings(FLAGS_REDIS_URL=None)
class TestFlagDefinitionsCacheWithoutRedis(BaseTest):
    """Test flag definitions cache behavior when FLAGS_REDIS_URL is not set."""

    def test_update_flag_definitions_cache_returns_false_without_redis(self):
        """Test update returns False when FLAGS_REDIS_URL not configured."""
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        result = update_flag_definitions_cache(self.team)

        # Without Redis URL configured, the HyperCache will still work but won't track expiry
        # The update should complete successfully
        assert result is True

    def test_management_commands_error_without_redis_url(self):
        """Test management commands fail gracefully without FLAGS_REDIS_URL."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("verify_flag_definitions_cache", f"--team-ids={self.team.id}", stdout=out)

        output = out.getvalue()
        assert "FLAGS_REDIS_URL" in output
        assert "NOT configured" in output
