from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils.translation import ugettext_lazy as _

from posthog.models import (
    Action,
    ActionStep,
    DashboardItem,
    Element,
    Event,
    FeatureFlag,
    Organization,
    Person,
    Team,
    User,
)

admin.site.register(Team)
admin.site.register(Person)
admin.site.register(Element)
admin.site.register(FeatureFlag)
admin.site.register(Action)
admin.site.register(ActionStep)
admin.site.register(DashboardItem)


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    readonly_fields = ("timestamp",)
    list_display = (
        "timestamp",
        "event",
        "id",
    )

    def get_queryset(self, request):
        qs = super(EventAdmin, self).get_queryset(request)
        return qs.order_by("-timestamp")


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Define admin model for custom User model with no email field."""

    change_form_template = "loginas/change_form.html"

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Personal info"), {"fields": ("first_name", "last_name")}),
        (_("Permissions"), {"fields": ("is_active", "is_staff", "groups", "user_permissions",)},),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
        (_("PostHog"), {"fields": ("temporary_token",)}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2"),}),)
    list_display = ("email", "first_name", "last_name", "is_staff")
    list_filter = ("is_staff", "is_active", "groups")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("email",)


@admin.register(Organization)
class OrganizationBillingAdmin(admin.ModelAdmin):
    search_fields = ("name", "members__email")
