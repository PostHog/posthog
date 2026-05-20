from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from ee.hogai.chat_agent.slash_commands.commands.usage.queries import (
    CLOUD_REGION_TO_TEAM_ID,
    CLOUD_REGION_TO_URL,
    DEFAULT_FREE_TIER_CREDITS,
    DEFAULT_GA_LAUNCH_DATE,
    format_usage_message,
    get_ai_credits,
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

    @parameterized.expand(
        [
            ("eu_cloud", "EU", CLOUD_REGION_TO_TEAM_ID["EU"], CLOUD_REGION_TO_URL["EU"], 2),
            ("us_cloud", "US", CLOUD_REGION_TO_TEAM_ID["US"], CLOUD_REGION_TO_URL["US"], 1),
            ("local_dev", None, CLOUD_REGION_TO_TEAM_ID["EU"], None, None),
        ]
    )
    def test_get_ai_credits_scopes_ai_events_query(
        self,
        _name,
        region,
        expected_team_to_query,
        expected_region_url,
        instance_group_index,
    ):
        begin = datetime(2026, 5, 1, tzinfo=UTC)
        end = datetime(2026, 5, 2, tzinfo=UTC)
        conversation_id = uuid4()

        group_mappings = (
            [
                {"group_type": "organization", "group_type_index": 0},
                {"group_type": "instance", "group_type_index": instance_group_index},
            ]
            if instance_group_index is not None
            else []
        )

        with (
            patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.get_instance_region") as mock_region,
            patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.sync_execute") as mock_sync_execute,
            patch(
                "ee.hogai.chat_agent.slash_commands.commands.usage.queries.get_group_types_for_team"
            ) as mock_group_types,
        ):
            mock_region.return_value = region
            mock_sync_execute.return_value = [(42,)]
            mock_group_types.return_value = group_mappings

            credits = get_ai_credits(team_id=133393, begin=begin, end=end, conversation_id=conversation_id)

            self.assertEqual(credits, 42)
            query, params = mock_sync_execute.call_args[0][:2]
            self.assertEqual(params["team_to_query"], expected_team_to_query)
            self.assertEqual(params["session_id"], str(conversation_id))
            if expected_region_url is None:
                self.assertNotIn("region_url", params)
                self.assertNotIn("%(region_url)s", query)
                mock_group_types.assert_not_called()
            else:
                self.assertEqual(params["region_url"], expected_region_url)
                mock_group_types.assert_called_once_with(expected_team_to_query)
                self.assertIn(
                    f"AND JSONExtractString(properties, '$group_{instance_group_index}') = %(region_url)s",
                    query,
                )

    def test_get_ai_credits_skips_region_filter_when_instance_group_missing(self):
        """If the destination team has no `instance` group registered, skip the region filter rather than match nothing."""
        begin = datetime(2026, 5, 1, tzinfo=UTC)
        end = datetime(2026, 5, 2, tzinfo=UTC)
        conversation_id = uuid4()

        with (
            patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.get_instance_region") as mock_region,
            patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.sync_execute") as mock_sync_execute,
            patch(
                "ee.hogai.chat_agent.slash_commands.commands.usage.queries.get_group_types_for_team",
                return_value=[{"group_type": "organization", "group_type_index": 0}],
            ),
        ):
            mock_region.return_value = "EU"
            mock_sync_execute.return_value = [(0,)]

            get_ai_credits(team_id=133393, begin=begin, end=end, conversation_id=conversation_id)

            query, params = mock_sync_execute.call_args[0][:2]
            self.assertNotIn("region_url", params)
            self.assertNotIn("%(region_url)s", query)

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
