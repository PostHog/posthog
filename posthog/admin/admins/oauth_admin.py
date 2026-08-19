from __future__ import annotations

import base64
import hashlib
from urllib.parse import urlencode

from django import forms
from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.template.response import TemplateResponse
from django.utils.html import format_html

from oauth2_provider.generators import generate_client_id, generate_client_secret
from oauth2_provider.models import AbstractApplication

from posthog.models.oauth import OAuthApplication, revoke_application_sessions
from posthog.models.oauth_provisioning import UNLIMITED_OVERRIDE, ProvisioningConfig

# The provisioning config is one JSONB column, but an operator should still get the checkboxes
# they had when it was a column each: a raw JSON textarea turns a mistyped capability key into
# something that silently reads back as "not granted" while looking granted on screen.
# Derived from the pydantic schema so a capability added there shows up here automatically.
PROVISIONING_FIELD_PREFIX = "provisioning_"
PROVISIONING_RATE_LIMIT_PREFIX = "provisioning_rate_limit_"


def _provisioning_form_fields() -> dict[str, forms.Field]:
    """One form field per capability. Rate-limit override fields are generated
    per request in ``get_form`` from the endpoint registry."""
    fields: dict[str, forms.Field] = {}
    for name, info in ProvisioningConfig.model_fields.items():
        if name == "rate_limits":
            continue
        fields[f"{PROVISIONING_FIELD_PREFIX}{name}"] = forms.BooleanField(
            required=False, label=name.replace("_", " "), help_text=info.description or ""
        )
    return fields


def _rate_limit_endpoints() -> list[str]:
    """Every declared rate-limit endpoint, so a new @rate_limited declaration
    grows an override field here with no admin change."""
    # Deferred: budgets register when the provisioning view modules import, and this
    # admin module loads at django.setup() in every process, where pulling the ee
    # views in eagerly would bloat startup.
    from ee.api.agentic_provisioning import views  # noqa: F401, PLC0415
    from ee.api.agentic_provisioning.ratelimits import registered_budgets  # noqa: PLC0415

    return sorted(registered_budgets())


def _rate_limit_form_fields() -> dict[str, forms.Field]:
    return {
        f"{PROVISIONING_RATE_LIMIT_PREFIX}{name}": forms.IntegerField(
            required=False,
            min_value=UNLIMITED_OVERRIDE,
            label=f"rate limit {name.replace('_', ' ')} (per hour)",
            help_text="Blank = tier-derived budget; -1 = unlimited. Outranks the tier, including BLOCKED.",
        )
        for name in _rate_limit_endpoints()
    }


PROVISIONING_FORM_FIELD_NAMES = tuple(_provisioning_form_fields())


class OAuthApplicationForm(forms.ModelForm):
    class Meta:
        model = OAuthApplication
        # The JSONB column is edited through the generated fields below, never as raw JSON.
        exclude = ("_provisioning_config",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._load_provisioning_initial()

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

    def _rate_limit_field_names(self) -> list[str]:
        return [name for name in self.fields if name.startswith(PROVISIONING_RATE_LIMIT_PREFIX)]

    def _load_provisioning_initial(self) -> None:
        config = self.instance.provisioning if self.instance.pk else ProvisioningConfig()
        for name in ProvisioningConfig.model_fields:
            if name == "rate_limits":
                continue
            self.fields[f"{PROVISIONING_FIELD_PREFIX}{name}"].initial = getattr(config, name)
        for field_name in self._rate_limit_field_names():
            endpoint = field_name.removeprefix(PROVISIONING_RATE_LIMIT_PREFIX)
            self.fields[field_name].initial = config.rate_limits.get(endpoint)

    def clean(self):
        cleaned = super().clean() or {}
        for field_name in self._rate_limit_field_names():
            # 0 is rejected rather than meaning "unlimited": that footgun is why the
            # unlimited sentinel is -1 (UNLIMITED_OVERRIDE).
            if cleaned.get(field_name) == 0:
                self.add_error(field_name, "Enter a positive hourly limit, -1 for unlimited, or leave blank.")
        return cleaned

    def save(self, commit: bool = True):
        instance = super().save(commit=False)

        capabilities = {
            name: self.cleaned_data[f"{PROVISIONING_FIELD_PREFIX}{name}"]
            for name in ProvisioningConfig.model_fields
            if name != "rate_limits"
        }
        rate_limits = {
            field_name.removeprefix(PROVISIONING_RATE_LIMIT_PREFIX): value
            for field_name in self._rate_limit_field_names()
            if (value := self.cleaned_data.get(field_name)) is not None
        }

        instance.provisioning = ProvisioningConfig(**capabilities, rate_limits=rate_limits)

        if commit:
            instance.save()
            self.save_m2m()
        return instance


# Declared on the class rather than added per instance, so admin's fieldset validation and
# modelform_factory can see them. Fields added in __init__ exist too late for either.
for _field_name, _form_field in _provisioning_form_fields().items():
    OAuthApplicationForm.declared_fields[_field_name] = _form_field
    OAuthApplicationForm.base_fields[_field_name] = _form_field


class ProvisioningCapabilityFilter(admin.SimpleListFilter):
    """Filter partners by a granted capability.

    The capabilities live inside a JSONB column, so the per-column checkbox filters the admin
    used to offer are gone. One filter over every capability replaces them, and it stays in
    step with the schema rather than needing an entry added per capability.
    """

    title = "provisioning capability"
    parameter_name = "provisioning_capability"

    def lookups(self, request, model_admin):
        return [(name, name.replace("_", " ")) for name in ProvisioningConfig.model_fields if name != "rate_limits"]

    def queryset(self, request, queryset):
        capability = self.value()
        if not capability or capability not in ProvisioningConfig.model_fields:
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
        "auth_brand",
        "is_provisioning_partner",
        ProvisioningCapabilityFilter,
    )
    search_fields = ("name", "client_id", "cimd_metadata_url", "user__email", "organization__name")
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
                # Also re-derived from the metadata document on each refresh.
                readonly.append("jwks_uri")
            return tuple(readonly)
        else:
            return ("id", "is_dcr_client", "is_cimd_client")

    def get_fieldsets(self, request, obj=None):
        if obj:
            provisioning_fields = [
                "is_provisioning_partner",
                *PROVISIONING_FORM_FIELD_NAMES,
                *_rate_limit_form_fields(),
            ]

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
                ("Status", {"fields": ("is_verified", "is_first_party", "is_dcr_client", "is_cimd_client")}),
                (
                    "Provisioning",
                    {
                        "description": (
                            "Provisioning settings for partners. Every capability is off unless you "
                            "grant it here, including for a partner that registered itself. How a partner "
                            "authenticates follows from the fields above: a confidential client with a "
                            "jwks_uri signs an assertion with its own key (preferred), a confidential client "
                            "without one presents a client secret, and a public client is identified by "
                            "client_id and relies on PKCE. The GitHub grant endpoints additionally require a "
                            "confidential client. Use the 'Generate a new client secret' action to issue a "
                            "secret. Leave a rate limit blank to use the endpoint's default."
                        ),
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
                ("Status", {"fields": ("is_verified", "is_first_party")}),
            )

    def get_form(self, request, obj=None, change=False, **kwargs):
        # The rate-limit override fields follow the endpoint registry, so they are
        # declared on a per-request subclass: modelform_factory validates the
        # fieldset names against the form class, which therefore has to carry them
        # before super() runs.
        kwargs["form"] = type("OAuthApplicationAdminForm", (self.form,), dict(_rate_limit_form_fields()))
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
