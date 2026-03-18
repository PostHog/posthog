from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from ee.hogai.chat_agent.slash_commands.commands.usage.queries import (
    DEFAULT_FREE_TIER_CREDITS,
    DEFAULT_GA_LAUNCH_DATE,
    format_usage_message,
    get_ai_free_tier_credits,
    get_conversation_start_time,
    get_ga_launch_date,
    get_past_month_start,
)
from ee.models.assistant import Conversation


class TestUsage(BaseTest):
    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.posthoganalytics.get_feature_flag_payload")
    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.get_instance_region")
    def test_get_ai_free_tier_credits_default(self, mock_region, mock_payload):
        """Test that teams without custom limits get the default free tier."""
        mock_region.return_value = "EU"
        mock_payload.return_value = None
        credits = get_ai_free_tier_credits(team_id=999)
        self.assertEqual(credits, DEFAULT_FREE_TIER_CREDITS)

    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.posthoganalytics.get_feature_flag_payload")
    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.get_instance_region")
    def test_get_ai_free_tier_credits_custom_eu(self, mock_region, mock_payload):
        """Test that EU internal team gets custom free tier limit from feature flag."""
        mock_region.return_value = "EU"
        mock_payload.return_value = {"EU": {"1": 9999999}, "US": {"2": 9999999}}
        credits = get_ai_free_tier_credits(team_id=1)
        self.assertEqual(credits, 9999999)

    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.posthoganalytics.get_feature_flag_payload")
    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.get_instance_region")
    def test_get_ai_free_tier_credits_custom_us(self, mock_region, mock_payload):
        """Test that US internal team gets custom free tier limit from feature flag."""
        mock_region.return_value = "US"
        mock_payload.return_value = {"EU": {"1": 9999999}, "US": {"2": 9999999}}
        credits = get_ai_free_tier_credits(team_id=2)
        self.assertEqual(credits, 9999999)

    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.posthoganalytics.get_feature_flag_payload")
    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.get_instance_region")
    def test_get_ai_free_tier_credits_fallback_when_region_unknown(self, mock_region, mock_payload):
        """Test that unknown regions fall back to default."""
        mock_region.return_value = None
        mock_payload.return_value = {"EU": {"1": 9999999}}
        credits = get_ai_free_tier_credits(team_id=1)
        self.assertEqual(credits, DEFAULT_FREE_TIER_CREDITS)

    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.posthoganalytics.get_feature_flag_payload")
    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.get_instance_region")
    def test_get_ai_free_tier_credits_team_not_in_payload(self, mock_region, mock_payload):
        """Test that teams not in the payload get default credits."""
        mock_region.return_value = "EU"
        mock_payload.return_value = {"EU": {"1": 9999999}}
        credits = get_ai_free_tier_credits(team_id=999)
        self.assertEqual(credits, DEFAULT_FREE_TIER_CREDITS)

    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.posthoganalytics.get_feature_flag_payload")
    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.get_instance_region")
    def test_get_ai_free_tier_credits_invalid_payload(self, mock_region, mock_payload):
        """Test that invalid payloads fall back to default."""
        mock_region.return_value = "EU"
        mock_payload.return_value = "invalid"
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
        self.assertEqual(
            cast(datetime, start_time).replace(microsecond=0),
            cast(datetime, conversation.created_at).replace(microsecond=0),
        )

    def test_get_conversation_start_time_not_exists(self):
        """Test that non-existent conversation returns None."""
        start_time = get_conversation_start_time(uuid4())
        self.assertIsNone(start_time)

    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.posthoganalytics.get_feature_flag_payload")
    def test_get_ga_launch_date_from_payload(self, mock_payload):
        """Test that GA launch date is fetched from feature flag payload."""
        mock_payload.return_value = {"ga_launch_date": "2025-12-01", "EU": {"1": 10000}}
        ga_date = get_ga_launch_date()
        self.assertEqual(ga_date, datetime(2025, 12, 1, tzinfo=UTC))

    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.posthoganalytics.get_feature_flag_payload")
    def test_get_ga_launch_date_fallback(self, mock_payload):
        """Test that GA launch date falls back to default when not in payload."""
        mock_payload.return_value = None
        ga_date = get_ga_launch_date()
        self.assertEqual(ga_date, DEFAULT_GA_LAUNCH_DATE)

    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.posthoganalytics.get_feature_flag_payload")
    def test_get_ga_launch_date_invalid_format(self, mock_payload):
        """Test that invalid date format falls back to default."""
        mock_payload.return_value = {"ga_launch_date": "invalid-date"}
        ga_date = get_ga_launch_date()
        self.assertEqual(ga_date, DEFAULT_GA_LAUNCH_DATE)

    def test_get_past_month_start_normal(self):
        """Test past month start when 30 days ago is after GA launch."""
        now = datetime(2025, 12, 20, tzinfo=UTC)
        with patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.datetime") as mock_datetime:
            mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)
            mock_datetime.now.return_value = now
            past_month_start = get_past_month_start()
            expected = datetime(2025, 11, 20, tzinfo=UTC)
            self.assertEqual(past_month_start, expected)

    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.posthoganalytics.get_feature_flag_payload")
    def test_get_past_month_start_capped_at_ga_launch(self, mock_payload):
        """Test that past month start is capped at GA launch date."""
        mock_payload.return_value = None
        now = DEFAULT_GA_LAUNCH_DATE + timedelta(days=10)
        with patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.datetime") as mock_datetime:
            mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)
            mock_datetime.now.return_value = now
            past_month_start = get_past_month_start()
            self.assertEqual(past_month_start, DEFAULT_GA_LAUNCH_DATE)

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

    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.posthoganalytics.get_feature_flag_payload")
    def test_format_usage_message_with_ga_cap(self, mock_payload):
        """Test formatting when GA cap is active."""
        mock_payload.return_value = None
        message = format_usage_message(
            conversation_credits=10,
            past_month_credits=100,
            free_tier_credits=2000,
            past_month_start=DEFAULT_GA_LAUNCH_DATE,
        )
        self.assertIn(f"since {DEFAULT_GA_LAUNCH_DATE.strftime('%Y-%m-%d')}", message)
        self.assertIn(
            f"from PostHog AI general availability date ({DEFAULT_GA_LAUNCH_DATE.strftime('%b %d, %Y')})", message
        )

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
        message = format_usage_message(
            conversation_credits=0,
            past_month_credits=1000,
            free_tier_credits=2000,
        )
        self.assertIn("█" * 10, message)
        self.assertIn("░" * 10, message)

    def test_format_usage_message_full_progress_bar(self):
        """Test progress bar when at 100% usage."""
        message = format_usage_message(
            conversation_credits=0,
            past_month_credits=2000,
            free_tier_credits=2000,
        )
        self.assertIn("█" * 20, message)
        self.assertNotIn("░", message)
