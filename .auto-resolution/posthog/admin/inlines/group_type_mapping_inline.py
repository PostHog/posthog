from django.contrib import admin

from posthog.models import GroupTypeMapping


class GroupTypeMappingInline(admin.TabularInline):
    extra = 0
    model = GroupTypeMapping
    fields = ("group_type_index", "group_type", "name_singular", "name_plural")
    readonly_fields = fields
    classes = ("collapse",)
    max_num = 5
    min_num = 5
    show_change_link = True
