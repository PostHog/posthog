from __future__ import annotations

from django import forms
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from oauth2_provider.generators import generate_client_id, generate_client_secret
from oauth2_provider.models import AbstractApplication

from posthog.models.oauth import OAuthApplication


class OAuthApplicationForm(forms.ModelForm):
    class Meta:
        model = OAuthApplication
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Set algorithm constraints
        if "algorithm" in self.fields:
            self.fields["algorithm"].initial = "RS256"
            self.fields["algorithm"].disabled = True
            self.fields["algorithm"].help_text = "Only RS256 is supported for security reasons"

        # Set authorization grant type constraints
        if "authorization_grant_type" in self.fields:
            self.fields["authorization_grant_type"].initial = AbstractApplication.GRANT_AUTHORIZATION_CODE
            self.fields["authorization_grant_type"].disabled = True
            self.fields["authorization_grant_type"].help_text = "Only authorization code grant type is supported"

        # For new applications, set defaults
        if not self.instance.pk:
            # Pre-generate client_id and client_secret
            if "client_id" in self.fields:
                self.fields["client_id"].initial = generate_client_id()
                self.fields["client_id"].help_text = "Generated automatically, but you can change it if needed"

            if "client_secret" in self.fields:
                self.fields["client_secret"].initial = generate_client_secret()
                self.fields["client_secret"].help_text = "⚠️ Save this secret now! It will be hashed after saving."

            # Set client type default
            if "client_type" in self.fields:
                self.fields["client_type"].initial = AbstractApplication.CLIENT_CONFIDENTIAL


class OAuthApplicationAdmin(admin.ModelAdmin):
    form = OAuthApplicationForm
    list_display = (
        "id",
        "name",
        "client_id",
        "user_link",
        "organization_link",
        "authorization_grant_type",
    )
    list_display_links = ("id", "name")
    list_filter = ("authorization_grant_type",)
    search_fields = ("name", "client_id", "user__email", "organization__name")
    autocomplete_fields = ("user", "organization")
    ordering = ("name",)

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ("id", "client_id")
        else:
            return ("id",)

    def get_fieldsets(self, request, obj=None):
        if obj:
            return (
                (None, {"fields": ("id", "name", "client_id", "client_type")}),
                (
                    "Authorization",
                    {"fields": ("authorization_grant_type", "redirect_uris", "algorithm")},
                ),
                ("Ownership", {"fields": ("user", "organization")}),
            )
        else:
            return (
                (None, {"fields": ("name", "client_id", "client_secret", "client_type")}),
                (
                    "Authorization",
                    {"fields": ("authorization_grant_type", "redirect_uris", "algorithm")},
                ),
                ("Ownership", {"fields": ("user", "organization")}),
            )

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj, change=change, **kwargs)

        if not obj:
            # Set user and organization defaults for new applications
            if "user" in form.base_fields and request.user:
                form.base_fields["user"].initial = request.user

            if (
                "organization" in form.base_fields
                and hasattr(request.user, "organization")
                and request.user.organization
            ):
                form.base_fields["organization"].initial = request.user.organization

        return form

    @admin.display(description="User")
    def user_link(self, obj: OAuthApplication):
        if not obj.user:
            return "–"
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_user_change", args=[obj.user.pk]),
            obj.user.email,
        )

    @admin.display(description="Organization")
    def organization_link(self, obj: OAuthApplication):
        if not obj.organization:
            return "–"
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_organization_change", args=[obj.organization.pk]),
            obj.organization.name,
        )
