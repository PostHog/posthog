from __future__ import annotations

import base64
import hashlib
from urllib.parse import urlencode

from django import forms
from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html

from oauth2_provider.generators import generate_client_id, generate_client_secret
from oauth2_provider.models import AbstractApplication

from posthog.admin.console.moved import MovedToConsole
from posthog.admin.console.oauth_tool import RevokeSessionsForm
from posthog.api.oauth.cimd import is_cimd_client_id
from posthog.models.oauth import OAuthApplication
from posthog.models.oauth_provisioning import PROVISIONING_CAPABILITIES


class OAuthApplicationForm(forms.ModelForm):
    class Meta:
        model = OAuthApplication
        # Provisioning partners are managed on the app's page in PostHog Admin.
        exclude = ("_provisioning_config", "is_provisioning_partner")

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

    def _reject_cimd_shaped_client_id(self, cleaned: dict) -> None:
        """Keep a URL-form client_id to the CIMD clients that register themselves.

        A CIMD client is identified by its metadata URL, and a metadata refresh writes that
        document's redirect URIs and auth settings onto whichever row carries the URL. An app
        given that shape by hand would take those writes from a document nobody here controls.
        """
        client_id = cleaned.get("client_id")
        if not client_id or self.instance.is_cimd_client:
            return
        if is_cimd_client_id(client_id):
            self.add_error(
                "client_id",
                "A client ID that looks like a URL is reserved for CIMD clients, which register "
                "themselves. Use the generated value, or an ID that is not a URL.",
            )

    def _reject_partner_that_cannot_sign(self, cleaned: dict) -> None:
        """Keep an edit of how the app authenticates from leaving a partner that has to sign without a key.

        The form has not applied the edit to the instance yet, so the instance is the app before it.
        """
        before = self.instance
        if before.pk is None:
            return
        if before.edit_would_break_provisioning_signature(
            client_type=cleaned.get("client_type", before.client_type),
            jwks_uri=cleaned.get("jwks_uri", before.jwks_uri),
        ):
            self.add_error(
                "client_type",
                "This provisioning partner can create accounts or pays for its customers, so it must sign its "
                "requests with a private key. Keep it a confidential client with a jwks_uri, or change its "
                "capabilities on its page in PostHog Admin first.",
            )

    def clean(self):
        cleaned = super().clean() or {}
        self._reject_cimd_shaped_client_id(cleaned)
        self._reject_partner_that_cannot_sign(cleaned)
        return cleaned


