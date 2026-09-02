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
        # Legacy, frozen columns — edit SAML settings via IdentityProviderConfigAdmin instead.
        "_identity_provider_config",
        "_saml_entity_id",
        "_saml_acs_url",
        "_saml_x509_cert",
        "_scim_enabled",
        "_scim_bearer_token",
        "_id_jag_issuer_url",
        "_id_jag_jwks_url",
        "_id_jag_allowed_clients",
    )
    autocomplete_fields = ["organization"]
    fieldsets = (
        (None, {"fields": ("id", "organization", "domain", "_identity_provider_config")}),
        ("Verification", {"fields": ("verification_challenge", "verified_at", "last_verification_retry")}),
        ("Access Control", {"fields": ("jit_provisioning_enabled", "sso_enforcement")}),
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
        if obj.saml_identity_provider_configs.exists():
            return format_html('<span style="color: green;">✓ Configured</span>')
        return format_html('<span style="color: gray;">Not Configured</span>')
