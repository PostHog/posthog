from posthog.services.organization_settings import OrganizationSettingsService


class OrganizationSettingsMixin:
    """Mixin for views that work with organization settings"""

    def get_setting_service(self, organization):
        """Get settings service for an organization"""
        return OrganizationSettingsService(organization)

    def check_setting_permission(self, setting_key, user, organization):
        """Check if user can access a specific setting"""
        service = self.get_setting_service(organization)
        return service.can_user_edit_setting(setting_key, user)

    def get_available_settings_for_user(self, user, organization):
        """Get all settings available to a user"""
        service = self.get_setting_service(organization)
        return service.get_all_settings()

    def filter_settings_by_permissions(self, settings, user, organization):
        """Filter settings based on user permissions"""
        filtered_settings = {}
        service = self.get_setting_service(organization)

        for setting_key, setting_data in settings.items():
            if service.can_user_edit_setting(setting_key, user):
                filtered_settings[setting_key] = setting_data

        return filtered_settings
