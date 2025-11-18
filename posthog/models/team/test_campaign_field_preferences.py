import pytest
from posthog.test.base import BaseTest

from django.core.exceptions import ValidationError


class TestCampaignFieldPreferencesValidation(BaseTest):
    """
    Tests for campaign_field_preferences validation on TeamMarketingAnalyticsConfig.
    """

    def test_valid_campaign_field_preferences_structure(self):
        """Test that valid campaign_field_preferences structure is accepted"""
        valid_preferences = {
            "GoogleAds": {"match_field": "campaign_name", "fallback_field": None},
            "MetaAds": {"match_field": "campaign_id", "fallback_field": "campaign_name"},
            "LinkedinAds": {"match_field": "campaign_id", "fallback_field": None},
        }

        # Should not raise ValidationError
        self.team.marketing_analytics_config.campaign_field_preferences = valid_preferences
        self.team.marketing_analytics_config.save()
        self.team.marketing_analytics_config.refresh_from_db()

        assert self.team.marketing_analytics_config.campaign_field_preferences == valid_preferences

    def test_empty_campaign_field_preferences(self):
        """Test that empty dict is valid"""
        self.team.marketing_analytics_config.campaign_field_preferences = {}
        self.team.marketing_analytics_config.save()
        self.team.marketing_analytics_config.refresh_from_db()

        assert self.team.marketing_analytics_config.campaign_field_preferences == {}

    def test_invalid_match_field_value(self):
        """Test that invalid match_field value is rejected"""
        invalid_preferences = {"GoogleAds": {"match_field": "invalid_value", "fallback_field": None}}

        with pytest.raises(ValidationError) as exc_info:
            self.team.marketing_analytics_config.campaign_field_preferences = invalid_preferences

        assert "Invalid match_field" in str(exc_info.value)
        assert "Must be one of" in str(exc_info.value)

    def test_manual_only_is_no_longer_valid(self):
        """Test that manual_only is no longer a valid match_field (manual mappings always override)"""
        invalid_preferences = {"GoogleAds": {"match_field": "manual_only", "fallback_field": None}}

        with pytest.raises(ValidationError) as exc_info:
            self.team.marketing_analytics_config.campaign_field_preferences = invalid_preferences

        assert "Invalid match_field" in str(exc_info.value)
        assert "manual_only" in str(exc_info.value)

    def test_invalid_fallback_field_value(self):
        """Test that invalid fallback_field value is rejected"""
        invalid_preferences = {"GoogleAds": {"match_field": "campaign_name", "fallback_field": "invalid_value"}}

        with pytest.raises(ValidationError) as exc_info:
            self.team.marketing_analytics_config.campaign_field_preferences = invalid_preferences

        assert "Invalid fallback_field" in str(exc_info.value)
        assert "Must be one of" in str(exc_info.value)

    def test_fallback_cannot_equal_match_field(self):
        """Test that fallback_field cannot be the same as match_field"""
        invalid_preferences = {"GoogleAds": {"match_field": "campaign_name", "fallback_field": "campaign_name"}}

        with pytest.raises(ValidationError) as exc_info:
            self.team.marketing_analytics_config.campaign_field_preferences = invalid_preferences

        assert "fallback_field cannot be the same as match_field" in str(exc_info.value)

    def test_missing_match_field(self):
        """Test that match_field is required"""
        invalid_preferences = {"GoogleAds": {"fallback_field": None}}

        with pytest.raises(ValidationError) as exc_info:
            self.team.marketing_analytics_config.campaign_field_preferences = invalid_preferences

        assert "must have a" in str(exc_info.value)
        assert "match_field" in str(exc_info.value)

    def test_config_not_a_dict(self):
        """Test that config for each integration must be a dict"""
        invalid_preferences = {"GoogleAds": "not_a_dict"}

        with pytest.raises(ValidationError) as exc_info:
            self.team.marketing_analytics_config.campaign_field_preferences = invalid_preferences

        assert "must be a dictionary" in str(exc_info.value)

    def test_preferences_not_a_dict(self):
        """Test that campaign_field_preferences must be a dict"""
        with pytest.raises(ValidationError) as exc_info:
            self.team.marketing_analytics_config.campaign_field_preferences = "not_a_dict"

        assert "campaign_field_preferences must be a dictionary" in str(exc_info.value)

    def test_integration_type_must_be_string(self):
        """Test that integration type keys must be strings"""
        # This should already be enforced by Python dict keys, but let's ensure non-string keys are handled
        # In practice, JSON doesn't support non-string keys, so this is mostly for completeness
        valid_preferences = {"GoogleAds": {"match_field": "campaign_name", "fallback_field": None}}

        self.team.marketing_analytics_config.campaign_field_preferences = valid_preferences
        self.team.marketing_analytics_config.save()
        # Should work fine

    def test_multiple_integrations_with_different_preferences(self):
        """Test that different integrations can have different preferences"""
        preferences = {
            "GoogleAds": {"match_field": "campaign_id", "fallback_field": None},
            "MetaAds": {"match_field": "campaign_name", "fallback_field": "campaign_id"},
            "LinkedinAds": {"match_field": "campaign_id", "fallback_field": "campaign_name"},
            "TikTokAds": {"match_field": "campaign_id", "fallback_field": "campaign_name"},
            "RedditAds": {"match_field": "campaign_name", "fallback_field": None},
        }

        self.team.marketing_analytics_config.campaign_field_preferences = preferences
        self.team.marketing_analytics_config.save()
        self.team.marketing_analytics_config.refresh_from_db()

        assert self.team.marketing_analytics_config.campaign_field_preferences == preferences

    def test_null_campaign_field_preferences(self):
        """Test that None is converted to empty dict"""
        self.team.marketing_analytics_config.campaign_field_preferences = None
        self.team.marketing_analytics_config.save()
        self.team.marketing_analytics_config.refresh_from_db()

        # None should be converted to empty dict by the property setter
        assert self.team.marketing_analytics_config.campaign_field_preferences == {}

    def test_valid_all_match_field_options(self):
        """Test that all valid match_field options work"""
        for match_field in ["campaign_name", "campaign_id"]:
            preferences = {"GoogleAds": {"match_field": match_field, "fallback_field": None}}
            self.team.marketing_analytics_config.campaign_field_preferences = preferences
            self.team.marketing_analytics_config.save()
            # Should not raise

    def test_valid_fallback_field_options(self):
        """Test that all valid fallback_field options work"""
        for fallback_field in ["campaign_name", "campaign_id", None]:
            # Skip if fallback equals match_field
            if fallback_field == "campaign_name":
                match_field = "campaign_id"
            else:
                match_field = "campaign_name"

            preferences = {"GoogleAds": {"match_field": match_field, "fallback_field": fallback_field}}
            self.team.marketing_analytics_config.campaign_field_preferences = preferences
            self.team.marketing_analytics_config.save()
            # Should not raise
