from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from posthog.models import IdentityProviderConfig


@admin.register(IdentityProviderConfig)
class IdentityProviderConfigAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "organization_link",
        "saml_status",
        "scim_enabled",
        "id_jag_issuer_url",
        "created_at",
    )
    list_filter = ("scim_enabled",)
    search_fields = ("name", "organization__name", "domains__domain")
    readonly_fields = ("id", "created_at", "updated_at", "linked_domains")
    autocomplete_fields = ["organization"]
    fieldsets = (
        (None, {"fields": ("id", "organization", "name", "created_at", "updated_at", "linked_domains")}),
        ("SAML Configuration", {"fields": ("saml_entity_id", "saml_acs_url", "saml_x509_cert")}),
        ("SCIM Configuration", {"fields": ("scim_enabled", "scim_bearer_token")}),
        ("ID-JAG (XAA) Configuration", {"fields": ("id_jag_issuer_url", "id_jag_jwks_url", "id_jag_allowed_clients")}),
    )
    ordering = ("-created_at",)

    @admin.display(description="Organization", ordering="organization__name")
    def organization_link(self, obj):
        if obj.organization:
            url = reverse("admin:posthog_organization_change", args=[obj.organization.pk])
            return format_html('<a href="{}">{}</a>', url, obj.organization.name)
        return "-"

    @admin.display(description="SAML Status")
    def saml_status(self, obj):
        if obj.has_saml:
            return format_html('<span style="color: green;">✓ Configured</span>')
        return format_html('<span style="color: gray;">Not Configured</span>')

    @admin.display(description="Linked domains")
    def linked_domains(self, obj):
        domains = list(obj.domains.order_by("domain").values_list("domain", flat=True))
        return ", ".join(domains) if domains else "-"
