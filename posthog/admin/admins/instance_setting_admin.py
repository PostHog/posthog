import json

from django.contrib import admin


class InstanceSettingAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "key",
        "value",
    )

    def save_model(self, request, obj, form, change):
        # Ensure raw_value is valid JSON before saving.
        # set_instance_setting() does json.dumps() but Django admin bypasses it,
        # so bare strings like "abc123" get saved instead of '"abc123"'.
        try:
            json.loads(obj.raw_value)
        except (json.JSONDecodeError, ValueError):
            obj.raw_value = json.dumps(obj.raw_value)
        super().save_model(request, obj, form, change)
