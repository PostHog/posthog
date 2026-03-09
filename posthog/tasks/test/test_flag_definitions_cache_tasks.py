from unittest.mock import MagicMock, patch

from django.test import TestCase

from posthog.tasks.feature_flags import (
    cleanup_stale_flag_definitions_expiry_tracking_task,
    refresh_expiring_flag_definitions_cache_entries,
)
from posthog.tasks.test.utils import PushGatewayTaskTestMixin


class TestRefreshExpiringFlagDefinitionsCacheEntries(PushGatewayTaskTestMixin, TestCase):
    @patch("posthog.storage.cache_expiry_manager.refresh_expiring_caches")
    def test_refreshes_both_cache_variants(self, mock_refresh: MagicMock) -> None:
        mock_refresh.return_value = (5, 0)

        refresh_expiring_flag_definitions_cache_entries()

        assert mock_refresh.call_count == 2

    @patch("posthog.storage.cache_expiry_manager.refresh_expiring_caches")
    def test_continues_to_next_variant_on_error(self, mock_refresh: MagicMock) -> None:
        mock_refresh.side_effect = [Exception("variant 1 failed"), (3, 0)]

        refresh_expiring_flag_definitions_cache_entries()

        assert mock_refresh.call_count == 2


class TestCleanupStaleFlagDefinitionsExpiryTrackingTask(PushGatewayTaskTestMixin, TestCase):
    @patch("posthog.storage.cache_expiry_manager.cleanup_stale_expiry_tracking")
    def test_cleans_up_both_cache_variants(self, mock_cleanup: MagicMock) -> None:
        mock_cleanup.return_value = 3

        cleanup_stale_flag_definitions_expiry_tracking_task()

        assert mock_cleanup.call_count == 2

    @patch("posthog.storage.cache_expiry_manager.cleanup_stale_expiry_tracking")
    def test_continues_to_next_variant_on_error(self, mock_cleanup: MagicMock) -> None:
        mock_cleanup.side_effect = [Exception("variant 1 failed"), 2]

        cleanup_stale_flag_definitions_expiry_tracking_task()

        assert mock_cleanup.call_count == 2
