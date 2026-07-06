from __future__ import annotations

import base64
import hashlib
from urllib.parse import urlencode

from django import forms
from django.contrib import admin
from django.contrib.admin import helpers
from django.template.response import TemplateResponse
from django.utils.html import format_html

from oauth2_provider.generators import generate_client_id, generate_client_secret
from oauth2_provider.models import AbstractApplication

from posthog.models.oauth import OAuthApplication, revoke_application_sessions


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

        if "provisioning_signing_secret" in self.fields:
            self.fields[
                "provisioning_signing_secret"
            ].help_text = "Only used for HMAC provisioning partners. Leave blank for PKCE or bearer clients."

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


# Registered manually in `posthog/admin/__init__.py::register_all_admin()`
# after `admin.site.unregister(OAuthApplication)` clears the default that
# `oauth2_provider`'s autodiscover sets up. `@admin.register` would race
# with that unregister and break the override.
class OAuthApplicationAdmin(admin.ModelAdmin):  # nosemgrep: admin-modeladmin-needs-register-decorator
    form = OAuthApplicationForm
    list_display = (
        "name",
        "client_id",
        "cimd_url",
        "verified",
        "dcr",
        "cimd",
        "first_party",
    )
    list_display_links = ("name",)
    list_filter = (
        "authorization_grant_type",
        "is_verified",
        "is_dcr_client",
        "is_cimd_client",
        "is_first_party",
        "auth_brand",
        "provisioning_active",
        "provisioning_auth_method",
        "provisioning_partner_type",
    )
    search_fields = ("name", "client_id", "cimd_metadata_url", "user__email", "organization__name")
    autocomplete_fields = ("user", "organization")
    ordering = ("name",)
    actions = ("revoke_all_sessions",)

    @admin.action(description="Revoke all sessions (force re-auth under current scopes)")
    def revoke_all_sessions(self, request, queryset):
        # Irreversible and app-wide (signs out every user/connection), so gate it behind an
        # interstitial confirmation instead of firing on the first click.
        if request.POST.get("confirm"):
            count = queryset.count()
            for application in queryset:
                revoke_application_sessions(application)
            self.message_user(request, f"Revoked all sessions for {count} application(s).")
            return None
        context = {
            **self.admin_site.each_context(request),
            "title": "Revoke all sessions",
            "queryset": queryset,
            "opts": self.model._meta,
            "action_checkbox_name": helpers.ACTION_CHECKBOX_NAME,
        }
        return TemplateResponse(request, "admin/posthog/oauthapplication/revoke_all_sessions_confirm.html", context)

    def view_on_site(self, obj: OAuthApplication):
        code_verifier = "test"
        digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
        code_challenge = base64.urlsafe_b64encode(digest).decode("utf-8").replace("=", "")

        redirect_uri = obj.redirect_uris.split()[0] if obj.redirect_uris else ""

        params = {
            "response_type": "code",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "client_id": obj.client_id,
            "redirect_uri": redirect_uri,
            "scope": "experiment:read query:read insight:read project:read organization:read openid",
        }

        return f"/oauth/authorize/?{urlencode(params)}"

    def get_readonly_fields(self, request, obj=None):
        if obj:
            readonly = ["id", "client_id", "is_dcr_client", "is_cimd_client", "cimd_metadata_url"]
            if obj.is_cimd_client:
                # A CIMD client's scope ceiling is derived from its own metadata document and
                # re-applied on every refresh, so a manual edit here would be silently reverted.
                # The unprivileged/hidden allow-list is the only ceiling that applies to CIMD
                # apps; to cut off an abusive one, block its metadata URL rather than editing scopes.
                readonly.append("scopes")
                # Model validation also rejects optional_scopes on CIMD apps: a split would
                # let the partner grow the locked required set via metadata refresh.
                readonly.append("optional_scopes")
            return tuple(readonly)
        else:
            return ("id", "is_dcr_client", "is_cimd_client")

    def get_fieldsets(self, request, obj=None):
        if obj:
            provisioning_fields = [
                "provisioning_auth_method",
                "provisioning_partner_type",
                "provisioning_active",
                "provisioning_skip_existing_user_consent",
                "provisioning_can_issue_deep_links",
                "provisioning_issues_personal_api_key",
                "provisioning_can_create_accounts",
                "provisioning_can_provision_resources",
                "provisioning_rate_limit_account_requests",
                "provisioning_rate_limit_token_exchanges",
                "provisioning_rate_limit_resource_creates",
            ]
            if obj.provisioning_auth_method == "hmac":
                provisioning_fields.append("provisioning_signing_secret")

            return (
                (None, {"fields": ("id", "name", "client_id", "client_type", "auth_brand", "logo_uri")}),
                (
                    "Authorization",
                    {"fields": ("authorization_grant_type", "redirect_uris", "algorithm", "scopes", "optional_scopes")},
                ),
                ("Ownership", {"fields": ("user", "organization")}),
                ("Status", {"fields": ("is_verified", "is_first_party", "is_dcr_client", "is_cimd_client")}),
                (
                    "Provisioning",
                    {
                        "description": "Provisioning settings for agentic partners. HMAC signing secret is only used for HMAC clients.",
                        "fields": tuple(provisioning_fields),
                    },
                ),
                (
                    "CIMD",
                    {
                        "classes": ("collapse",),
                        "fields": ("cimd_metadata_url", "cimd_metadata_last_fetched"),
                    },
                ),
            )
        else:
            return (
                (None, {"fields": ("name", "client_id", "client_secret", "client_type", "auth_brand", "logo_uri")}),
                (
                    "Authorization",
                    {"fields": ("authorization_grant_type", "redirect_uris", "algorithm", "scopes", "optional_scopes")},
                ),
                ("Ownership", {"fields": ("user", "organization")}),
                ("Status", {"fields": ("is_verified", "is_first_party")}),
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

    @admin.display(description="CIMD URL")
    def cimd_url(self, obj: OAuthApplication):
        if not obj.cimd_metadata_url:
            return "–"
        return format_html(
            '<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>',
            obj.cimd_metadata_url,
            obj.cimd_metadata_url,
        )

    @admin.display(description="Verified", boolean=True, ordering="is_verified")
    def verified(self, obj: OAuthApplication):
        return obj.is_verified

    @admin.display(description="DCR", boolean=True, ordering="is_dcr_client")
    def dcr(self, obj: OAuthApplication):
        return obj.is_dcr_client

    @admin.display(description="CIMD", boolean=True, ordering="is_cimd_client")
    def cimd(self, obj: OAuthApplication):
        return obj.is_cimd_client

    @admin.display(description="First party", boolean=True, ordering="is_first_party")
    def first_party(self, obj: OAuthApplication):
        return obj.is_first_party
