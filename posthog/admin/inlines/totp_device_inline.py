from django.contrib import admin

from django_otp.plugins.otp_totp.models import TOTPDevice


class TOTPDeviceInline(admin.TabularInline):
    model = TOTPDevice
    extra = 0
    # only include non-sensitive fields
    fields = ("name", "confirmed", "throttling_failure_timestamp", "throttling_failure_count", "last_used_at")
    readonly_fields = ("name", "confirmed", "throttling_failure_timestamp", "throttling_failure_count", "last_used_at")
    can_delete = False
    show_change_link = False

    def has_add_permission(self, request, obj=None):
        # Prevent adding TOTP devices through the admin (they should be created via API)
        return False

    def has_change_permission(self, request, obj=None):
        # Make the inline completely read-only to prevent formset validation issues
        return False

    def has_view_permission(self, request, obj=None):
        # Ensure the inline is still visible even though change permission is False
        return True
