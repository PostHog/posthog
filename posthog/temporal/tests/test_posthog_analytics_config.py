"""
Tests for Temporal-specific posthoganalytics configuration.

These tests verify that the safety configuration for posthoganalytics is applied
correctly in Temporal workers to avoid thread-safety issues.
"""

import sys

import pytest
from unittest import mock


@pytest.fixture
def mock_posthoganalytics():
    """Mock posthoganalytics module for testing."""
    # Create a mock module
    mock_module = mock.MagicMock()
    mock_module.personal_api_key = "test_key"
    mock_module.sync_mode = False
    mock_module.disable_connection_reuse = mock.MagicMock()

    # Inject into sys.modules so the import inside the function finds it
    with mock.patch.dict(sys.modules, {"posthoganalytics": mock_module}):
        yield mock_module


class TestPostHogAnalyticsConfig:
    def test_configure_disables_connection_reuse(self, mock_posthoganalytics):
        """Test that connection pooling is disabled."""
        from posthog.temporal.common.posthog_analytics_config import configure_posthog_analytics_for_temporal

        configure_posthog_analytics_for_temporal()

        mock_posthoganalytics.disable_connection_reuse.assert_called_once()

    def test_configure_disables_local_evaluation(self, mock_posthoganalytics):
        """Test that local evaluation (Poller thread) is disabled."""
        from posthog.temporal.common.posthog_analytics_config import configure_posthog_analytics_for_temporal

        configure_posthog_analytics_for_temporal()

        assert mock_posthoganalytics.personal_api_key is None

    def test_configure_enables_sync_mode(self, mock_posthoganalytics):
        """Test that sync mode (no Consumer threads) is enabled."""
        from posthog.temporal.common.posthog_analytics_config import configure_posthog_analytics_for_temporal

        configure_posthog_analytics_for_temporal()

        assert mock_posthoganalytics.sync_mode is True

    def test_configure_handles_missing_disable_connection_reuse(self, mock_posthoganalytics):
        """Test graceful handling when disable_connection_reuse doesn't exist (older SDK versions)."""
        from posthog.temporal.common.posthog_analytics_config import configure_posthog_analytics_for_temporal

        # Simulate older SDK version without this method
        delattr(mock_posthoganalytics, "disable_connection_reuse")

        # Should not raise an exception
        configure_posthog_analytics_for_temporal()

        # Other configs should still be applied
        assert mock_posthoganalytics.personal_api_key is None
        assert mock_posthoganalytics.sync_mode is True
