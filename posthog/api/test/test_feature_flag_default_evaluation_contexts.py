from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models import FeatureFlag
from posthog.models.evaluation_context import EvaluationContext, TeamDefaultEvaluationContext


class TestFeatureFlagDefaultEnvironments(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.feature_flag_url = "/api/projects/@current/feature_flags/"

        self.feature_flag_patcher = patch("posthoganalytics.feature_enabled")
        self.mock_feature_enabled = self.feature_flag_patcher.start()
        self.mock_feature_enabled.return_value = True

    def tearDown(self):
        self.feature_flag_patcher.stop()
        super().tearDown()

    def _create_default_context(self, name: str) -> TeamDefaultEvaluationContext:
        ctx, _ = EvaluationContext.objects.get_or_create(name=name, team=self.team)
        default, _ = TeamDefaultEvaluationContext.objects.get_or_create(team=self.team, evaluation_context=ctx)
        return default

    def test_create_flag_without_default_contexts(self):
        self.team.default_evaluation_contexts_enabled = False
        self.team.save()

        self._create_default_context("production")

        response = self.client.post(
            self.feature_flag_url,
            {"key": "test-flag", "name": "Test Flag"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="test-flag", team=self.team)
        self.assertEqual(flag.tagged_items.count(), 0)
        self.assertEqual(flag.flag_evaluation_contexts.count(), 0)

    def test_create_flag_with_default_contexts_enabled(self):
        self.team.default_evaluation_contexts_enabled = True
        self.team.save()

        self._create_default_context("production")
        self._create_default_context("staging")

        response = self.client.post(
            self.feature_flag_url,
            {"key": "test-flag-with-defaults", "name": "Test Flag with Defaults"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="test-flag-with-defaults", team=self.team)
        self.assertEqual(flag.tagged_items.count(), 0)
        self.assertEqual(flag.flag_evaluation_contexts.count(), 0)

    def test_create_flag_with_explicit_tags_overrides(self):
        self.team.default_evaluation_contexts_enabled = True
        self.team.save()

        self._create_default_context("production")

        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "test-flag-explicit",
                "name": "Test Flag with Explicit Tags",
                "tags": ["custom-tag"],
                "evaluation_contexts": ["custom-tag"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="test-flag-explicit", team=self.team)
        eval_context_names = set(flag.flag_evaluation_contexts.values_list("evaluation_context__name", flat=True))
        self.assertEqual(eval_context_names, {"custom-tag"})

    def test_create_flag_with_explicit_tags_only(self):
        self.team.default_evaluation_contexts_enabled = True
        self.team.save()

        self._create_default_context("production")
        self._create_default_context("staging")

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
        tag_names = set(flag.tagged_items.values_list("tag__name", flat=True))
        self.assertEqual(tag_names, {"custom-tag"})
        self.assertEqual(flag.flag_evaluation_contexts.count(), 0)

    def test_create_flag_with_empty_evaluation_contexts(self):
        self.team.default_evaluation_contexts_enabled = True
        self.team.save()

        self._create_default_context("production")

        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "test-flag-empty",
                "name": "Test Flag with Empty Eval Contexts",
                "evaluation_contexts": [],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="test-flag-empty", team=self.team)
        self.assertEqual(flag.flag_evaluation_contexts.count(), 0)

    def test_update_flag_doesnt_apply_defaults(self):
        self.team.default_evaluation_contexts_enabled = True
        self.team.save()

        flag = FeatureFlag.objects.create(
            key="existing-flag",
            name="Existing Flag",
            team=self.team,
            created_by=self.user,
        )

        self._create_default_context("production")

        response = self.client.patch(
            f"/api/projects/@current/feature_flags/{flag.id}/",
            {"name": "Updated Name"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        flag.refresh_from_db()
        self.assertEqual(flag.tagged_items.count(), 0)
        self.assertEqual(flag.flag_evaluation_contexts.count(), 0)

    def test_create_flag_with_none_evaluation_contexts(self):
        self.team.default_evaluation_contexts_enabled = True
        self.team.save()

        self._create_default_context("production")
        self._create_default_context("staging")

        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "test-flag-none-eval",
                "name": "Test Flag with None Eval Contexts",
                "evaluation_contexts": None,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_flag_with_explicit_evaluation_contexts(self):
        self.team.default_evaluation_contexts_enabled = True
        self.team.save()

        self._create_default_context("production")
        self._create_default_context("staging")

        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "test-flag-explicit-eval",
                "name": "Test Flag with Explicit Eval Contexts",
                "tags": ["custom-tag", "production"],
                "evaluation_contexts": ["custom-tag"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="test-flag-explicit-eval", team=self.team)
        eval_context_names = set(flag.flag_evaluation_contexts.values_list("evaluation_context__name", flat=True))
        self.assertEqual(eval_context_names, {"custom-tag"})

    def test_no_default_contexts_configured(self):
        self.team.default_evaluation_contexts_enabled = True
        self.team.save()

        response = self.client.post(
            self.feature_flag_url,
            {"key": "test-flag-no-defaults", "name": "Test Flag No Defaults"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="test-flag-no-defaults", team=self.team)
        self.assertEqual(flag.tagged_items.count(), 0)
        self.assertEqual(flag.flag_evaluation_contexts.count(), 0)
