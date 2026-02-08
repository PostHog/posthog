from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models import FeatureFlag, Tag
from posthog.models.feature_flag.feature_flag import FeatureFlagEvaluationTag


class TestFeatureFlagRequireEvaluationTags(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.feature_flag_url = "/api/projects/@current/feature_flags/"

        # Mock FLAG_EVALUATION_TAGS feature flag to be enabled by default
        self.feature_flag_patcher = patch("posthoganalytics.feature_enabled")
        self.mock_feature_enabled = self.feature_flag_patcher.start()
        # Enable the feature flag by default
        self.mock_feature_enabled.return_value = True

    def tearDown(self):
        self.feature_flag_patcher.stop()
        super().tearDown()

    def test_create_flag_without_tags_when_not_required(self):
        """Test creating a flag without evaluation tags when requirement is disabled"""
        self.team.require_evaluation_contexts = False
        self.team.save()

        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "test-flag",
                "name": "Test Flag",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="test-flag", team=self.team)
        self.assertEqual(flag.evaluation_tags.count(), 0)

    def test_create_flag_without_tags_when_required(self):
        """Test creating a flag without evaluation tags when requirement is enabled should fail"""
        self.team.require_evaluation_contexts = True
        self.team.save()

        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "test-flag-required",
                "name": "Test Flag Required",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("evaluation context tag", str(response.content))

    def test_create_flag_with_empty_tags_when_required(self):
        """Test creating a flag with empty evaluation tags when requirement is enabled should fail"""
        self.team.require_evaluation_contexts = True
        self.team.save()

        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "test-flag-empty",
                "name": "Test Flag Empty",
                "evaluation_tags": [],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("evaluation context tag", str(response.content))

    def test_create_flag_with_tags_when_required(self):
        """Test creating a flag with evaluation tags when requirement is enabled should succeed"""
        self.team.require_evaluation_contexts = True
        self.team.save()

        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "test-flag-with-tags",
                "name": "Test Flag With Tags",
                "tags": ["production"],
                "evaluation_tags": ["production"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="test-flag-with-tags", team=self.team)
        eval_tag_names = set(flag.evaluation_tags.values_list("tag__name", flat=True))
        self.assertEqual(eval_tag_names, {"production"})

    def test_update_flag_without_tags_when_required(self):
        """Test updating an existing flag without evaluation tags when requirement is enabled should succeed"""
        self.team.require_evaluation_contexts = True
        self.team.save()

        # Create a flag first without the requirement
        self.team.require_evaluation_contexts = False
        self.team.save()
        flag = FeatureFlag.objects.create(
            key="existing-flag",
            name="Existing Flag",
            team=self.team,
            created_by=self.user,
        )

        # Enable the requirement
        self.team.require_evaluation_contexts = True
        self.team.save()

        # Update the flag (should succeed)
        response = self.client.patch(
            f"/api/projects/@current/feature_flags/{flag.id}/",
            {
                "name": "Updated Name",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_flag_with_multiple_tags_when_required(self):
        """Test creating a flag with multiple evaluation tags when requirement is enabled"""
        self.team.require_evaluation_contexts = True
        self.team.save()

        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "test-flag-multiple",
                "name": "Test Flag Multiple",
                "tags": ["production", "staging"],
                "evaluation_tags": ["production", "staging"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="test-flag-multiple", team=self.team)
        eval_tag_names = set(flag.evaluation_tags.values_list("tag__name", flat=True))
        self.assertEqual(eval_tag_names, {"production", "staging"})

    def test_create_flag_without_feature_flag_enabled(self):
        """Test that requirement doesn't apply when FLAG_EVALUATION_TAGS feature is disabled"""
        self.team.require_evaluation_contexts = True
        self.team.save()

        # Disable the FLAG_EVALUATION_TAGS feature flag
        self.mock_feature_enabled.return_value = False

        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "test-flag-feature-disabled",
                "name": "Test Flag Feature Disabled",
            },
            format="json",
        )

        # Should succeed because the feature is disabled
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_update_flag_remove_all_evaluation_tags_when_required(self):
        """Test that removing all evaluation tags from a flag fails when requirement is enabled"""
        self.team.require_evaluation_contexts = True
        self.team.save()

        # Create a flag with evaluation tags
        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "test-flag-with-tags",
                "name": "Test Flag With Tags",
                "tags": ["production", "staging"],
                "evaluation_tags": ["production", "staging"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="test-flag-with-tags", team=self.team)

        # Try to remove all evaluation tags
        response = self.client.patch(
            f"/api/projects/@current/feature_flags/{flag.id}/",
            {
                "evaluation_tags": [],
            },
            format="json",
        )

        # Should fail because the flag has existing evaluation tags
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Cannot remove all evaluation context tags", str(response.content))

    def test_update_flag_keep_some_evaluation_tags_when_required(self):
        """Test that updating to keep at least one evaluation tag succeeds"""
        self.team.require_evaluation_contexts = True
        self.team.save()

        # Create a flag with multiple evaluation tags
        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "test-flag-multiple-tags",
                "name": "Test Flag Multiple Tags",
                "tags": ["production", "staging"],
                "evaluation_tags": ["production", "staging"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="test-flag-multiple-tags", team=self.team)

        # Remove one tag but keep one
        response = self.client.patch(
            f"/api/projects/@current/feature_flags/{flag.id}/",
            {
                "tags": ["production"],
                "evaluation_tags": ["production"],
            },
            format="json",
        )

        # Should succeed because at least one evaluation tag remains
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        flag.refresh_from_db()
        eval_tag_names = set(flag.evaluation_tags.values_list("tag__name", flat=True))
        self.assertEqual(eval_tag_names, {"production"})

    def test_update_flag_without_evaluation_tags_when_required(self):
        """Test that updating a flag without existing evaluation tags succeeds"""
        self.team.require_evaluation_contexts = True
        self.team.save()

        # Create a flag without evaluation tags (before requirement was enabled)
        self.team.require_evaluation_contexts = False
        self.team.save()
        flag = FeatureFlag.objects.create(
            key="flag-no-tags",
            name="Flag No Tags",
            team=self.team,
            created_by=self.user,
        )

        # Enable requirement
        self.team.require_evaluation_contexts = True
        self.team.save()

        # Update the flag name (not touching evaluation tags)
        response = self.client.patch(
            f"/api/projects/@current/feature_flags/{flag.id}/",
            {
                "name": "Updated Name",
            },
            format="json",
        )

        # Should succeed because the flag doesn't have existing evaluation tags
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_update_flag_without_sending_evaluation_tags_field(self):
        """Test that updating a flag without sending evaluation_tags field at all succeeds"""
        self.team.require_evaluation_contexts = True
        self.team.save()

        # Create a flag with evaluation tags
        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "test-flag-update",
                "name": "Test Flag Update",
                "tags": ["production"],
                "evaluation_tags": ["production"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="test-flag-update", team=self.team)

        # Update without sending evaluation_tags field (just update the name)
        response = self.client.patch(
            f"/api/projects/@current/feature_flags/{flag.id}/",
            {
                "name": "Updated Name",
            },
            format="json",
        )

        # Should succeed because we're not explicitly changing evaluation_tags
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        flag.refresh_from_db()
        # Evaluation tags should remain unchanged
        eval_tag_names = set(flag.evaluation_tags.values_list("tag__name", flat=True))
        self.assertEqual(eval_tag_names, {"production"})

    def test_create_survey_flag_without_tags_when_required(self):
        """Test that survey flags can be created without tags even when requirement is enabled"""
        self.team.require_evaluation_contexts = True
        self.team.save()

        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "survey-flag",
                "name": "Survey Flag",
                "creation_context": "surveys",
            },
            format="json",
        )

        # Should succeed because surveys are exempt from the requirement
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="survey-flag", team=self.team)
        self.assertEqual(flag.evaluation_tags.count(), 0)

    def test_create_experiment_flag_without_tags_when_required(self):
        """Test that experiment flags cannot be created without tags when requirement is enabled"""
        self.team.require_evaluation_contexts = True
        self.team.save()

        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "experiment-flag",
                "name": "Experiment Flag",
                "creation_context": "experiments",
            },
            format="json",
        )

        # Should fail because experiments are subject to the requirement
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("evaluation context tag", str(response.content))

    def test_create_experiment_flag_with_tags_when_required(self):
        """Test that experiment flags can be created with tags when requirement is enabled"""
        self.team.require_evaluation_contexts = True
        self.team.save()

        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "experiment-flag-with-tags",
                "name": "Experiment Flag With Tags",
                "tags": ["production"],
                "evaluation_tags": ["production"],
                "creation_context": "experiments",
            },
            format="json",
        )

        # Should succeed because experiment has evaluation tags
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="experiment-flag-with-tags", team=self.team)
        eval_tag_names = set(flag.evaluation_tags.values_list("tag__name", flat=True))
        self.assertEqual(eval_tag_names, {"production"})

    def test_filter_by_evaluation_tags(self):
        """Test filtering feature flags by evaluation tag presence"""
        # Create flag with evaluation tags
        flag_with_tags = FeatureFlag.objects.create(
            key="flag-with-tags",
            name="Flag With Tags",
            team=self.team,
            created_by=self.user,
        )
        tag = Tag.objects.create(name="production", team_id=self.team.id)
        FeatureFlagEvaluationTag.objects.create(feature_flag=flag_with_tags, tag=tag)

        # Create flag without evaluation tags
        FeatureFlag.objects.create(
            key="flag-without-tags",
            name="Flag Without Tags",
            team=self.team,
            created_by=self.user,
        )

        # Test filtering for flags WITH evaluation tags
        response = self.client.get(f"{self.feature_flag_url}?has_evaluation_tags=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["key"], "flag-with-tags")

        # Test filtering for flags WITHOUT evaluation tags
        response = self.client.get(f"{self.feature_flag_url}?has_evaluation_tags=false")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["key"], "flag-without-tags")

        # Test no filter returns both
        response = self.client.get(self.feature_flag_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 2)
