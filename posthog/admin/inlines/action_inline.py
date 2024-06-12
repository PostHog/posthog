from django.contrib import admin

from posthog.models import Action


class ActionInline(admin.TabularInline):
    extra = 0
    model = Action
    classes = ("collapse",)
    autocomplete_fields = ("created_by",)
    exclude = ("events",)
