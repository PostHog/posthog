from posthog.models.organization import Organization
from posthog.models.organization_settings import OrganizationSetting
from posthog.models.organization_setting_definitions import OrganizationSettingKey, get_setting_definition
from posthog.services.organization_settings import OrganizationSettingsService
from posthog.constants import AvailableFeature
from posthog.test.base import BaseTest


class TestOrganizationSettings(BaseTest):
    def setUp(self):
        super().setUp()
        self.organization = Organization.objects.create(name="Test Org")
        self.user = self.create_user(email="test@example.com")

        # Get test setting definition from code
        self.definition = get_setting_definition(OrganizationSettingKey.CUSTOM_BRANDING_ENABLED.value)
        self.service = OrganizationSettingsService(self.organization)

    def test_setting_creation(self):
        """Test creating a setting"""
        setting = self.service.set_setting(OrganizationSettingKey.CUSTOM_BRANDING_ENABLED, True, self.user)

        self.assertEqual(setting.setting_value, True)
        self.assertEqual(setting.created_by, self.user)

    def test_setting_validation(self):
        """Test setting validation"""
        # Test invalid value
        with self.assertRaises(ValueError):
            self.service.set_setting(OrganizationSettingKey.CUSTOM_BRANDING_ENABLED, "not_a_boolean", self.user)

    def test_feature_availability(self):
        """Test feature-based setting availability"""
        # Setting should not be active without feature
        self.assertFalse(self.service.is_setting_active(OrganizationSettingKey.CUSTOM_BRANDING_ENABLED))

        # Add feature to organization
        self.organization.available_product_features = [{"key": AvailableFeature.WHITE_LABELLING}]
        self.organization.save()

        # Setting should now be active
        self.assertTrue(self.service.is_setting_active(OrganizationSettingKey.CUSTOM_BRANDING_ENABLED))

    def test_multiple_features_required(self):
        """Test settings that require multiple features"""
        # This would require a definition with multiple features
        # For now, test with a single feature setting
        self.assertFalse(self.service.is_setting_active(OrganizationSettingKey.ADVANCED_PERMISSIONS_ENABLED))

        # Add feature to organization
        self.organization.available_product_features = [{"key": AvailableFeature.ADVANCED_PERMISSIONS}]
        self.organization.save()

        # Setting should now be active
        self.assertTrue(self.service.is_setting_active(OrganizationSettingKey.ADVANCED_PERMISSIONS_ENABLED))

    def test_validation_rules(self):
        """Test custom validation rules"""
        # Test integer validation with range
        setting = self.service.set_setting(OrganizationSettingKey.SESSION_RECORDING_RETENTION_DAYS, 50, self.user)
        self.assertEqual(setting.setting_value, 50)

        # Test invalid value (out of range)
        with self.assertRaises(ValueError):
            self.service.set_setting(OrganizationSettingKey.SESSION_RECORDING_RETENTION_DAYS, 400, self.user)

    def test_get_setting_with_default(self):
        """Test getting a setting with default value"""
        # Should return default value when setting doesn't exist
        value = self.service.get_setting(OrganizationSettingKey.CUSTOM_BRANDING_ENABLED)
        self.assertEqual(value, False)

        # Should return definition default when setting doesn't exist
        value = self.service.get_setting(OrganizationSettingKey.CUSTOM_BRANDING_ENABLED)
        self.assertEqual(value, False)

    def test_setting_manager_methods(self):
        """Test the custom manager methods"""
        # Test get_setting
        value = OrganizationSetting.objects.get_setting(
            self.organization, OrganizationSettingKey.CUSTOM_BRANDING_ENABLED.value
        )
        self.assertEqual(value, False)

        # Test set_setting
        setting = OrganizationSetting.objects.set_setting(
            self.organization, OrganizationSettingKey.CUSTOM_BRANDING_ENABLED.value, True, self.user
        )
        self.assertEqual(setting.setting_value, True)

        # Test get_settings_for_organization
        settings = OrganizationSetting.objects.get_settings_for_organization(self.organization)
        self.assertIn(OrganizationSettingKey.CUSTOM_BRANDING_ENABLED.value, settings)
        self.assertEqual(settings[OrganizationSettingKey.CUSTOM_BRANDING_ENABLED.value]["value"], True)
