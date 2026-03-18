from django.contrib import admin

from social_django.models import UserSocialAuth


class UserSocialAuthInline(admin.TabularInline):
    """
    Inline table for UserSocialAuth records on the User admin page.
    Allows viewing and deleting social auth connections.
    """

    model = UserSocialAuth
    extra = 0
    fields = ("provider", "uid", "extra_data", "created", "modified")
    readonly_fields = ("provider", "uid", "extra_data", "created", "modified")
    can_delete = True
    show_change_link = False
    verbose_name = "Social auth connection"
    verbose_name_plural = "Social auth connections"

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return True
