from django.contrib import admin


class InstanceSettingAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "key",
        "value",
    )
