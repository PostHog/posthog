from django.contrib import admin

from ee.models.scim_provisioned_user import SCIMProvisionedUser


class SCIMProvisionedUserInline(admin.TabularInline):
    """
    Inline table for SCIMProvisionedUser records on the User admin page.
    Shows SCIM provisioning details and allows deletion.
    """

    model = SCIMProvisionedUser
    extra = 0
    # Both FKs stay in readonly_fields so the change page renders them as plain text instead of a
    # <select> that loads every config and domain per row.
    fields = (
        "identity_provider_config",
        "organization_domain",
        "identity_provider",
        "username",
        "active",
        "created_at",
    )
    readonly_fields = (
        "identity_provider_config",
        "organization_domain",
        "identity_provider",
        "username",
        "active",
        "created_at",
    )
    can_delete = True
    show_change_link = False
    verbose_name = "SCIM provisioned user"
    verbose_name_plural = "SCIM provisioned users"

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return True