class ProvisioningCapabilityFilter(admin.SimpleListFilter):
    """Filter partners by a granted capability.

    The capabilities live inside a JSONB column, so the per-column checkbox filters the admin
    used to offer are gone. One filter over every capability replaces them, and it stays in
    step with the schema rather than needing an entry added per capability.
    """

    title = "provisioning capability"
    parameter_name = "provisioning_capability"

    def lookups(self, request, model_admin):
        return [(name, name.replace("_", " ")) for name in PROVISIONING_CAPABILITIES]

    def queryset(self, request, queryset):
        capability = self.value()
        if not capability or capability not in PROVISIONING_CAPABILITIES:
            return queryset
        # nosemgrep: orm-field-injection -- capability is allowlisted above, and the JSONField prefix keeps any __ as a JSON key lookup
        return queryset.filter(**{f"_provisioning_config__{capability}": True})


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
    list_display_links = ("name", "client_id")
    list_filter = (
        "authorization_grant_type",
        "is_verified",
        "is_dcr_client",
        "is_cimd_client",
        "is_first_party",
        "supports_step_up",
        "can_manage_ema_issuer",
        "auth_brand",
        "is_provisioning_partner",
        ProvisioningCapabilityFilter,
    )
    search_fields = ("name", "client_id", "user__email", "organization__name")
    autocomplete_fields = ("user", "organization")
    ordering = ("name",)
    actions = ("revoke_all_sessions", "regenerate_client_secret")

    @admin.action(description="Generate a new client secret")
    def regenerate_client_secret(self, request, queryset):
        # client_secret is only editable on the add form (it is hashed on save and can never be
        # read back), so this is the only way to give an existing app a secret or rotate one.
        for application in queryset:
            # Gated on the auth method rather than the client type: a private_key_jwt client is
            # confidential too, but authenticates by signed assertion, so a secret minted for it
            # would never be checked and would look like working credentials to an operator.
            if not application.uses_client_secret_auth:
                self.message_user(
                    request,
                    f"{application.name}: skipped, its token_endpoint_auth_method is "
                    f"'{application.token_endpoint_auth_method.value}', which uses no client secret.",
                    level=messages.ERROR,
                )
                continue

            plaintext_secret = generate_client_secret()
            application.client_secret = plaintext_secret
            # ClientSecretField.pre_save hashes it, so plaintext_secret is the only copy that
            # will ever exist.
            application.save(update_fields=["client_secret"])
            self.message_user(
                request,
                f"{application.name} ({application.client_id}) new client secret, save it now, "
                f"it cannot be shown again: {plaintext_secret}",
                level=messages.WARNING,
            )

    @admin.action(description="Revoke all sessions (force re-auth under current scopes)")
    def revoke_all_sessions(self, request, queryset):
        # The confirm step lives in PostHog Admin, which previews the applications and asks for a reason.
        if queryset.count() > RevokeSessionsForm.MAX_APPLICATIONS:
            self.message_user(
                request,
                f"Pick {RevokeSessionsForm.MAX_APPLICATIONS} applications or fewer to revoke their sessions.",
                level=messages.ERROR,
            )
            return None
        query = urlencode(
            [("application", str(application_id)) for application_id in queryset.values_list("id", flat=True)]
        )
        return HttpResponseRedirect(
            f"{reverse('admin_console_tool_operation', args=['oauth-sessions', 'revoke'])}?{query}"
        )

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
            readonly = ["id", "client_id", "is_dcr_client", "is_cimd_client", "provisioning"]
            if obj.is_cimd_client:
                # A CIMD client's scope ceiling is derived from its own metadata document and
                # re-applied on every refresh, so a manual edit here would be silently reverted.
                # The unprivileged/hidden allow-list is the only ceiling that applies to CIMD
                # apps. To cut off an abusive partner, block it on its page in PostHog Admin: deleting
                # the app only revokes its tokens, and a self-registered partner can register again.
                readonly.append("scopes")
                # Model validation also rejects optional_scopes on CIMD apps: a split would
                # let the partner grow the locked required set via metadata refresh.
                readonly.append("optional_scopes")
                # Also re-derived from the metadata document on each refresh.
                readonly.append("jwks_uri")
            return tuple(readonly)
        else:
            return ("id", "is_dcr_client", "is_cimd_client")

    def get_fieldsets(self, request, obj=None):
        if obj:
            return (
                (None, {"fields": ("id", "name", "client_id", "client_type", "auth_brand", "logo_uri")}),
                (
                    "Authorization",
                    {
                        "fields": (
                            "authorization_grant_type",
                            "jwks_uri",
                            "redirect_uris",
                            "algorithm",
                            "scopes",
                            "optional_scopes",
                        )
                    },
                ),
                ("Ownership", {"fields": ("user", "organization")}),
                (
                    "Status",
                    {
                        "fields": (
                            "is_verified",
                            "is_first_party",
                            "supports_step_up",
                            "can_manage_ema_issuer",
                            "is_dcr_client",
                            "is_cimd_client",
                        )
                    },
                ),
                ("Provisioning", {"fields": ("provisioning",)}),
                (
                    "CIMD",
                    {
                        "classes": ("collapse",),
                        "fields": ("cimd_metadata_last_fetched",),
                    },
                ),
            )
        else:
            return (
                (None, {"fields": ("name", "client_id", "client_secret", "client_type", "auth_brand", "logo_uri")}),
                (
                    "Authorization",
                    {
                        "fields": (
                            "authorization_grant_type",
                            "jwks_uri",
                            "redirect_uris",
                            "algorithm",
                            "scopes",
                            "optional_scopes",
                        )
                    },
                ),
                ("Ownership", {"fields": ("user", "organization")}),
                ("Status", {"fields": ("is_verified", "is_first_party", "supports_step_up", "can_manage_ema_issuer")}),
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

    @admin.display(description="Provisioning partner")
    def provisioning(self, obj: OAuthApplication) -> str:
        return MovedToConsole.action(
            "oauth-application", obj, "provisioning", "Accept or block the partner, capabilities and rate limits"
        )

    @admin.display(description="CIMD URL")
    def cimd_url(self, obj: OAuthApplication):
        if not obj.is_cimd_client:
            return "–"
        return format_html(
            '<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>',
            obj.client_id,
            obj.client_id,
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
