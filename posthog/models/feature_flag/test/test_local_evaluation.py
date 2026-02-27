from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.models.cohort.cohort import Cohort
from posthog.models.feature_flag.feature_flag import FeatureFlag, FeatureFlagEvaluationTag
from posthog.models.feature_flag.local_evaluation import (
    FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG,
    FLAG_DEFINITIONS_NO_COHORTS_HYPERCACHE_MANAGEMENT_CONFIG,
    _extract_cohort_ids_from_filters,
    _get_flags_response_for_local_evaluation,
    _get_flags_response_for_local_evaluation_batch,
    _update_flag_definitions_with_cohorts,
    _update_flag_definitions_without_cohorts,
    clear_flag_definition_caches,
    flag_definitions_hypercache,
    flag_definitions_without_cohorts_hypercache,
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
        clear_flag_definition_caches(self.team)

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
        response, source = flag_definitions_hypercache.get_from_cache_with_source(self.team)
        assert source == "redis"
        self._assert_payload_valid_with_cohorts(response)

    def test_get_flags_cache_warm(self):
        update_flag_caches(self.team)
        clear_flag_definition_caches(self.team, kinds=["redis"])
        response, source = flag_definitions_hypercache.get_from_cache_with_source(self.team)
        assert source == "s3"
        self._assert_payload_valid_with_cohorts(response)

    def test_get_flags_cold(self):
        clear_flag_definition_caches(self.team, kinds=["redis", "s3"])
        response, source = flag_definitions_hypercache.get_from_cache_with_source(self.team)
        assert source == "db"
        self._assert_payload_valid_with_cohorts(response)

        # second request should be cached in redis
        response, source = flag_definitions_hypercache.get_from_cache_with_source(self.team)
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

        response = _get_flags_response_for_local_evaluation(self.team, include_cohorts=True)
        flag_keys = [f["key"] for f in response["flags"]]

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

        response = _get_flags_response_for_local_evaluation(self.team, include_cohorts=True)
        flag_keys = [f["key"] for f in response["flags"]]

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

        response = _get_flags_response_for_local_evaluation(self.team, include_cohorts=True)
        assert survey_flag.key not in [f["key"] for f in response["flags"]]

        survey.delete()

        response = _get_flags_response_for_local_evaluation(self.team, include_cohorts=True)
        assert survey_flag.key in [f["key"] for f in response["flags"]]

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

        response = _get_flags_response_for_local_evaluation(self.team, include_cohorts=True)
        assert survey_flag.key not in [f["key"] for f in response["flags"]]

        # Archive the survey (not delete)
        survey.archived = True
        survey.save()

        # Flag should still be excluded since the survey still exists
        response = _get_flags_response_for_local_evaluation(self.team, include_cohorts=True)
        assert survey_flag.key not in [f["key"] for f in response["flags"]]

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

        response = _get_flags_response_for_local_evaluation(self.team, include_cohorts=True)
        flag_keys = [f["key"] for f in response["flags"]]
        assert flag_a.key not in flag_keys
        assert flag_b.key in flag_keys

        survey.targeting_flag = flag_b
        survey.save()

        response = _get_flags_response_for_local_evaluation(self.team, include_cohorts=True)
        flag_keys = [f["key"] for f in response["flags"]]
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

        response = _get_flags_response_for_local_evaluation(self.team, include_cohorts=True)
        flag_keys = [f["key"] for f in response["flags"]]

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

        response = _get_flags_response_for_local_evaluation(self.team, include_cohorts=True)
        flag_keys = [f["key"] for f in response["flags"]]

        assert flag_a.key not in flag_keys
        assert flag_b.key not in flag_keys
        assert regular_flag.key in flag_keys


class TestExtractCohortIdsFromFilters(BaseTest):
    @parameterized.expand(
        [
            ("empty_filters", {}, set()),
            ("no_groups", {"multivariate": {}}, set()),
            ("empty_groups", {"groups": []}, set()),
            (
                "person_properties_only",
                {"groups": [{"properties": [{"type": "person", "key": "email", "value": "test@example.com"}]}]},
                set(),
            ),
            ("single_cohort", {"groups": [{"properties": [{"type": "cohort", "value": 123}]}]}, {123}),
            (
                "multiple_cohorts_same_group",
                {"groups": [{"properties": [{"type": "cohort", "value": 1}, {"type": "cohort", "value": 2}]}]},
                {1, 2},
            ),
            (
                "cohorts_across_groups",
                {
                    "groups": [
                        {"properties": [{"type": "cohort", "value": 10}]},
                        {"properties": [{"type": "cohort", "value": 20}]},
                    ]
                },
                {10, 20},
            ),
            ("string_value_coerced", {"groups": [{"properties": [{"type": "cohort", "value": "456"}]}]}, {456}),
            ("invalid_string_skipped", {"groups": [{"properties": [{"type": "cohort", "value": "bad"}]}]}, set()),
            ("none_value_skipped", {"groups": [{"properties": [{"type": "cohort", "value": None}]}]}, set()),
            (
                "duplicates_collapsed",
                {
                    "groups": [
                        {"properties": [{"type": "cohort", "value": 5}]},
                        {"properties": [{"type": "cohort", "value": 5}]},
                    ]
                },
                {5},
            ),
        ]
    )
    def test_extract_cohort_ids(self, _name: str, filters: dict, expected: set):
        assert _extract_cohort_ids_from_filters(filters) == expected


class TestLocalEvaluationBatch(BaseTest):
    def _create_team_with_project(self, name: str) -> Team:
        project, team = Project.objects.create_with_team(
            initiating_user=self.user,
            organization=self.organization,
            name=name,
        )
        return team

    def test_batch_empty_team_list(self):
        result = _get_flags_response_for_local_evaluation_batch([], True)
        assert result == {}

    def test_batch_two_teams_flags_isolated(self):
        team_a = self._create_team_with_project("Team A")
        team_b = self._create_team_with_project("Team B")

        FeatureFlag.objects.create(
            team=team_a,
            key="flag-a",
            filters={"groups": [{"rollout_percentage": 100}]},
        )
        FeatureFlag.objects.create(
            team=team_b,
            key="flag-b",
            filters={"groups": [{"rollout_percentage": 50}]},
        )

        results = _get_flags_response_for_local_evaluation_batch([team_a, team_b], True)

        assert team_a.id in results
        assert team_b.id in results

        keys_a = [f["key"] for f in results[team_a.id]["flags"]]
        keys_b = [f["key"] for f in results[team_b.id]["flags"]]

        assert keys_a == ["flag-a"]
        assert keys_b == ["flag-b"]

    def test_batch_team_with_no_flags(self):
        team_with_flags = self._create_team_with_project("Has Flags")
        team_without_flags = self._create_team_with_project("No Flags")

        FeatureFlag.objects.create(
            team=team_with_flags,
            key="some-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        results = _get_flags_response_for_local_evaluation_batch([team_with_flags, team_without_flags], True)

        assert len(results[team_with_flags.id]["flags"]) == 1
        assert results[team_without_flags.id]["flags"] == []
        assert "group_type_mapping" in results[team_without_flags.id]
        assert "cohorts" in results[team_without_flags.id]

    def test_batch_team_with_no_flags_includes_group_type_mapping(self):
        team = self._create_team_with_project("GTM Team")

        create_group_type_mapping_without_created_at(
            team=team, project_id=team.project_id, group_type="company", group_type_index=0
        )

        results = _get_flags_response_for_local_evaluation_batch([team], True)

        assert results[team.id]["flags"] == []
        assert results[team.id]["group_type_mapping"] == {"0": "company"}

    def test_batch_cohort_isolation_across_projects(self):
        team_a = self._create_team_with_project("Project A")
        team_b = self._create_team_with_project("Project B")

        cohort_a = Cohort.objects.create(
            team=team_a,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "email", "value": "a@a.com", "type": "person"}]}],
                }
            },
            name="cohort-a",
        )
        cohort_b = Cohort.objects.create(
            team=team_b,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "email", "value": "b@b.com", "type": "person"}]}],
                }
            },
            name="cohort-b",
        )

        FeatureFlag.objects.create(
            team=team_a,
            key="flag-with-cohort-a",
            filters={"groups": [{"properties": [{"key": "id", "type": "cohort", "value": cohort_a.pk}]}]},
        )
        FeatureFlag.objects.create(
            team=team_b,
            key="flag-with-cohort-b",
            filters={"groups": [{"properties": [{"key": "id", "type": "cohort", "value": cohort_b.pk}]}]},
        )

        results = _get_flags_response_for_local_evaluation_batch([team_a, team_b], True)

        cohort_ids_a = set(results[team_a.id]["cohorts"].keys())
        cohort_ids_b = set(results[team_b.id]["cohorts"].keys())

        assert str(cohort_a.pk) in cohort_ids_a
        assert str(cohort_b.pk) not in cohort_ids_a

        assert str(cohort_b.pk) in cohort_ids_b
        assert str(cohort_a.pk) not in cohort_ids_b

    def test_batch_only_loads_referenced_cohorts(self):
        """Cohorts not referenced by any flag filter should not appear in the response."""
        team = self._create_team_with_project("Selective Cohort Team")

        referenced_cohort = Cohort.objects.create(
            team=team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "email", "value": "a@a.com", "type": "person"}]}],
                }
            },
            name="referenced-cohort",
        )
        unreferenced_cohort = Cohort.objects.create(
            team=team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "email", "value": "b@b.com", "type": "person"}]}],
                }
            },
            name="unreferenced-cohort",
        )

        FeatureFlag.objects.create(
            team=team,
            key="flag-with-cohort",
            filters={"groups": [{"properties": [{"key": "id", "type": "cohort", "value": referenced_cohort.pk}]}]},
        )

        results = _get_flags_response_for_local_evaluation_batch([team], True)

        assert str(referenced_cohort.pk) in results[team.id]["cohorts"]
        assert str(unreferenced_cohort.pk) not in results[team.id]["cohorts"]

    def test_batch_static_cohort_excluded(self):
        """Static cohorts cannot be locally evaluated and should not appear in the response."""
        team = self._create_team_with_project("Static Cohort Team")

        static_cohort = Cohort.objects.create(
            team=team,
            name="static-cohort",
            is_static=True,
        )
        dynamic_cohort = Cohort.objects.create(
            team=team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "email", "value": "a@a.com", "type": "person"}]}],
                }
            },
            name="dynamic-cohort",
        )

        FeatureFlag.objects.create(
            team=team,
            key="flag-with-both",
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": "id", "type": "cohort", "value": static_cohort.pk},
                            {"key": "id", "type": "cohort", "value": dynamic_cohort.pk},
                        ]
                    }
                ]
            },
        )

        results = _get_flags_response_for_local_evaluation_batch([team], True)

        assert str(dynamic_cohort.pk) in results[team.id]["cohorts"]
        assert str(static_cohort.pk) not in results[team.id]["cohorts"]

    def test_batch_loads_nested_cohort_dependencies(self):
        """Cohorts referenced transitively through other cohorts should be loaded."""
        team = self._create_team_with_project("Nested Cohort Team")

        leaf_cohort = Cohort.objects.create(
            team=team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "email", "value": "a@a.com", "type": "person"}]}],
                }
            },
            name="leaf-cohort",
        )
        parent_cohort = Cohort.objects.create(
            team=team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {"type": "OR", "values": [{"key": "id", "value": leaf_cohort.pk, "type": "cohort"}]},
                    ],
                }
            },
            name="parent-cohort",
        )

        FeatureFlag.objects.create(
            team=team,
            key="flag-with-nested-cohort",
            filters={"groups": [{"properties": [{"key": "id", "type": "cohort", "value": parent_cohort.pk}]}]},
        )

        results = _get_flags_response_for_local_evaluation_batch([team], True)

        assert str(parent_cohort.pk) in results[team.id]["cohorts"]
        assert str(leaf_cohort.pk) in results[team.id]["cohorts"]

    def test_batch_loads_deeply_nested_cohort_chain(self):
        """Three-level cohort chain (grandparent -> parent -> leaf) exercises multiple iterations of the loading loop."""
        team = self._create_team_with_project("Deep Nesting Team")

        leaf = Cohort.objects.create(
            team=team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "email", "value": "a@a.com", "type": "person"}]}],
                }
            },
            name="leaf",
        )
        parent = Cohort.objects.create(
            team=team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "id", "value": leaf.pk, "type": "cohort"}]}],
                }
            },
            name="parent",
        )
        grandparent = Cohort.objects.create(
            team=team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "id", "value": parent.pk, "type": "cohort"}]}],
                }
            },
            name="grandparent",
        )

        FeatureFlag.objects.create(
            team=team,
            key="deep-flag",
            filters={"groups": [{"properties": [{"key": "id", "type": "cohort", "value": grandparent.pk}]}]},
        )

        results = _get_flags_response_for_local_evaluation_batch([team], True)
        cohort_ids = set(results[team.id]["cohorts"].keys())

        assert str(grandparent.pk) in cohort_ids
        assert str(parent.pk) in cohort_ids
        assert str(leaf.pk) in cohort_ids

    def test_batch_circular_cohort_references_terminate(self):
        """Circular cohort dependencies (A -> B -> A) should not cause an infinite loop."""
        team = self._create_team_with_project("Circular Cohort Team")

        cohort_a = Cohort.objects.create(
            team=team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "email", "value": "a@a.com", "type": "person"}]}],
                }
            },
            name="cohort-a",
        )
        cohort_b = Cohort.objects.create(
            team=team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "id", "value": cohort_a.pk, "type": "cohort"}]}],
                }
            },
            name="cohort-b",
        )

        # Create the circular reference: A -> B -> A
        cohort_a.filters = {
            "properties": {
                "type": "OR",
                "values": [{"type": "OR", "values": [{"key": "id", "value": cohort_b.pk, "type": "cohort"}]}],
            }
        }
        cohort_a.save()

        FeatureFlag.objects.create(
            team=team,
            key="circular-flag",
            filters={"groups": [{"properties": [{"key": "id", "type": "cohort", "value": cohort_a.pk}]}]},
        )

        results = _get_flags_response_for_local_evaluation_batch([team], True)
        cohort_ids = set(results[team.id]["cohorts"].keys())

        assert str(cohort_a.pk) in cohort_ids
        assert str(cohort_b.pk) in cohort_ids

    def test_batch_no_cohort_flags_skips_cohort_loading(self):
        """When no flags reference cohorts, the cohort query should be skipped entirely."""
        team = self._create_team_with_project("No Cohort Team")

        Cohort.objects.create(
            team=team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "email", "value": "a@a.com", "type": "person"}]}],
                }
            },
            name="unused-cohort",
        )

        FeatureFlag.objects.create(
            team=team,
            key="simple-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        with self.assertNumQueries(3):
            # Expected queries: survey flag IDs, flags (with evaluation
            # tags via ArrayAgg), and group type mappings. No cohort
            # query should be issued.
            results = _get_flags_response_for_local_evaluation_batch([team], True)

        assert results[team.id]["cohorts"] == {}
        assert len(results[team.id]["flags"]) == 1

    def test_batch_deleted_cohort_handled_gracefully(self):
        team = self._create_team_with_project("Deleted Cohort Team")

        cohort = Cohort.objects.create(
            team=team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "email", "value": "x@x.com", "type": "person"}]}],
                }
            },
            name="soon-deleted",
        )
        cohort_id = cohort.pk

        FeatureFlag.objects.create(
            team=team,
            key="flag-ref-deleted-cohort",
            filters={"groups": [{"properties": [{"key": "id", "type": "cohort", "value": cohort_id}]}]},
        )

        # Soft-delete the cohort
        cohort.deleted = True
        cohort.save()

        results = _get_flags_response_for_local_evaluation_batch([team], True)

        flag_keys = [f["key"] for f in results[team.id]["flags"]]
        assert "flag-ref-deleted-cohort" in flag_keys
        assert str(cohort_id) not in results[team.id]["cohorts"]


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestFlagDefinitionsCache(BaseTest):
    """Tests for flag definitions HyperCache operations."""

    def setUp(self):
        super().setUp()
        clear_flag_definition_caches(self.team, kinds=["redis", "s3"])

    def test_cache_key_format_is_stable(self):
        """
        Changing the key format would orphan existing cached data,
        causing a cold cache on deploy.
        """
        with_cohorts_key = flag_definitions_hypercache.get_cache_key(self.team)
        without_cohorts_key = flag_definitions_without_cohorts_hypercache.get_cache_key(self.team)

        assert with_cohorts_key == f"cache/teams/{self.team.id}/feature_flags/flags_with_cohorts.json"
        assert without_cohorts_key == f"cache/teams/{self.team.id}/feature_flags/flags_without_cohorts.json"

    def test_update_flag_definitions_cache_updates_both_variants(self):
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        result = update_flag_definitions_cache(self.team)
        assert result is True

        with_cohorts, source1 = flag_definitions_hypercache.get_from_cache_with_source(self.team)
        without_cohorts, source2 = flag_definitions_without_cohorts_hypercache.get_from_cache_with_source(self.team)

        assert source1 == "redis"
        assert source2 == "redis"
        assert with_cohorts is not None
        assert without_cohorts is not None
        assert len(with_cohorts["flags"]) == 1
        assert len(without_cohorts["flags"]) == 1

    def test_update_flag_definitions_cache_accepts_team_id(self):
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        result = update_flag_definitions_cache(self.team.id)
        assert result is True

        data, source = flag_definitions_hypercache.get_from_cache_with_source(self.team)
        assert source == "redis"
        assert data is not None
        assert len(data["flags"]) == 1

    def test_update_flag_definitions_cache_returns_false_for_nonexistent_team(self):
        result = update_flag_definitions_cache(999999)
        assert result is False

    def test_clear_flag_definition_caches_clears_both_variants(self):
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        update_flag_definitions_cache(self.team)

        _, source1 = flag_definitions_hypercache.get_from_cache_with_source(self.team)
        _, source2 = flag_definitions_without_cohorts_hypercache.get_from_cache_with_source(self.team)
        assert source1 == "redis"
        assert source2 == "redis"

        clear_flag_definition_caches(self.team, kinds=["redis", "s3"])

        _, source1 = flag_definitions_hypercache.get_from_cache_with_source(self.team)
        _, source2 = flag_definitions_without_cohorts_hypercache.get_from_cache_with_source(self.team)
        assert source1 == "db"
        assert source2 == "db"

    def test_hypercache_configs_are_properly_configured(self):
        config1 = FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG
        assert config1.cache_name == "flag_definitions"
        assert config1.hypercache == flag_definitions_hypercache
        assert config1.update_fn == _update_flag_definitions_with_cohorts

        config2 = FLAG_DEFINITIONS_NO_COHORTS_HYPERCACHE_MANAGEMENT_CONFIG
        assert config2.cache_name == "flag_definitions_no_cohorts"
        assert config2.hypercache == flag_definitions_without_cohorts_hypercache
        assert config2.update_fn == _update_flag_definitions_without_cohorts

    def test_update_flag_definitions_cache_returns_false_on_partial_failure(self):
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        with patch.object(flag_definitions_hypercache, "update_cache", return_value=False):
            result = update_flag_definitions_cache(self.team)

        assert result is False

        # The second variant should still have been updated
        _, source = flag_definitions_without_cohorts_hypercache.get_from_cache_with_source(self.team)
        assert source == "redis"

    def test_update_flag_definitions_cache_passes_custom_ttl(self):
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        with (
            patch.object(flag_definitions_hypercache, "update_cache", return_value=True) as mock_with,
            patch.object(
                flag_definitions_without_cohorts_hypercache, "update_cache", return_value=True
            ) as mock_without,
        ):
            update_flag_definitions_cache(self.team, ttl=3600)

        mock_with.assert_called_once_with(self.team, ttl=3600)
        mock_without.assert_called_once_with(self.team, ttl=3600)


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestVerifyFlagDefinitions(BaseTest):
    """Tests for flag definitions cache verification."""

    def setUp(self):
        super().setUp()
        clear_flag_definition_caches(self.team, kinds=["redis", "s3"])

    def test_verify_returns_miss_when_cache_empty(self):
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
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        update_flag_definitions_cache(self.team)

        result = verify_team_flag_definitions(self.team, include_cohorts=True)

        assert result["status"] == "match"
        assert result["issue"] == ""

    def test_verify_returns_mismatch_when_flag_key_renamed(self):
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        update_flag_definitions_cache(self.team)

        flag.key = "modified-flag"
        flag.save()

        result = verify_team_flag_definitions(self.team, include_cohorts=True, verbose=True)

        assert result["status"] == "mismatch"
        assert result["issue"] == "DATA_MISMATCH"
        assert "1 missing, 1 stale" in result["details"]
        missing_diffs = [d for d in result["diffs"] if d["type"] == "MISSING_IN_CACHE"]
        stale_diffs = [d for d in result["diffs"] if d["type"] == "STALE_IN_CACHE"]
        assert len(missing_diffs) == 1
        assert missing_diffs[0]["flag_key"] == "modified-flag"
        assert len(stale_diffs) == 1
        assert stale_diffs[0]["flag_key"] == "test-flag"

    def test_verify_returns_field_mismatch_when_flag_filters_changed(self):
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        update_flag_definitions_cache(self.team)

        flag.filters = {"groups": [{"properties": [], "rollout_percentage": 50}]}
        flag.save()

        result = verify_team_flag_definitions(self.team, include_cohorts=True, verbose=True)

        assert result["status"] == "mismatch"
        assert result["issue"] == "DATA_MISMATCH"
        assert "1 mismatched" in result["details"]
        field_mismatch_diffs = [d for d in result["diffs"] if d["type"] == "FIELD_MISMATCH"]
        assert len(field_mismatch_diffs) == 1
        assert field_mismatch_diffs[0]["flag_key"] == "test-flag"

    def test_verify_both_variants_independently(self):
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        update_flag_definitions_cache(self.team)

        result_with = verify_team_flag_definitions(self.team, include_cohorts=True)
        result_without = verify_team_flag_definitions(self.team, include_cohorts=False)

        assert result_with["status"] == "match"
        assert result_without["status"] == "match"

    def test_verify_returns_mismatch_when_cohort_changed(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="Test Cohort",
            groups=[{"properties": [{"key": "email", "value": "test@example.com", "type": "person"}]}],
        )

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

        update_flag_definitions_cache(self.team)

        cohort.groups = [{"properties": [{"key": "email", "value": "changed@example.com", "type": "person"}]}]
        cohort.save()

        result = verify_team_flag_definitions(self.team, include_cohorts=True, verbose=True)

        assert result["status"] == "mismatch"
        assert result["issue"] == "DATA_MISMATCH"
        assert "cohorts mismatch" in result["details"]
        assert "diffs" in result
        cohorts_diff = [d for d in result["diffs"] if d.get("type") == "COHORTS_MISMATCH"]
        assert len(cohorts_diff) == 1

    def test_verify_returns_mismatch_when_group_type_mapping_changed(self):
        GroupTypeMapping.objects.create(
            team=self.team,
            project_id=self.team.project_id,
            group_type="company",
            group_type_index=0,
        )

        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={
                "aggregation_group_type_index": 0,
                "groups": [{"properties": [], "rollout_percentage": 100}],
            },
        )

        update_flag_definitions_cache(self.team)

        mapping = GroupTypeMapping.objects.get(team=self.team, group_type_index=0)
        mapping.group_type = "organization"
        mapping.save()

        result = verify_team_flag_definitions(self.team, include_cohorts=True, verbose=True)

        assert result["status"] == "mismatch"
        assert result["issue"] == "DATA_MISMATCH"
        assert "group_type_mapping mismatch" in result["details"]
        assert "diffs" in result
        mapping_diff = [d for d in result["diffs"] if d.get("type") == "GROUP_TYPE_MAPPING_MISMATCH"]
        assert len(mapping_diff) == 1


@override_settings(FLAGS_REDIS_URL=None)
class TestFlagDefinitionsCacheWithoutRedis(BaseTest):
    def test_update_flag_definitions_cache_returns_true_without_redis(self):
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        result = update_flag_definitions_cache(self.team)
        assert result is True
