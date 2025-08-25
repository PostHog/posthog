from posthog.test.base import BaseTest

from posthog.schema import SharingConfigurationSettings

from posthog.models.sharing_configuration import SharingConfiguration


class TestSharingConfigurationSettings(BaseTest):
    """Test the SharingConfigurationSettings Pydantic model"""

    def test_default_values(self):
        """Test that all fields have correct default values"""
        settings = SharingConfigurationSettings()
        assert settings.whitelabel is None
        assert settings.noHeader is None
        assert settings.showInspector is None
        assert settings.legend is None
        assert settings.detailed is None

    def test_model_validate_with_empty_dict(self):
        """Test model_validate with empty dictionary returns defaults"""
        settings = SharingConfigurationSettings.model_validate({}, strict=False)
        assert settings.whitelabel is None
        assert settings.noHeader is None
        assert settings.showInspector is None
        assert settings.legend is None
        assert settings.detailed is None

    def test_model_validate_with_partial_data(self):
        """Test model_validate with partial data uses defaults for missing fields"""
        data = {"whitelabel": True, "legend": True}
        settings = SharingConfigurationSettings.model_validate(data, strict=False)
        assert settings.whitelabel is True
        assert settings.legend is True
        assert settings.noHeader is None  # default
        assert settings.showInspector is None  # default
        assert settings.detailed is None  # default

    def test_model_validate_with_complete_data(self):
        """Test model_validate with complete data"""
        data = {
            "whitelabel": True,
            "noHeader": True,
            "showInspector": True,
            "legend": True,
            "detailed": True,
        }
        settings = SharingConfigurationSettings.model_validate(data, strict=False)
        assert settings.whitelabel is True
        assert settings.noHeader is True
        assert settings.showInspector is True
        assert settings.legend is True
        assert settings.detailed is True

    def test_model_validate_rejects_unknown_fields(self):
        """Test model_validate rejects unknown fields due to extra='forbid'"""
        data = {
            "whitelabel": True,
            "unknownField": "should be rejected",
            "legend": False,
        }
        try:
            SharingConfigurationSettings.model_validate(data, strict=False)
            raise AssertionError("Should have raised ValidationError")
        except Exception:
            # This is expected due to extra="forbid"
            pass

    def test_model_dump_structure(self):
        """Test that model_dump returns expected dictionary structure"""
        settings = SharingConfigurationSettings(whitelabel=True, noHeader=True, showInspector=False)
        dump = settings.model_dump()
        expected = {
            "whitelabel": True,
            "noHeader": True,
            "showInspector": False,
            "legend": None,
            "hideExtraDetails": None,
            "detailed": None,
        }
        assert dump == expected

    def test_boolean_field_assignment(self):
        """Test that boolean fields can be assigned properly"""
        settings = SharingConfigurationSettings(whitelabel=True, noHeader=False)
        assert settings.whitelabel is True
        assert settings.noHeader is False


class TestSharingConfigurationModel(BaseTest):
    """Test the SharingConfiguration Django model"""

    def test_settings_field_defaults_to_none(self):
        """Test that the model's settings field defaults to None"""
        config = SharingConfiguration.objects.create(
            team=self.team,
            enabled=True,
        )
        assert config.settings is None

    def test_settings_field_can_store_data(self):
        """Test that settings field can store dictionary data"""
        settings_data = {"whitelabel": True, "custom": "value", "legend": False}
        config = SharingConfiguration.objects.create(team=self.team, enabled=True, settings=settings_data)
        assert config.settings == settings_data

    def test_rotate_access_token_preserves_settings(self):
        """Test that rotating access token preserves the settings"""
        settings_data = {
            "whitelabel": True,
            "noHeader": False,
            "showInspector": True,
            "legend": False,
            "detailed": True,
            "customSetting": "preserved",
        }
        original_config = SharingConfiguration.objects.create(team=self.team, enabled=True, settings=settings_data)

        # Rotate token
        new_config = original_config.rotate_access_token()

        # Settings should be preserved
        assert new_config.settings == settings_data
        assert new_config.access_token != original_config.access_token
        assert new_config.enabled == original_config.enabled
