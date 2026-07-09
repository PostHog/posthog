from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from posthog.models import OrganizationDomain


@admin.register(OrganizationDomain)
class OrganizationDomainAdmin(admin.ModelAdmin):
    list_display = (
        "domain",
        "organization_link",
        "verified_at",
        "jit_provisioning_enabled",
        "sso_enforcement",
        "saml_status",
    )
    list_filter = (
        "jit_provisioning_enabled",
        "sso_enforcement",
        "verified_at",
    )
    search_fields = ("domain", "organization__name")
    readonly_fields = (
        "id",
        "domain",
        "verified_at",
        "verification_challenge",
        "last_verification_retry",
    )
    autocomplete_fields = ["organization", "identity_provider_config"]
    fieldsets = (
        (None, {"fields": ("id", "organization", "domain", "identity_provider_config")}),
        ("Verification", {"fields": ("verification_challenge", "verified_at", "last_verification_retry")}),
        ("Access Control", {"fields": ("jit_provisioning_enabled", "sso_enforcement")}),
        ("SAML Configuration", {"fields": ("_saml_entity_id", "_saml_acs_url", "_saml_x509_cert")}),
    )
    list_display_links = ("domain",)
    ordering = ("domain",)

    @admin.display(description="Organization", ordering="organization__name")
    def organization_link(self, obj):
        """Link to the organization admin page"""
        if obj.organization:
            url = reverse("admin:posthog_organization_change", args=[obj.organization.pk])
            return format_html('<a href="{}">{}</a>', url, obj.organization.name)
        return "-"

    @admin.display(description="SAML Status")
    def saml_status(self, obj):
        """Display SAML configuration status"""
        if obj.has_saml:
            return format_html('<span style="color: green;">✓ Configured</span>')
        return format_html('<span style="color: gray;">Not Configured</span>')
