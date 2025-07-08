from posthog.models.organization_setting_definitions import OrganizationSettingKey
from posthog.test.base import APIBaseTest


class TestOrganizationSettingsAPI(APIBaseTest):
    def setUp(self):
        super().setUp()

    def test_get_settings(self):
        """Test getting organization settings"""
        response = self.client.get(f"/api/organizations/{self.organization.id}/settings/")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.data, list)

    def test_upsert_setting(self):
        """Test upserting a setting"""
        data = {"setting_key": OrganizationSettingKey.CUSTOM_BRANDING_ENABLED.value, "setting_value": True}

        response = self.client.put(f"/api/organizations/{self.organization.id}/settings/", data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["setting_value"], True)

    def test_upsert_setting_invalid_value(self):
        """Test upserting a setting with invalid value"""
        data = {"setting_key": OrganizationSettingKey.CUSTOM_BRANDING_ENABLED.value, "setting_value": "not_a_boolean"}

        response = self.client.put(f"/api/organizations/{self.organization.id}/settings/", data)
        self.assertEqual(response.status_code, 400)

    def test_upsert_setting_invalid_key(self):
        """Test upserting a setting with invalid key"""
        data = {"setting_key": "invalid_setting_key", "setting_value": True}

        response = self.client.put(f"/api/organizations/{self.organization.id}/settings/", data)
        self.assertEqual(response.status_code, 400)

    def test_bulk_update_settings(self):
        """Test bulk updating settings"""
        data = {
            "settings": [
                {"setting_key": OrganizationSettingKey.CUSTOM_BRANDING_ENABLED.value, "setting_value": True},
                {"setting_key": OrganizationSettingKey.ENFORCE_2FA.value, "setting_value": False},
            ]
        }

        response = self.client.post(f"/api/organizations/{self.organization.id}/settings/bulk_update/", data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 2)

    def test_bulk_update_settings_invalid(self):
        """Test bulk updating settings with invalid data"""
        data = {
            "settings": [
                {"setting_key": OrganizationSettingKey.CUSTOM_BRANDING_ENABLED.value, "setting_value": "not_a_boolean"}
            ]
        }

        response = self.client.post(f"/api/organizations/{self.organization.id}/settings/bulk_update/", data)
        self.assertEqual(response.status_code, 400)
