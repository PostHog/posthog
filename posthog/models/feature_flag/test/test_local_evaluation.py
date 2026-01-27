from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.cohort.cohort import Cohort
from posthog.models.feature_flag.feature_flag import FeatureFlag, FeatureFlagEvaluationTag
from posthog.models.feature_flag.local_evaluation import (
    _get_flags_for_local_evaluation,
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
