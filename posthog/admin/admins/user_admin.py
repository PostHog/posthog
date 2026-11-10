from typing import Any

from django.contrib import admin
from django.contrib.admin.views.main import ChangeList
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import (
    ReadOnlyPasswordHashWidget as DjangoReadOnlyPasswordHashWidget,
    UserChangeForm as DjangoUserChangeForm,
)
from django.contrib.auth.hashers import UNUSABLE_PASSWORD_PREFIX, identify_hasher
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.html import format_html
from django.utils.http import urlencode
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from django_otp.plugins.otp_totp.models import TOTPDevice

from posthog.admin.console.moved import MovedToConsole
from posthog.admin.inlines.organization_member_inline import OrganizationMemberForUserInline
from posthog.admin.inlines.personal_api_key_inline import PersonalAPIKeyInline
from posthog.admin.inlines.scim_provisioned_user_inline import SCIMProvisionedUserInline
from posthog.admin.inlines.totp_device_inline import TOTPDeviceInline
from posthog.admin.inlines.user_social_auth_inline import UserSocialAuthInline
from posthog.helpers.email_utils import EmailNormalizer
from posthog.models import User
from posthog.models.webauthn_credential import WebauthnCredential

# Support tools (Hogdesk) link to the user search as `?q=<email>&ticket=<ticket url>`, and
# change_form.html prefills the "Log in as user" reason from it.
TICKET_PARAM = "ticket"


