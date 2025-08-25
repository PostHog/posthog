from django.contrib import admin

from django_otp.plugins.otp_totp.models import TOTPDevice


class TOTPDeviceInline(admin.TabularInline):
    model = TOTPDevice
    extra = 0
    # only include non-sensitive fields
    fields = ("name", "confirmed", "throttling_failure_timestamp", "throttling_failure_count", "last_used_at")
