from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.posthog_ai.backend.models.assistant import Conversation

from ee.hogai.chat_agent.slash_commands.commands.usage.queries import (
    CLOUD_REGION_TO_TEAM_ID,
    CLOUD_REGION_TO_URL,
    DEFAULT_FREE_TIER_CREDITS,
    DEFAULT_GA_LAUNCH_DATE,
    AiUsagePeriod,
    format_usage_message,
    get_ai_credits,
    get_ai_free_tier_credits,
    get_ai_usage_period,
    get_conversation_start_time,
    get_ga_launch_date,
    get_past_month_start,
)


class TestUsage(BaseTest):
    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.posthoganalytics.get_feature_flag_payload")
    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.get_instance_region")
    def test_get_ai_free_tier_credits_default(self, mock_region, mock_payload):
        """Test that teams without custom limits get the default free tier."""
        mock_region.return_value = "EU"
        mock_payload.return_value = None
        credits = get_ai_free_tier_credits(team_id=999)
        assert credits == DEFAULT_FREE_TIER_CREDITS

    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.posthoganalytics.get_feature_flag_payload")
    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.get_instance_region")
    def test_get_ai_free_tier_credits_custom_eu(self, mock_region, mock_payload):
        """Test that EU internal team gets custom free tier limit from feature flag."""
        mock_region.return_value = "EU"
        mock_payload.return_value = {"EU": {"1": 9999999}, "US": {"2": 9999999}}
        credits = get_ai_free_tier_credits(team_id=1)
        assert credits == 9999999

    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.posthoganalytics.get_feature_flag_payload")
    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.get_instance_region")
    def test_get_ai_free_tier_credits_custom_us(self, mock_region, mock_payload):
        """Test that US internal team gets custom free tier limit from feature flag."""
        mock_region.return_value = "US"
        mock_payload.return_value = {"EU": {"1": 9999999}, "US": {"2": 9999999}}
        credits = get_ai_free_tier_credits(team_id=2)
        assert credits == 9999999

    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.posthoganalytics.get_feature_flag_payload")
    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.get_instance_region")
    def test_get_ai_free_tier_credits_fallback_when_region_unknown(self, mock_region, mock_payload):
        """Test that unknown regions fall back to default."""
        mock_region.return_value = None
        mock_payload.return_value = {"EU": {"1": 9999999}}
        credits = get_ai_free_tier_credits(team_id=1)
        assert credits == DEFAULT_FREE_TIER_CREDITS

    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.posthoganalytics.get_feature_flag_payload")
    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.get_instance_region")
    def test_get_ai_free_tier_credits_team_not_in_payload(self, mock_region, mock_payload):
        """Test that teams not in the payload get default credits."""
        mock_region.return_value = "EU"
        mock_payload.return_value = {"EU": {"1": 9999999}}
        credits = get_ai_free_tier_credits(team_id=999)
        assert credits == DEFAULT_FREE_TIER_CREDITS

    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.posthoganalytics.get_feature_flag_payload")
    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.get_instance_region")
    def test_get_ai_free_tier_credits_invalid_payload(self, mock_region, mock_payload):
        """Test that invalid payloads fall back to default."""
        mock_region.return_value = "EU"
        mock_payload.return_value = "invalid"
        credits = get_ai_free_tier_credits(team_id=1)
        assert credits == DEFAULT_FREE_TIER_CREDITS

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

        with (
            patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.get_instance_region") as mock_region,
            patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.sync_execute") as mock_sync_execute,
            patch(
                "ee.hogai.chat_agent.slash_commands.commands.usage.queries.build_ai_billing_region_filter"
            ) as mock_region_filter,
        ):
            mock_region.return_value = region
            mock_sync_execute.return_value = [(42,)]
            if expected_region_url is not None:
                mock_region_filter.return_value = {
                    "region_group_property": f"$group_{instance_group_index}",
                    "region_url": expected_region_url,
                }

            credits = get_ai_credits(team_id=133393, begin=begin, end=end, conversation_id=conversation_id)

            assert credits == 42
            query, params = mock_sync_execute.call_args[0][:2]
            assert params["team_to_query"] == expected_team_to_query
            assert params["session_id"] == str(conversation_id)
            if expected_region_url is None:
                assert "region_url" not in params
                assert "%(region_url)s" not in query
                mock_region_filter.assert_not_called()
            else:
                assert params["region_url"] == expected_region_url
                assert params["region_group_property"] == f"$group_{instance_group_index}"
                mock_region_filter.assert_called_once_with(expected_team_to_query, expected_region_url)
                assert "AND JSONExtractString(properties, %(region_group_property)s) = %(region_url)s" in query

    def test_get_ai_credits_returns_zero_when_instance_group_missing(self):
        begin = datetime(2026, 5, 1, tzinfo=UTC)
        end = datetime(2026, 5, 2, tzinfo=UTC)
        conversation_id = uuid4()

        with (
            patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.get_instance_region") as mock_region,
            patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.sync_execute") as mock_sync_execute,
            patch(
                "ee.hogai.chat_agent.slash_commands.commands.usage.queries.build_ai_billing_region_filter",
                return_value=None,
            ),
        ):
            mock_region.return_value = "EU"

            credits = get_ai_credits(team_id=133393, begin=begin, end=end, conversation_id=conversation_id)

            assert credits == 0
            mock_sync_execute.assert_not_called()

    def test_get_conversation_start_time_exists(self):
        """Test retrieving conversation start time for existing conversation."""
        conversation = Conversation.objects.create(
            team=self.team,
            user=self.user,
        )
        start_time = get_conversation_start_time(conversation.id)
        assert start_time is not None
        assert cast(datetime, start_time).replace(microsecond=0) == cast(datetime, conversation.created_at).replace(
            microsecond=0
        )

    def test_get_conversation_start_time_not_exists(self):
        """Test that non-existent conversation returns None."""
        start_time = get_conversation_start_time(uuid4())
        assert start_time is None

    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.posthoganalytics.get_feature_flag_payload")
    def test_get_ga_launch_date_from_payload(self, mock_payload):
        """Test that GA launch date is fetched from feature flag payload."""
        mock_payload.return_value = {"ga_launch_date": "2025-12-01", "EU": {"1": 10000}}
        ga_date = get_ga_launch_date()
        assert ga_date == datetime(2025, 12, 1, tzinfo=UTC)

    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.posthoganalytics.get_feature_flag_payload")
    def test_get_ga_launch_date_fallback(self, mock_payload):
        """Test that GA launch date falls back to default when not in payload."""
        mock_payload.return_value = None
        ga_date = get_ga_launch_date()
        assert ga_date == DEFAULT_GA_LAUNCH_DATE

    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.posthoganalytics.get_feature_flag_payload")
    def test_get_ga_launch_date_invalid_format(self, mock_payload):
        """Test that invalid date format falls back to default."""
        mock_payload.return_value = {"ga_launch_date": "invalid-date"}
        ga_date = get_ga_launch_date()
        assert ga_date == DEFAULT_GA_LAUNCH_DATE

    def test_get_past_month_start_normal(self):
        """Test past month start when 30 days ago is after GA launch."""
        now = datetime(2025, 12, 20, tzinfo=UTC)
        with patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.datetime") as mock_datetime:
            mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)
            mock_datetime.now.return_value = now
            past_month_start = get_past_month_start()
            expected = datetime(2025, 11, 20, tzinfo=UTC)
            assert past_month_start == expected

    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.posthoganalytics.get_feature_flag_payload")
    def test_get_past_month_start_capped_at_ga_launch(self, mock_payload):
        """Test that past month start is capped at GA launch date."""
        mock_payload.return_value = None
        now = DEFAULT_GA_LAUNCH_DATE + timedelta(days=10)
        with patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.datetime") as mock_datetime:
            mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)
            mock_datetime.now.return_value = now
            past_month_start = get_past_month_start()
            assert past_month_start == DEFAULT_GA_LAUNCH_DATE

    def test_get_ai_usage_period_from_billing_context(self):
        billing_context = {
            "billing_period": {
                "current_period_start": "2026-05-02T14:51:12Z",
                "current_period_end": "2026-06-02T14:51:12Z",
                "interval": "month",
            },
            "billing_plan": "paid",
            "has_active_subscription": True,
            "is_deactivated": False,
            "products": [],
            "settings": {"autocapture_on": True, "active_destinations": 0},
            "subscription_level": "paid",
        }

        usage_period = get_ai_usage_period(self.team, billing_context)

        assert usage_period.label == "Billing period"
        assert usage_period.start == datetime(2026, 5, 2, 14, 51, 12, tzinfo=UTC)
        assert usage_period.end == datetime(2026, 6, 2, 14, 51, 12, tzinfo=UTC)
        assert usage_period.query_start == datetime(2026, 5, 2, 14, 51, 12, tzinfo=UTC)

    def test_get_ai_usage_period_from_organization_usage(self):
        self.organization.usage = {
            "period": ["2026-05-02T14:51:12Z", "2026-06-02T14:51:12Z"],
        }

        usage_period = get_ai_usage_period(self.team, None)

        assert usage_period.label == "Billing period"
        assert usage_period.start == datetime(2026, 5, 2, 14, 51, 12, tzinfo=UTC)
        assert usage_period.end == datetime(2026, 6, 2, 14, 51, 12, tzinfo=UTC)
        assert usage_period.query_start == datetime(2026, 5, 2, 14, 51, 12, tzinfo=UTC)

    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.posthoganalytics.get_feature_flag_payload")
    def test_get_ai_usage_period_caps_query_start_at_ga_launch(self, mock_payload):
        mock_payload.return_value = None
        self.organization.usage = {
            "period": ["2025-11-01T00:00:00Z", "2025-12-01T00:00:00Z"],
        }

        usage_period = get_ai_usage_period(self.team, None)

        assert usage_period.label == "Billing period"
        assert usage_period.start == datetime(2025, 11, 1, tzinfo=UTC)
        assert usage_period.end == datetime(2025, 12, 1, tzinfo=UTC)
        assert usage_period.query_start == DEFAULT_GA_LAUNCH_DATE

    def test_get_ai_usage_period_falls_back_to_past_month(self):
        now = datetime(2025, 12, 20, tzinfo=UTC)
        with patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.datetime") as mock_datetime:
            mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)
            mock_datetime.now.return_value = now

            usage_period = get_ai_usage_period(self.team, None)

        assert usage_period.label == "Past 30 days"
        assert usage_period.start == datetime(2025, 11, 20, tzinfo=UTC)
        assert usage_period.end == now
        assert usage_period.query_start == datetime(2025, 11, 20, tzinfo=UTC)

    def test_format_usage_message_no_usage(self):
        """Test formatting when no credits have been used."""
        message = format_usage_message(
            conversation_credits=0,
            period_credits=0,
            free_tier_credits=2000,
            usage_period=AiUsagePeriod(
                label="Billing period",
                start=datetime(2026, 5, 2, 14, 51, 12, tzinfo=UTC),
                end=datetime(2026, 6, 2, 14, 51, 12, tzinfo=UTC),
                query_start=datetime(2026, 5, 2, 14, 51, 12, tzinfo=UTC),
            ),
        )
        assert "**Current conversation**: 0 credits" in message
        assert "**Billing period** (2026-05-02 to 2026-06-02): 0 credits" in message
        assert "**Free tier limit**: 2,000 credits" in message
        assert "**Remaining**: 2,000 credits" in message
        assert "0% of free tier" in message
        assert "_Billing period resets on_: 2026-06-02 14:51 UTC" in message

    def test_format_usage_message_partial_usage(self):
        """Test formatting with partial usage."""
        message = format_usage_message(
            conversation_credits=50,
            period_credits=500,
            free_tier_credits=2000,
            usage_period=AiUsagePeriod(
                label="Billing period",
                start=datetime(2026, 5, 2, tzinfo=UTC),
                end=datetime(2026, 6, 2, tzinfo=UTC),
                query_start=datetime(2026, 5, 2, tzinfo=UTC),
            ),
        )
        assert "**Current conversation**: 50 credits" in message
        assert "**Billing period** (2026-05-02 to 2026-06-02): 500 credits" in message
        assert "**Remaining**: 1,500 credits" in message
        assert "25% of free tier" in message

    def test_format_usage_message_over_limit(self):
        """Test formatting when over the free tier limit."""
        message = format_usage_message(
            conversation_credits=100,
            period_credits=2500,
            free_tier_credits=2000,
            usage_period=AiUsagePeriod(
                label="Billing period",
                start=datetime(2026, 5, 2, tzinfo=UTC),
                end=datetime(2026, 6, 2, tzinfo=UTC),
                query_start=datetime(2026, 5, 2, tzinfo=UTC),
            ),
        )
        assert "**Overage**: 500 credits over limit" in message
        assert "125% of free tier" in message

    @patch("ee.hogai.chat_agent.slash_commands.commands.usage.queries.posthoganalytics.get_feature_flag_payload")
    def test_format_usage_message_with_ga_cap(self, mock_payload):
        """Test formatting when GA cap is active."""
        mock_payload.return_value = None
        message = format_usage_message(
            conversation_credits=10,
            period_credits=100,
            free_tier_credits=2000,
            usage_period=AiUsagePeriod(
                label="Billing period",
                start=datetime(2025, 11, 1, tzinfo=UTC),
                end=datetime(2025, 12, 1, tzinfo=UTC),
                query_start=DEFAULT_GA_LAUNCH_DATE,
            ),
        )
        assert f"since {DEFAULT_GA_LAUNCH_DATE.strftime('%Y-%m-%d')}" in message
        assert f"from PostHog AI general availability date ({DEFAULT_GA_LAUNCH_DATE.strftime('%b %d, %Y')})" in message

    def test_format_usage_message_with_conversation_start(self):
        """Test formatting with conversation start time."""
        conv_start = datetime(2025, 11, 18, 10, 30, tzinfo=UTC)
        message = format_usage_message(
            conversation_credits=25,
            period_credits=200,
            free_tier_credits=2000,
            conversation_start=conv_start,
        )
        assert "_Conversation since_: 2025-11-18 10:30 UTC" in message

    def test_format_usage_message_progress_bar(self):
        """Test that progress bar is rendered correctly."""
        message = format_usage_message(
            conversation_credits=0,
            period_credits=1000,
            free_tier_credits=2000,
        )
        assert "█" * 10 in message
        assert "░" * 10 in message

    def test_format_usage_message_full_progress_bar(self):
        """Test progress bar when at 100% usage."""
        message = format_usage_message(
            conversation_credits=0,
            period_credits=2000,
            free_tier_credits=2000,
        )
        assert "█" * 20 in message
        assert "░" not in message
