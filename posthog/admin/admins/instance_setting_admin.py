from django.contrib import admin

from posthog.models import InstanceSetting


@admin.register(InstanceSetting)
class InstanceSettingAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "key",
        "value",
    )
    readonly_fields = ("key", "raw_value")

    # Deletion stays: removing a stored row is how an instance moves that setting to its environment variable.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
