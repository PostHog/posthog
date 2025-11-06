from datetime import datetime as dt
from typing import cast

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models import FeatureFlag, Tag
from posthog.models.feature_flag import TeamDefaultEvaluationTag

from products.enterprise.backend.models.license import License, LicenseManager


class TestFeatureFlagDefaultEnvironments(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.feature_flag_url = "/api/projects/@current/feature_flags/"

        # Create a license to enable tagging feature
        future_year = dt.now().year + 50
        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="test_license_key",
            plan="enterprise",
            valid_until=dt(future_year, 1, 19, 3, 14, 7),
        )

        # Mock FLAG_EVALUATION_TAGS feature flag to be enabled by default
        self.feature_flag_patcher = patch("posthoganalytics.feature_enabled")
        self.mock_feature_enabled = self.feature_flag_patcher.start()
        # Enable the feature flag by default
        self.mock_feature_enabled.return_value = True

    def tearDown(self):
        self.feature_flag_patcher.stop()
        super().tearDown()

    def test_create_flag_without_default_environments(self):
        """Test creating a flag when default environments are disabled"""
        self.team.default_evaluation_environments_enabled = False
        self.team.save()

        # Add some default tags (but feature is disabled)
        tag = Tag.objects.create(name="production", team=self.team)
        TeamDefaultEvaluationTag.objects.create(team=self.team, tag=tag)

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

        # Verify no tags were applied
        self.assertEqual(flag.tagged_items.count(), 0)
        self.assertEqual(flag.evaluation_tags.count(), 0)

    def test_create_flag_with_default_environments_enabled(self):
        """Test creating a flag when default environments are enabled but not explicitly requested"""
        self.team.default_evaluation_environments_enabled = True
        self.team.save()

        # Create default evaluation tags
        tag1 = Tag.objects.create(name="production", team=self.team)
        tag2 = Tag.objects.create(name="staging", team=self.team)
        TeamDefaultEvaluationTag.objects.create(team=self.team, tag=tag1)
        TeamDefaultEvaluationTag.objects.create(team=self.team, tag=tag2)

        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "test-flag-with-defaults",
                "name": "Test Flag with Defaults",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="test-flag-with-defaults", team=self.team)

        # Verify no tags were applied (defaults not applied automatically)
        self.assertEqual(flag.tagged_items.count(), 0)
        self.assertEqual(flag.evaluation_tags.count(), 0)

    def test_create_flag_with_explicit_tags_overrides(self):
        """Test that explicitly provided tags are not overridden"""
        self.team.default_evaluation_environments_enabled = True
        self.team.save()

        # Create default evaluation tags
        tag1 = Tag.objects.create(name="production", team=self.team)
        TeamDefaultEvaluationTag.objects.create(team=self.team, tag=tag1)

        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "test-flag-explicit",
                "name": "Test Flag with Explicit Tags",
                "tags": ["custom-tag"],
                "evaluation_tags": ["custom-tag"],  # must be subset of tags
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="test-flag-explicit", team=self.team)

        # Verify only explicit tags were applied (defaults not added to evaluation tags)
        eval_tag_names = set(flag.evaluation_tags.values_list("tag__name", flat=True))
        self.assertEqual(eval_tag_names, {"custom-tag"})

    def test_create_flag_with_explicit_tags_only(self):
        """Test that only explicitly provided tags are applied"""
        self.team.default_evaluation_environments_enabled = True
        self.team.save()

        # Create default evaluation tags
        tag1 = Tag.objects.create(name="production", team=self.team)
        tag2 = Tag.objects.create(name="staging", team=self.team)
        TeamDefaultEvaluationTag.objects.create(team=self.team, tag=tag1)
        TeamDefaultEvaluationTag.objects.create(team=self.team, tag=tag2)

        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "test-flag-explicit-only",
                "name": "Test Flag with Explicit Tags Only",
                "tags": ["custom-tag"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="test-flag-explicit-only", team=self.team)

        # Verify only explicit tags were applied
        tag_names = set(flag.tagged_items.values_list("tag__name", flat=True))
        self.assertEqual(tag_names, {"custom-tag"})

        # Verify no evaluation tags (not explicitly provided)
        self.assertEqual(flag.evaluation_tags.count(), 0)

    def test_create_flag_with_empty_evaluation_tags(self):
        """Test that empty evaluation_tags array is respected"""
        self.team.default_evaluation_environments_enabled = True
        self.team.save()

        # Create default evaluation tags
        tag1 = Tag.objects.create(name="production", team=self.team)
        TeamDefaultEvaluationTag.objects.create(team=self.team, tag=tag1)

        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "test-flag-empty",
                "name": "Test Flag with Empty Eval Tags",
                "evaluation_tags": [],  # Explicitly empty
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="test-flag-empty", team=self.team)

        # Verify no evaluation tags (empty array means "clear all")
        self.assertEqual(flag.evaluation_tags.count(), 0)

    def test_update_flag_doesnt_apply_defaults(self):
        """Test that updating an existing flag doesn't apply defaults"""
        self.team.default_evaluation_environments_enabled = True
        self.team.save()

        # Create a flag first without defaults
        flag = FeatureFlag.objects.create(
            key="existing-flag", name="Existing Flag", team=self.team, created_by=self.user
        )

        # Now add default evaluation tags
        tag1 = Tag.objects.create(name="production", team=self.team)
        TeamDefaultEvaluationTag.objects.create(team=self.team, tag=tag1)

        # Update the flag
        response = self.client.patch(
            f"/api/projects/@current/feature_flags/{flag.id}/",
            {
                "name": "Updated Name",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        flag.refresh_from_db()

        # Verify no tags were added during update
        self.assertEqual(flag.tagged_items.count(), 0)
        self.assertEqual(flag.evaluation_tags.count(), 0)

    def test_create_flag_with_none_evaluation_tags_applies_defaults(self):
        """Test that explicitly setting evaluation_tags to None applies defaults"""
        self.team.default_evaluation_environments_enabled = True
        self.team.save()

        # Create default evaluation tags
        tag1 = Tag.objects.create(name="production", team=self.team)
        tag2 = Tag.objects.create(name="staging", team=self.team)
        TeamDefaultEvaluationTag.objects.create(team=self.team, tag=tag1)
        TeamDefaultEvaluationTag.objects.create(team=self.team, tag=tag2)

        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "test-flag-none-eval",
                "name": "Test Flag with None Eval Tags",
                "evaluation_tags": None,  # Explicitly None
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_flag_with_explicit_evaluation_tags(self):
        """Test that explicitly provided evaluation tags are used"""
        self.team.default_evaluation_environments_enabled = True
        self.team.save()

        # Create default evaluation tags
        tag1 = Tag.objects.create(name="production", team=self.team)
        tag2 = Tag.objects.create(name="staging", team=self.team)
        TeamDefaultEvaluationTag.objects.create(team=self.team, tag=tag1)
        TeamDefaultEvaluationTag.objects.create(team=self.team, tag=tag2)

        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "test-flag-explicit-eval",
                "name": "Test Flag with Explicit Eval Tags",
                "tags": ["custom-tag", "production"],
                "evaluation_tags": ["custom-tag"],  # Explicitly set
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="test-flag-explicit-eval", team=self.team)

        # Verify only explicit evaluation tags were applied
        eval_tag_names = set(flag.evaluation_tags.values_list("tag__name", flat=True))
        self.assertEqual(eval_tag_names, {"custom-tag"})

    def test_no_default_tags_configured(self):
        """Test creating a flag when feature is enabled but no default tags exist"""
        self.team.default_evaluation_environments_enabled = True
        self.team.save()

        # No default tags configured

        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "test-flag-no-defaults",
                "name": "Test Flag No Defaults",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="test-flag-no-defaults", team=self.team)

        # Verify no tags were applied
        self.assertEqual(flag.tagged_items.count(), 0)
        self.assertEqual(flag.evaluation_tags.count(), 0)