class UserChangeList(ChangeList):
    # Django reads unknown query params as field lookups, and a `ticket` lookup on User redirects to `?e=1`.
    def get_filters_params(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        lookup_params = super().get_filters_params(params)
        lookup_params.pop(TICKET_PARAM, None)
        return lookup_params


class ReadOnlyPasswordHashWidget(DjangoReadOnlyPasswordHashWidget):
    # Django's widget shows the first characters of the salt and hash. Show only the algorithm.
    template_name = "admin/posthog/user/read_only_password_hash.html"

    def get_context(self, name: str, value: str | None, attrs: dict[str, Any] | None) -> dict[str, Any]:
        context = super().get_context(name, value, attrs)
        context["has_password"] = False
        context["algorithm"] = None
        if value and not value.startswith(UNUSABLE_PASSWORD_PREFIX):
            context["has_password"] = True
            try:
                context["algorithm"] = identify_hasher(value).algorithm
            except ValueError:
                pass
        return context


class UserChangeForm(DjangoUserChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password"].widget = ReadOnlyPasswordHashWidget()

    def clean_is_staff(self):
        is_staff = bool(self.cleaned_data.get("is_staff", False))
        enabled_is_staff = is_staff and (not getattr(self.instance, "is_staff", False))
        if enabled_is_staff and not self.instance.email.endswith("@posthog.com"):
            raise ValidationError("Only users with a posthog.com email address may be promoted to staff.")

        return is_staff

    def clean_passkeys_enabled_for_2fa(self):
        # Mirror the API-side guard in UserSerializer.validate_passkeys_enabled_for_2fa:
        # only allow enabling if the user has a verified passkey.
        value = bool(self.cleaned_data.get("passkeys_enabled_for_2fa", False))
        if value and not WebauthnCredential.objects.filter(user=self.instance, verified=True).exists():
            raise ValidationError("Cannot enable passkeys for 2FA — this user has no verified passkey.")
        return value


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Define admin model for custom User model with no email field."""

    form = UserChangeForm
    change_password_form = None  # This view is not exposed in our subclass of UserChangeForm
    change_form_template = "admin/posthog/user/change_form.html"

    inlines = [
        OrganizationMemberForUserInline,
        PersonalAPIKeyInline,
        TOTPDeviceInline,
        UserSocialAuthInline,
        SCIMProvisionedUserInline,
    ]
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "id",
                    "distinct_id",
                    "email",
                    "password",
                    "current_organization",
                    "is_email_verified",
                    "email_verification_status",
                    "pending_email",
                    "strapi_id",
                    "revoke_sessions_link",
                    "two_factor_status",
                    "passkeys_enabled_for_2fa",
                    "allow_impersonation",
                )
            },
        ),
        (_("Personal info"), {"fields": ("first_name", "last_name")}),
        (_("Permissions"), {"fields": ("is_active", "is_staff", "groups")}),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
        ("Danger zone", {"fields": ("deletion_moved",)}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)
    list_display = (
        "id",
        "email",
        "first_name",
        "last_name",
        "current_team_link",
        "current_organization_link",
        "is_staff",
    )
    list_display_links = ("id", "email")
    list_filter = ("is_staff", "is_active", "groups")
    list_select_related = ("current_team", "current_organization")
    search_fields = ("email", "first_name", "last_name", "distinct_id")
    readonly_fields = [
        "id",
        "distinct_id",
        "email",
        "pending_email",
        "current_team",
        "current_organization",
        "is_email_verified",
        "email_verification_status",
        "revoke_sessions_link",
        "two_factor_status",
        "allow_impersonation",
        "last_login",
        "date_joined",
        "deletion_moved",
    ]
    ordering = ("email",)

    def get_changelist(self, request: HttpRequest, **kwargs: Any) -> type[ChangeList]:
        return UserChangeList

    def changelist_view(self, request: HttpRequest, extra_context: dict[str, Any] | None = None) -> HttpResponse:
        response = super().changelist_view(request, extra_context)
        ticket = request.GET.get(TICKET_PARAM)
        if ticket and isinstance(response, TemplateResponse):
            changelist = (response.context_data or {}).get("cl")
            if changelist is not None and changelist.result_count == 1:
                user = changelist.result_list[0]
                # Exact email only, not any single result: the search matches substrings, and a near
                # miss has to stay on the list where the engineer can see it.
                if EmailNormalizer.normalize(user.email) != EmailNormalizer.normalize(changelist.query.strip()):
                    return response
                # Save and Close return to `_changelist_filters`, so `ticket` in it would bounce them back here.
                filters = request.GET.copy()
                del filters[TICKET_PARAM]
                query = urlencode({TICKET_PARAM: ticket, "_changelist_filters": filters.urlencode()})
                return HttpResponseRedirect(f"{reverse('admin:posthog_user_change', args=[user.pk])}?{query}")
        return response

    @admin.display(description="Current Team")
    def current_team_link(self, user: User):
        if not user.team:
            return "–"

        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[user.team.pk]),
            user.team.name,
        )

    @admin.display(description="Current Organization")
    def current_organization_link(self, user: User):
        if not user.organization:
            return "–"

        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_organization_change", args=[user.organization.pk]),
            user.organization.name,
        )

    @admin.display(description="Web sessions")
    def revoke_sessions_link(self, user: User):
        return MovedToConsole.action("user", user, "sign-in", "Revoking web sessions")

    @admin.display(description="Email Verification")
    def email_verification_status(self, user: User):
        if user.is_email_verified:
            return mark_safe('<p style="color: green;">✓ Verified</p>')
        return format_html(
            '<p style="color: red;">✗ Not verified</p><br>{}',
            MovedToConsole.action("user", user, "sign-in", "Sending a verification email"),
        )

    @admin.display(description="Two-factor authentication")
    def two_factor_status(self, user: User):
        has_totp = TOTPDevice.objects.filter(user=user, confirmed=True).exists()
        has_passkeys = WebauthnCredential.objects.filter(user=user, verified=True).exists()
        passkeys_enabled_for_2fa = user.passkeys_enabled_for_2fa

        status_parts = []
        if has_totp:
            status_parts.append("TOTP device")
        if has_passkeys and passkeys_enabled_for_2fa:
            status_parts.append("Passkeys (2FA enabled)")
        elif has_passkeys:
            status_parts.append("Passkeys (2FA disabled)")

        if status_parts:
            status_text = ", ".join(status_parts)
            return format_html(
                '<p style="color: green;">✓ Enabled: {}</p><br>{}',
                status_text,
                MovedToConsole.action("user", user, "sign-in", "Sending a 2FA reset email"),
            )
        else:
            return mark_safe('<p style="color: gray;">✗ Not configured</p>')

    def has_delete_permission(self, request, obj=None):
        # Deleting a user asks for a reason, checks what cascades with the account and logs the reason to every
        # organization of the user, so it runs as an operation in PostHog Admin. The old delete URL redirects there.
        return False

    @admin.display(description="Delete user")
    def deletion_moved(self, user: User):
        if not user.pk:
            return "-"
        return MovedToConsole.action("user", user, "deletion", "Deleting the user")
