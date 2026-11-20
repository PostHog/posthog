from django.contrib import admin

from posthog.models.organization_external_project_link import OrganizationExternalProjectLink


class OrganizationExternalProjectLinkInline(admin.TabularInline):
    model = OrganizationExternalProjectLink
    verbose_name = "Project switcher link to another instance"
    verbose_name_plural = "Project switcher links to other instances"
    extra = 0
    fields = ("name", "url")
