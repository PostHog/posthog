from parameterized import parameterized

from posthog.models.sharing_configuration import SharingConfiguration, SharingConfigurationSettings
from posthog.test.base import BaseTest


class TestSharingConfigurationSettings(BaseTest):
    """Test the SharingConfigurationSettings Pydantic model"""

    def test_default_values(self):
        """Test that all fields have correct default values"""
        settings = SharingConfigurationSettings()
        assert settings.whitelabel is False
        assert settings.noHeader is False
        assert settings.showInspector is False
        assert settings.legend is False
        assert settings.detailed is False

    def test_from_dict_with_empty_dict(self):
        """Test from_dict with empty dictionary returns defaults"""
        settings = SharingConfigurationSettings.from_dict({})
        assert settings.whitelabel is False
        assert settings.noHeader is False
        assert settings.showInspector is False
        assert settings.legend is False
        assert settings.detailed is False

    def test_from_dict_with_partial_data(self):
        """Test from_dict with partial data uses defaults for missing fields"""
        data = {"whitelabel": True, "legend": True}
        settings = SharingConfigurationSettings.from_dict(data)
        assert settings.whitelabel is True
        assert settings.legend is True
        assert settings.noHeader is False  # default
        assert settings.showInspector is False  # default
        assert settings.detailed is False  # default

    def test_from_dict_with_complete_data(self):
        """Test from_dict with complete data"""
        data = {
            "whitelabel": True,
            "noHeader": True,
            "showInspector": True,
            "legend": True,
            "detailed": True,
        }
        settings = SharingConfigurationSettings.from_dict(data)
        assert settings.whitelabel is True
        assert settings.noHeader is True
        assert settings.showInspector is True
        assert settings.legend is True
        assert settings.detailed is True

    def test_from_dict_filters_unknown_fields(self):
        """Test from_dict filters out unknown fields"""
        data = {
            "whitelabel": True,
            "unknownField": "should be ignored",
            "anotherUnknown": 123,
            "legend": False,
        }
        settings = SharingConfigurationSettings.from_dict(data)
        assert settings.whitelabel is True
        assert settings.legend is False
        # Unknown fields should not be included in the model
        assert not hasattr(settings, "unknownField")
        assert not hasattr(settings, "anotherUnknown")

    def test_merge_with_query_params_empty(self):
        """Test merge_with_query_params with empty query params"""
        settings = SharingConfigurationSettings(whitelabel=True, legend=True)
        merged = settings.merge_with_query_params({})
        assert merged.whitelabel is True
        assert merged.legend is True
        assert merged.noHeader is False

    def test_merge_with_query_params_overrides(self):
        """Test merge_with_query_params overrides existing values"""
        settings = SharingConfigurationSettings(whitelabel=False, legend=False)
        query_params = {"whitelabel": "true", "legend": "1", "detailed": "yes"}
        merged = settings.merge_with_query_params(query_params)

        # Query params should override base settings (converted to bool)
        assert merged.whitelabel is True  # "true" -> True
        assert merged.legend is True  # "1" -> True
        assert merged.detailed is True  # "yes" -> True
        assert merged.noHeader is False  # not in query params, keeps original

    def test_merge_with_query_params_ignores_unknown_fields(self):
        """Test merge_with_query_params ignores unknown query param fields"""
        settings = SharingConfigurationSettings(whitelabel=True)
        query_params = {"whitelabel": "", "unknownParam": "true", "legend": "true"}
        merged = settings.merge_with_query_params(query_params)

        assert merged.whitelabel is False  # empty string -> False
        assert merged.legend is True
        # Unknown param should be ignored
        assert not hasattr(merged, "unknownParam")

    def test_model_dump_structure(self):
        """Test that model_dump returns expected dictionary structure"""
        settings = SharingConfigurationSettings(whitelabel=True, noHeader=True, showInspector=False)
        dump = settings.model_dump()
        expected = {
            "whitelabel": True,
            "noHeader": True,
            "showInspector": False,
            "legend": False,
            "detailed": False,
        }
        assert dump == expected

    @parameterized.expand(
        [
            # Test boolean conversion from query param strings
            ("true", True),
            ("1", True),
            ("yes", True),
            ("on", True),
            ("", False),
            ("false", False),
            ("0", False),
            ("no", False),
            ("off", False),
        ]
    )
    def test_query_param_boolean_conversion(self, param_value: str, expected: bool):
        """Test that query parameters are properly converted to booleans"""
        settings = SharingConfigurationSettings()
        merged = settings.merge_with_query_params({"whitelabel": param_value})
        assert merged.whitelabel is expected


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
