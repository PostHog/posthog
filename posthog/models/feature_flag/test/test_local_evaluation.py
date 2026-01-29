from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.cohort.cohort import Cohort
from posthog.models.feature_flag.feature_flag import FeatureFlag, FeatureFlagEvaluationTag
from posthog.models.feature_flag.local_evaluation import (
    _get_flags_for_local_evaluation,
    _get_flags_response_for_local_evaluation,
    _get_flags_response_for_local_evaluation_batch,
    clear_flag_caches,
    flags_hypercache,
    get_flags_response_for_local_evaluation,
    update_flag_caches,
)
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


class TestBatchLocalEvaluation(BaseTest):
    """Tests for batch loading optimization that reduces N+1 queries."""

    def test_batch_loading_produces_same_results_as_individual_loading(self):
        """
        Demonstrates the fix: batch loading multiple teams produces identical results
        to loading teams individually, but with far fewer database queries.

        Before the fix: Loading N teams would make N+1 queries for each data type
        After the fix: Loading N teams makes only 4 total queries (surveys, flags, cohorts, group mappings)
        """
        # Create multiple teams with flags and cohorts
        teams = []
        for i in range(3):
            project, team = Project.objects.create_with_team(
                initiating_user=self.user,
                organization=self.organization,
                name=f"Test project {i}",
            )

            # Create a cohort for each team
            cohort = Cohort.objects.create(
                team=team,
                filters={
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "OR",
                                "values": [
                                    {
                                        "key": f"$team_{i}_prop",
                                        "value": f"value_{i}",
                                        "type": "person",
                                    }
                                ],
                            }
                        ],
                    }
                },
                name=f"cohort_{i}",
            )

            # Create flags with cohort filters
            FeatureFlag.objects.create(
                team=team,
                key=f"flag-{i}",
                filters={
                    "groups": [
                        {
                            "rollout_percentage": 50 + i * 10,
                            "properties": [{"key": "id", "type": "cohort", "value": cohort.pk}],
                        }
                    ],
                },
            )

            # Create a survey flag that should be excluded
            survey_flag = FeatureFlag.objects.create(
                team=team,
                key=f"survey-flag-{i}",
                filters={"groups": [{"rollout_percentage": 100}]},
            )

            Survey.objects.create(
                team=team,
                name=f"Survey {i}",
                type="popover",
                targeting_flag=survey_flag,
            )

            # Create group type mapping
            create_group_type_mapping_without_created_at(
                team=team, project_id=team.project_id, group_type=f"company_{i}", group_type_index=i
            )

            teams.append(team)

        # Load data using the batch function (the fix)
        batch_results = _get_flags_response_for_local_evaluation_batch(teams, include_cohorts=True)

        # Load data individually (the old way)
        individual_results = {}
        for team in teams:
            individual_results[team.id] = _get_flags_response_for_local_evaluation(team, include_cohorts=True)

        # Verify batch results match individual results
        assert len(batch_results) == len(individual_results) == 3

        for team in teams:
            batch_result = batch_results[team.id]
            individual_result = individual_results[team.id]

            # Check flags match
            assert len(batch_result["flags"]) == len(individual_result["flags"]) == 1
            assert batch_result["flags"][0]["key"] == individual_result["flags"][0]["key"]

            # Check survey flags are excluded
            flag_keys = [f["key"] for f in batch_result["flags"]]
            assert f"flag-{teams.index(team)}" in flag_keys
            assert f"survey-flag-{teams.index(team)}" not in flag_keys

            # Check cohorts match
            assert len(batch_result["cohorts"]) == len(individual_result["cohorts"]) == 1
            assert batch_result["cohorts"] == individual_result["cohorts"]

            # Check group type mappings match
            assert batch_result["group_type_mapping"] == individual_result["group_type_mapping"]

    def test_batch_loading_reduces_database_queries(self):
        """
        Demonstrates the N+1 query problem fix.

        Before: Loading N teams individually would result in many queries per team
        After: Loading N teams in batch results in only 4 queries total
        """
        # Create 5 teams with flags and cohorts
        teams = []
        for i in range(5):
            project, team = Project.objects.create_with_team(
                initiating_user=self.user,
                organization=self.organization,
                name=f"Batch test project {i}",
            )

            cohort = Cohort.objects.create(
                team=team,
                filters={"properties": {"type": "OR", "values": []}},
                name=f"batch_cohort_{i}",
            )

            FeatureFlag.objects.create(
                team=team,
                key=f"batch-flag-{i}",
                filters={
                    "groups": [
                        {
                            "rollout_percentage": 100,
                            "properties": [{"key": "id", "type": "cohort", "value": cohort.pk}],
                        }
                    ],
                },
            )

            teams.append(team)

        # Test batch loading query count
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as batch_context:
            batch_results = _get_flags_response_for_local_evaluation_batch(teams, include_cohorts=True)

        # The batch function should make a fixed number of queries regardless of team count:
        # 1. Load all survey flag IDs
        # 2. Load all feature flags
        # 3. Load all cohorts
        # 4. Load all group type mappings
        # Plus minimal serialization queries
        batch_query_count = len(batch_context.captured_queries)

        # Test individual loading query count (old approach)
        individual_query_count = 0
        for team in teams:
            with CaptureQueriesContext(connection) as individual_context:
                _get_flags_response_for_local_evaluation(team, include_cohorts=True)
            individual_query_count += len(individual_context.captured_queries)

        # Batch loading should use significantly fewer queries than individual loading
        assert batch_query_count < individual_query_count, (
            f"Batch loading should use fewer queries than individual loading. "
            f"Got batch={batch_query_count}, individual={individual_query_count}"
        )

        # Batch loading should be roughly constant (not scale with number of teams)
        # Allow some overhead for serialization and other operations
        assert batch_query_count < 20, f"Batch loading made {batch_query_count} queries, expected < 20"

        # Individual loading should use more queries (demonstrating the fix for inefficiency)
        # With 5 teams, we expect at least 30% more queries for individual loading
        assert individual_query_count >= batch_query_count * 1.3, (
            f"Individual loading should make notably more queries than batch loading. "
            f"Got individual={individual_query_count}, batch={batch_query_count}, "
            f"ratio={individual_query_count / batch_query_count:.2f}x"
        )

        # Verify results are correct
        assert len(batch_results) == 5
        for team in teams:
            assert team.id in batch_results
            assert len(batch_results[team.id]["flags"]) >= 1

    def test_batch_loading_handles_empty_teams_list(self):
        """Batch loading should handle edge case of empty teams list."""
        result = _get_flags_response_for_local_evaluation_batch([], include_cohorts=True)
        assert result == {}

    def test_batch_loading_with_and_without_cohorts(self):
        """
        Batch loading should work correctly for both cache variants
        (with cohorts and without cohorts).
        """
        teams = []
        for i in range(2):
            project, team = Project.objects.create_with_team(
                initiating_user=self.user,
                organization=self.organization,
                name=f"Variant test project {i}",
            )

            cohort = Cohort.objects.create(
                team=team,
                filters={
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "OR",
                                "values": [{"key": "email", "value": "test@example.com", "type": "person"}],
                            }
                        ],
                    }
                },
                name=f"variant_cohort_{i}",
            )

            FeatureFlag.objects.create(
                team=team,
                key=f"variant-flag-{i}",
                filters={
                    "groups": [
                        {
                            "rollout_percentage": 100,
                            "properties": [{"key": "id", "type": "cohort", "value": cohort.pk}],
                        }
                    ],
                },
            )

            teams.append(team)

        # Test with cohorts
        results_with_cohorts = _get_flags_response_for_local_evaluation_batch(teams, include_cohorts=True)

        for team in teams:
            result = results_with_cohorts[team.id]
            assert len(result["cohorts"]) > 0, "Should include cohorts when include_cohorts=True"
            assert len(result["flags"]) == 1

        # Test without cohorts
        results_without_cohorts = _get_flags_response_for_local_evaluation_batch(teams, include_cohorts=False)

        for team in teams:
            result = results_without_cohorts[team.id]
            assert len(result["cohorts"]) == 0, "Should not include cohorts when include_cohorts=False"
            assert len(result["flags"]) == 1
