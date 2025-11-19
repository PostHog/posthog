from datetime import UTC, datetime, timedelta
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from ee.hogai.graph.usage.queries import (
    DEFAULT_FREE_TIER_CREDITS,
    GA_LAUNCH_DATE,
    format_usage_message,
    get_ai_free_tier_credits,
    get_conversation_start_time,
    get_past_month_start,
)
from ee.models.assistant import Conversation


class TestUsage(BaseTest):
    def test_get_ai_free_tier_credits_default(self):
        """Test that teams without custom limits get the default free tier."""
        credits = get_ai_free_tier_credits(team_id=999)
        self.assertEqual(credits, DEFAULT_FREE_TIER_CREDITS)

    @patch("ee.hogai.graph.usage.queries.get_instance_region")
    def test_get_ai_free_tier_credits_custom_eu(self, mock_region):
        """Test that EU internal team gets custom free tier limit."""
        mock_region.return_value = "EU"
        credits = get_ai_free_tier_credits(team_id=1)
        self.assertEqual(credits, 9999999)

    @patch("ee.hogai.graph.usage.queries.get_instance_region")
    def test_get_ai_free_tier_credits_custom_us(self, mock_region):
        """Test that US internal team gets custom free tier limit."""
        mock_region.return_value = "US"
        credits = get_ai_free_tier_credits(team_id=2)
        self.assertEqual(credits, 9999999)

    @patch("ee.hogai.graph.usage.queries.get_instance_region")
    def test_get_ai_free_tier_credits_fallback_when_region_unknown(self, mock_region):
        """Test that unknown regions fall back to default."""
        mock_region.return_value = None
        credits = get_ai_free_tier_credits(team_id=1)
        self.assertEqual(credits, DEFAULT_FREE_TIER_CREDITS)

    def test_get_conversation_start_time_exists(self):
        """Test retrieving conversation start time for existing conversation."""
        conversation = Conversation.objects.create(
            team=self.team,
            user=self.user,
        )
        start_time = get_conversation_start_time(conversation.id)
        self.assertIsNotNone(start_time)
        assert start_time is not None  # type narrowing for mypy
        self.assertEqual(start_time.replace(microsecond=0), conversation.created_at.replace(microsecond=0))

    def test_get_conversation_start_time_not_exists(self):
        """Test that non-existent conversation returns None."""
        start_time = get_conversation_start_time(uuid4())
        self.assertIsNone(start_time)

    def test_get_past_month_start_normal(self):
        """Test past month start when 30 days ago is after GA launch."""
        now = datetime(2025, 12, 20, tzinfo=UTC)
        with patch("ee.hogai.graph.usage.queries.datetime") as mock_datetime:
            mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)
            mock_datetime.now.return_value = now
            past_month_start = get_past_month_start()
            expected = datetime(2025, 11, 20, tzinfo=UTC)
            self.assertEqual(past_month_start, expected)

    def test_get_past_month_start_capped_at_ga_launch(self):
        """Test that past month start is capped at GA launch date."""
        # Set current time to shortly after GA launch
        now = GA_LAUNCH_DATE + timedelta(days=10)
        with patch("ee.hogai.graph.usage.queries.datetime") as mock_datetime:
            mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)
            mock_datetime.now.return_value = now
            past_month_start = get_past_month_start()
            # Should return GA_LAUNCH_DATE since 30 days ago is before GA launch
            self.assertEqual(past_month_start, GA_LAUNCH_DATE)

    def test_format_usage_message_no_usage(self):
        """Test formatting when no credits have been used."""
        message = format_usage_message(
            conversation_credits=0,
            past_month_credits=0,
            free_tier_credits=2000,
        )
        self.assertIn("**Current conversation**: 0 credits", message)
        self.assertIn("**Past 30 days**: 0 credits", message)
        self.assertIn("**Free tier limit**: 2,000 credits", message)
        self.assertIn("**Remaining**: 2,000 credits", message)
        self.assertIn("0% of free tier", message)

    def test_format_usage_message_partial_usage(self):
        """Test formatting with partial usage."""
        message = format_usage_message(
            conversation_credits=50,
            past_month_credits=500,
            free_tier_credits=2000,
        )
        self.assertIn("**Current conversation**: 50 credits", message)
        self.assertIn("**Past 30 days**: 500 credits", message)
        self.assertIn("**Remaining**: 1,500 credits", message)
        self.assertIn("25% of free tier", message)

    def test_format_usage_message_over_limit(self):
        """Test formatting when over the free tier limit."""
        message = format_usage_message(
            conversation_credits=100,
            past_month_credits=2500,
            free_tier_credits=2000,
        )
        self.assertIn("**Overage**: 500 credits over limit", message)
        self.assertIn("125% of free tier", message)

    def test_format_usage_message_with_ga_cap(self):
        """Test formatting when GA cap is active."""
        message = format_usage_message(
            conversation_credits=10,
            past_month_credits=100,
            free_tier_credits=2000,
            past_month_start=GA_LAUNCH_DATE,
        )
        self.assertIn(f"since {GA_LAUNCH_DATE.strftime('%Y-%m-%d')}", message)
        self.assertIn(f"from PostHog AI general availability date ({GA_LAUNCH_DATE.strftime('%b %d, %Y')})", message)

    def test_format_usage_message_with_conversation_start(self):
        """Test formatting with conversation start time."""
        conv_start = datetime(2025, 11, 18, 10, 30, tzinfo=UTC)
        message = format_usage_message(
            conversation_credits=25,
            past_month_credits=200,
            free_tier_credits=2000,
            conversation_start=conv_start,
        )
        self.assertIn("_Conversation since_: 2025-11-18 10:30 UTC", message)

    def test_format_usage_message_progress_bar(self):
        """Test that progress bar is rendered correctly."""
        # 50% usage
        message = format_usage_message(
            conversation_credits=0,
            past_month_credits=1000,
            free_tier_credits=2000,
        )
        # Should have exactly 10 filled blocks out of 20
        self.assertIn("█" * 10, message)
        self.assertIn("░" * 10, message)

    def test_format_usage_message_full_progress_bar(self):
        """Test progress bar when at 100% usage."""
        message = format_usage_message(
            conversation_credits=0,
            past_month_credits=2000,
            free_tier_credits=2000,
        )
        # Should have all 20 blocks filled
        self.assertIn("█" * 20, message)
        self.assertNotIn("░", message)
