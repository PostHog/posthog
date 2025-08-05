from unittest.mock import patch

from posthog.test.base import APIBaseTest
from posthog.hogql_queries.legacy_compatibility.feature_flag import query_cache_use_s3


class TestQueryCacheFeatureFlag(APIBaseTest):
    """Test query cache feature flag functionality."""

    @patch("posthoganalytics.feature_enabled")
    def test_query_cache_use_s3_without_user(self, mock_feature_enabled):
        """Test feature flag evaluation without user."""
        mock_feature_enabled.return_value = True

        result = query_cache_use_s3(self.team)

        self.assertTrue(result)
        mock_feature_enabled.assert_called_once_with(
            "query-cache-use-s3",
            str(self.team.uuid),  # Uses team UUID as distinct_id
            groups={
                "organization": str(self.team.organization_id),
                "project": str(self.team.id),
            },
            group_properties={
                "organization": {"id": str(self.team.organization_id)},
                "project": {"id": str(self.team.id)},
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )

    @patch("posthoganalytics.feature_enabled")
    def test_query_cache_use_s3_with_user(self, mock_feature_enabled):
        """Test feature flag evaluation with user."""
        mock_feature_enabled.return_value = False

        result = query_cache_use_s3(self.team, user=self.user)

        self.assertFalse(result)
        mock_feature_enabled.assert_called_once_with(
            "query-cache-use-s3",
            str(self.user.distinct_id),  # Uses user distinct_id
            groups={
                "organization": str(self.team.organization_id),
                "project": str(self.team.id),
            },
            group_properties={
                "organization": {"id": str(self.team.organization_id)},
                "project": {"id": str(self.team.id)},
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )

    @patch("posthoganalytics.feature_enabled")
    def test_query_cache_use_s3_with_none_user(self, mock_feature_enabled):
        """Test feature flag evaluation with None user."""
        mock_feature_enabled.return_value = True

        result = query_cache_use_s3(self.team, user=None)

        self.assertTrue(result)
        mock_feature_enabled.assert_called_once_with(
            "query-cache-use-s3",
            str(self.team.uuid),  # Falls back to team UUID
            groups={
                "organization": str(self.team.organization_id),
                "project": str(self.team.id),
            },
            group_properties={
                "organization": {"id": str(self.team.organization_id)},
                "project": {"id": str(self.team.id)},
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
