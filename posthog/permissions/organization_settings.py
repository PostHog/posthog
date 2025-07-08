from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from posthog.services.organization_settings import OrganizationSettingsService


class OrganizationSettingPermission(BasePermission):
    """Generic permission class for organization settings"""

    def has_permission(self, request: Request, view) -> bool:
        setting_key = getattr(view, "setting_key", None)
        if not setting_key:
            return True

        user = request.user
        organization = user.organization

        if not organization:
            return False

        service = OrganizationSettingsService(organization)
        return service.can_user_edit_setting(setting_key, user)


class OrganizationSettingsViewPermission(BasePermission):
    """Permission class for viewing organization settings"""

    def has_permission(self, request: Request, view) -> bool:
        # Everyone can view organization settings
        return True


class OrganizationSettingsEditPermission(BasePermission):
    """Permission class for editing organization settings"""

    def has_permission(self, request: Request, view) -> bool:
        user = request.user
        organization = user.organization

        if not organization:
            return False

        # Check if user has admin or owner level
        try:
            membership = organization.memberships.get(user=user)
            return membership.level >= 8  # Admin or higher
        except:
            return False

    def has_object_permission(self, request: Request, view, obj) -> bool:
        """Check if user can edit a specific setting"""
        user = request.user
        organization = obj.organization

        service = OrganizationSettingsService(organization)
        return service.can_user_edit_setting(obj.setting_key, user)


class HasEnabledSettingPermission(BasePermission):
    """Permission class that checks if a user can perform an action based on a setting"""

    def has_permission(self, request: Request, view) -> bool:
        # Get the setting key from the view
        setting_key = getattr(view, "has_enabled_setting", None)
        if not setting_key:
            return True  # If no setting specified, allow access

        user = request.user
        organization = user.organization

        if not organization:
            return False

        service = OrganizationSettingsService(organization)
        return service.can_user_perform_action(setting_key, user)

    def has_object_permission(self, request: Request, view, obj) -> bool:
        """Check if user can perform action on a specific object"""
        setting_key = getattr(view, "has_enabled_setting", None)
        if not setting_key:
            return True

        user = request.user
        organization = user.organization

        if not organization:
            return False

        service = OrganizationSettingsService(organization)
        return service.can_user_perform_action(setting_key, user)
