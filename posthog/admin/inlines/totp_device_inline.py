from django.contrib import admin
from django_otp.plugins.otp_totp.models import TOTPDevice


class TOTPDeviceInline(admin.TabularInline):
    model = TOTPDevice
    extra = 0
