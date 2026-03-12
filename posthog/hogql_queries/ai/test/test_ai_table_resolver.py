from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import Mock, patch

from posthog.hogql_queries.ai.ai_table_resolver import (
    AI_EVENTS_TTL_DAYS,
    is_ai_events_enabled,
    is_within_ai_events_ttl,
    validate_ai_event_names,
)


class TestIsWithinAiEventsTtl:
    def test_within_ttl(self):
        now = datetime(2026, 3, 12, 12, 0, 0)
        date_from = now - timedelta(days=20)
        assert is_within_ai_events_ttl(date_from, now) is True

    def test_at_ttl_boundary_with_buffer(self):
        now = datetime(2026, 3, 12, 12, 0, 0)
        # Exactly 30 days ago — within the 1-day buffer
        date_from = now - timedelta(days=AI_EVENTS_TTL_DAYS)
        assert is_within_ai_events_ttl(date_from, now) is True

    def test_at_buffer_boundary(self):
        now = datetime(2026, 3, 12, 12, 0, 0)
        # Exactly 31 days ago — cutoff is TTL + 1 day, so exactly at cutoff
        date_from = now - timedelta(days=AI_EVENTS_TTL_DAYS + 1)
        assert is_within_ai_events_ttl(date_from, now) is True

    def test_beyond_buffer(self):
        now = datetime(2026, 3, 12, 12, 0, 0)
        date_from = now - timedelta(days=AI_EVENTS_TTL_DAYS + 2)
        assert is_within_ai_events_ttl(date_from, now) is False

    def test_aware_datetimes(self):
        now = datetime(2026, 3, 12, 12, 0, 0, tzinfo=UTC)
        date_from = now - timedelta(days=20)
        assert is_within_ai_events_ttl(date_from, now) is True

    def test_mixed_naive_aware(self):
        now = datetime(2026, 3, 12, 12, 0, 0, tzinfo=UTC)
        date_from = datetime(2026, 2, 20, 12, 0, 0)  # naive
        assert is_within_ai_events_ttl(date_from, now) is True


class TestIsAiEventsEnabled:
    @patch("posthog.hogql_queries.ai.ai_table_resolver.posthoganalytics.feature_enabled", return_value=True)
    def test_returns_true_when_flag_enabled(self, mock_flag):
        team = Mock(id=123, organization_id="org_abc")
        assert is_ai_events_enabled(team) is True
        mock_flag.assert_called_once_with(
            "ai-events-table-rollout",
            "123",
            groups={"organization": "org_abc"},
            group_properties={"organization": {"id": "org_abc"}},
            send_feature_flag_events=False,
        )

    @patch("posthog.hogql_queries.ai.ai_table_resolver.posthoganalytics.feature_enabled", return_value=False)
    def test_returns_false_when_flag_disabled(self, mock_flag):
        team = Mock(id=456, organization_id="org_xyz")
        assert is_ai_events_enabled(team) is False
        mock_flag.assert_called_once_with(
            "ai-events-table-rollout",
            "456",
            groups={"organization": "org_xyz"},
            group_properties={"organization": {"id": "org_xyz"}},
            send_feature_flag_events=False,
        )


class TestValidateAiEventNames:
    def test_valid_ai_events(self):
        validate_ai_event_names(["$ai_generation", "$ai_span", "$ai_trace"])

    def test_single_valid_event(self):
        validate_ai_event_names(["$ai_generation"])

    def test_empty_list(self):
        validate_ai_event_names([])

    def test_invalid_event_raises(self):
        with pytest.raises(ValueError, match="only supports AI events"):
            validate_ai_event_names(["$pageview"])

    def test_mixed_valid_invalid_raises(self):
        with pytest.raises(ValueError, match="only supports AI events"):
            validate_ai_event_names(["$ai_generation", "$pageview"])
