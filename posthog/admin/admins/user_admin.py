import datetime

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import UserChangeForm as DjangoUserChangeForm
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from django_otp.plugins.otp_totp.models import TOTPDevice

from posthog.admin.inlines.organization_member_inline import OrganizationMemberForUserInline
from posthog.admin.inlines.personal_api_key_inline import PersonalAPIKeyInline
from posthog.admin.inlines.scim_provisioned_user_inline import SCIMProvisionedUserInline
from posthog.admin.inlines.totp_device_inline import TOTPDeviceInline
from posthog.admin.inlines.user_social_auth_inline import UserSocialAuthInline
from posthog.api.authentication import password_reset_token_generator
from posthog.api.email_verification import EmailVerifier
from posthog.api.two_factor_reset import TwoFactorResetVerifier
from posthog.models import User
from posthog.models.webauthn_credential import WebauthnCredential
from posthog.session.activity import revoke_other_sessions
from posthog.tasks.email import send_password_reset, send_two_factor_reset_email


class UserChangeForm(DjangoUserChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # This is a riff on https://github.com/django/django/blob/stable/4.1.x/django/contrib/auth/forms.py#L151-L153.
        # The difference from the Django default is that instead of a form where the _admin_ sets the new password,
        # we have a link to the password reset page which the _user_ can use themselves.
        # This way if some user needs to reset their password and there's a problem with receiving the reset link email,
        # an admin can provide that reset link manually – much better than sending a new password in plain text.
        password_reset_token = password_reset_token_generator.make_token(self.instance)
        self.fields["password"].help_text = (
            "Raw passwords are not stored, so there is no way to see this user's password, but you can send them "
            f'<a target="_blank" href="/reset/{self.instance.uuid}/{password_reset_token}">this password reset link</a> '
            "(it only works when logged out)."
        )

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
    ]
    ordering = ("email",)

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
        return format_html('<a href="{}" class="button" id="revoke_sessions_button">{}</a>', "#", "Revoke all")

    @admin.display(description="Email Verification")
    def email_verification_status(self, user: User):
        if user.is_email_verified:
            return format_html('<p style="color: green;">✓ Verified</p>')
        else:
            return format_html(
                '<p style="color: red;">✗ Not verified</p><br>'
                '<a href="#" class="button" id="send_verification_email_button">Send verification email</a>'
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
                '<p style="color: green;">✓ Enabled: {}</p><br>'
                '<a href="#" class="button" id="send_2fa_reset_email_button">Send 2FA reset email</a>',
                status_text,
            )
        else:
            return format_html('<p style="color: gray;">✗ Not configured</p>')

    def change_view(self, request, object_id, form_url="", extra_context=None):
        """Override change view to handle email verification button."""
        user = self.get_object(request, object_id)

        if request.POST.get("send_verification") == "1":
            try:
                if user and not user.is_email_verified:
                    EmailVerifier.create_token_and_send_email_verification(user)
                    self.log_change(request, user, "Sent verification email.")
                    messages.success(request, f"Verification email sent to {user.email}")
                else:
                    messages.warning(request, "User is already verified or not found.")
            except Exception as e:
                messages.error(request, f"Failed to send verification email: {str(e)}")

            # Redirect back to the change form
            return HttpResponseRedirect(reverse("admin:posthog_user_change", args=[object_id]))

        if request.POST.get("revoke_sessions") == "1":
            try:
                if user:
                    num_revoked = self.delete_user_sessions(user)
                    self.log_change(request, user, f"Revoked {num_revoked} web session(s).")
                    messages.success(request, f"Revoked {num_revoked} session(s)")
                else:
                    messages.warning(request, "User not found.")
            except Exception as e:
                messages.error(request, f"Failed to revoke sessions: {str(e)}")

            # Redirect back to the change form
            return HttpResponseRedirect(reverse("admin:posthog_user_change", args=[object_id]))

        if request.POST.get("send_password_reset") == "1":
            try:
                if user:
                    # Persist the timestamp before generating the token — it's folded into the token
                    # hash (PasswordResetTokenGenerator._make_hash_value), so saving must come first.
                    user.requested_password_reset_at = datetime.datetime.now(datetime.UTC)
                    user.save(update_fields=["requested_password_reset_at"])

                    token = password_reset_token_generator.make_token(user)
                    send_password_reset.delay(user.pk, token)

                    self.log_change(request, user, "Sent password reset email.")
                    messages.success(request, f"Password reset email sent to {user.email}")
                else:
                    messages.warning(request, "User not found.")
            except Exception as e:
                messages.error(request, f"Failed to send password reset email: {str(e)}")

            # Redirect back to the change form
            return HttpResponseRedirect(reverse("admin:posthog_user_change", args=[object_id]))

        if request.POST.get("send_2fa_reset") == "1":
            try:
                if user:
                    # Check if user has any 2FA configured
                    has_totp = TOTPDevice.objects.filter(user=user, confirmed=True).exists()
                    has_passkeys_for_2fa = (
                        WebauthnCredential.objects.filter(user=user, verified=True).exists()
                        and user.passkeys_enabled_for_2fa
                    )

                    if not has_totp and not has_passkeys_for_2fa:
                        messages.warning(request, "User does not have 2FA enabled.")
                    else:
                        # Update the requested_2fa_reset_at timestamp to invalidate any previous tokens
                        user.requested_2fa_reset_at = datetime.datetime.now(datetime.UTC)
                        user.save(update_fields=["requested_2fa_reset_at"])

                        # Generate token and send email
                        token = TwoFactorResetVerifier.create_token(user)
                        send_two_factor_reset_email.delay(user.pk, token)

                        self.log_change(request, user, "Sent 2FA reset email.")
                        messages.success(request, f"2FA reset email sent to {user.email}")
                else:
                    messages.warning(request, "User not found.")
            except Exception as e:
                messages.error(request, f"Failed to send 2FA reset email: {str(e)}")

            # Redirect back to the change form
            return HttpResponseRedirect(reverse("admin:posthog_user_change", args=[object_id]))

        return super().change_view(request, object_id, form_url, extra_context)

    def user_change_password(self, request, id, form_url=""):
        # We don't let admins set passwords directly (change_password_form is None), but Django's
        # inherited get_urls() still registers this route — which would 500 on NoneType form.
        # Redirect to the change page where the "email them a reset link" button lives instead.
        messages.info(
            request,
            'Admins can\'t set passwords directly. Use the "Reset password" button on the user page to email the user a reset link.',
        )
        return HttpResponseRedirect(reverse("admin:posthog_user_change", args=[id]))

    def delete_user_sessions(self, user):
        return revoke_other_sessions(user, keep_session_key=None)
