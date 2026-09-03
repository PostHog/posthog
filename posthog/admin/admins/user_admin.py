import datetime
import dataclasses
from collections.abc import Iterable
from typing import Any, cast

from django.contrib import admin, messages
from django.contrib.admin.models import DELETION, LogEntry
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import (
    ReadOnlyPasswordHashWidget as DjangoReadOnlyPasswordHashWidget,
    UserChangeForm as DjangoUserChangeForm,
)
from django.core.exceptions import ValidationError
from django.db.models import CASCADE, PROTECT, RESTRICT, Model
from django.db.models.deletion import get_candidate_relations_to_delete
from django.db.models.fields.related import ForeignObject
from django.db.models.fields.reverse_related import ForeignObjectRel
from django.http import HttpRequest, HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import (
    gettext,
    gettext_lazy as _,
)

from django_otp.plugins.otp_totp.models import TOTPDevice

from posthog.admin.inlines.organization_member_inline import OrganizationMemberForUserInline
from posthog.admin.inlines.personal_api_key_inline import PersonalAPIKeyInline
from posthog.admin.inlines.scim_provisioned_user_inline import SCIMProvisionedUserInline
from posthog.admin.inlines.totp_device_inline import TOTPDeviceInline
from posthog.admin.inlines.user_social_auth_inline import UserSocialAuthInline
from posthog.api.authentication import password_reset_token_generator
from posthog.api.email_verification import email_verification_code_verifier
from posthog.api.two_factor_reset import TwoFactorResetVerifier
from posthog.dataclasses import frozen
from posthog.helpers.impersonation import get_impersonated_user, is_impersonated
from posthog.models import User
from posthog.models.activity_logging.activity_log import (
    ActivityContextBase,
    Detail,
    LogActivityEntry,
    bulk_log_activity,
)
from posthog.models.webauthn_credential import WebauthnCredential
from posthog.session.activity import revoke_other_sessions
from posthog.tasks.email import send_password_reset, send_two_factor_reset_email

# Django's default widget masks salt/hash but still shows their first few characters; keep those out of the admin entirely.
_HIDDEN_SUMMARY_LABELS = {"salt", "hash", "checksum"}

# Every relation is counted with its own capped query, so this bounds how much of a table the
# confirmation page reads. The exact figure past the cap doesn't change the operator's decision.
DELETION_SUMMARY_COUNT_CAP = 100

DELETION_REASON_FIELD = "deletion_reason"


class ReadOnlyPasswordHashWidget(DjangoReadOnlyPasswordHashWidget):
    def get_context(self, name: str, value: str | None, attrs: dict[str, Any] | None) -> dict[str, Any]:
        context = super().get_context(name, value, attrs)
        hidden_labels = {gettext(label) for label in _HIDDEN_SUMMARY_LABELS}
        context["summary"] = [entry for entry in context["summary"] if entry["label"] not in hidden_labels]
        return context


@dataclasses.dataclass(frozen=True)
class UserDeletionActivityContext(ActivityContextBase):
    reason: str
    # The item_id of the log entry points at a row that no longer exists, so the address the
    # account was deleted under is the only thing that identifies it afterwards.
    email: str


@frozen
class _CascadeSummary:
    counts: dict[str, str]
    perms_needed: set[str]
    protected: list[str]


def _deletion_reason(request: HttpRequest) -> str:
    return request.POST.get(DELETION_REASON_FIELD, "").strip()


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
                    email_verification_code_verifier.send_code(user)
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

    def has_delete_permission(self, request, obj=None):
        if self._is_acting_as(request, obj):
            return False
        return super().has_delete_permission(request, obj)

    def _is_acting_as(self, request: HttpRequest, obj: User | None) -> bool:
        # Deleting the account you're acting as would end the session mid-request, and the
        # deletion's own activity log entries record the actor by foreign key, which the cascade
        # would take out from under them.
        if obj is None:
            return False
        if obj.pk == request.user.pk:
            return True
        # On `/admin/` paths `AdminImpersonationMiddleware` swaps `request.user` back to the staff
        # operator, so the impersonated account passes the check above while its session is the one
        # the delete would break. `get_impersonated_user` reads the session instead of `request.user`.
        impersonated = get_impersonated_user(request)
        return impersonated is not None and obj.pk == impersonated.pk

    def get_actions(self, request):
        actions = super().get_actions(request)
        # Bulk delete has nowhere to ask for a reason, and it would collect the cascade for every
        # selected account into one page.
        actions.pop("delete_selected", None)
        return actions

    def get_deleted_objects(self, objs, request):
        # Django builds this page with NestedObjects, which loads every row that cascades from the
        # user and renders a list item per row. Recorded views alone (session recordings, insights,
        # file tree entries) reach into the millions on a long-lived account, so both the
        # confirmation page and the POST that re-collects them time out before anything is deleted.
        # A capped count per relation answers the same question for the operator in bounded work.
        summary = self._cascade_summary(objs, request)
        return [], summary.counts, summary.perms_needed, summary.protected

    def _cascade_summary(self, objs: list[User], request: HttpRequest) -> _CascadeSummary:
        counts: list[tuple[str, int]] = []
        perms_needed: set[str] = set()
        protected: list[str] = []
        # The same relations Django's own collector walks. `User._meta.related_objects` drops the
        # ones declared with `related_name="+"`, which still cascade and include some of the
        # highest-volume tables, so the summary would understate what gets deleted.
        # Only relations that hang straight off the user are counted. Reaching the rows that
        # cascade one step further, through a relation of a relation, means joining back through
        # every parent table, which is the unbounded work this page exists to avoid. The
        # confirmation page says the counts stop at the account's own rows.
        relations = cast(Iterable[ForeignObjectRel], get_candidate_relations_to_delete(User._meta))
        for related in relations:
            field = related.field
            related_model = field.model
            # Auto-created through models (groups, permissions) are noise next to the fields that
            # already show them on the change form.
            if related_model._meta.auto_created:
                continue
            on_delete = field.remote_field.on_delete
            if on_delete in (PROTECT, RESTRICT):
                protected.extend(self._protected_rows(field, objs))
                continue
            if on_delete is not CASCADE:
                continue
            count = (
                # nosemgrep: orm-field-injection -- field.name comes from User._meta, never a request
                related_model._base_manager.filter(**{f"{field.name}__in": objs})
                .order_by()[: DELETION_SUMMARY_COUNT_CAP + 1]
                .count()
            )
            if count:
                counts.append((str(related_model._meta.verbose_name_plural), count))
                if not self._may_delete_related(request, related_model):
                    perms_needed.add(str(related_model._meta.verbose_name))

        counts.sort(key=lambda entry: (-entry[1], entry[0]))
        summary = {str(User._meta.verbose_name_plural): str(len(objs))}
        for label, count in counts:
            summary[label] = f"{DELETION_SUMMARY_COUNT_CAP}+" if count > DELETION_SUMMARY_COUNT_CAP else str(count)
        return _CascadeSummary(counts=summary, perms_needed=perms_needed, protected=protected)

    def _may_delete_related(self, request: HttpRequest, related_model: type[Model]) -> bool:
        # Django's own collector reports a model in `perms_needed` when the operator can't delete
        # it in the admin, and `ModelAdmin._delete_view` then withholds the confirm button and
        # raises PermissionDenied on the POST. Reporting nothing here would cascade through models
        # whose admin refuses deletion outright, such as the one for AI assistant conversations.
        # A model with no admin has nobody to ask, which Django also treats as nothing to check.
        related_admin = self.admin_site._registry.get(related_model)
        if related_admin is None:
            return True
        # Django asks per row. Asking once per model is what keeps this page bounded, so an admin
        # that refuses only some of its rows is answered by whatever it says for the model as a
        # whole.
        return related_admin.has_delete_permission(request)

    def _protected_rows(self, field: ForeignObject, objs: list[User]) -> list[str]:
        # Django refuses a delete that a PROTECT or RESTRICT relation blocks by raising from inside
        # the delete itself, which here would be after the confirmation page has already accepted
        # the reason. Returning the rows as `protected` instead makes the admin render its own
        # blocked page and withhold the confirm button. RESTRICT is included even though Django
        # clears it when the same row also cascades away through another relation: refusing a delete
        # that could have gone through is recoverable, and a failure part-way through a delete is not.
        related_model = field.model
        rows = list(
            # nosemgrep: orm-field-injection -- field.name comes from User._meta, never a request
            related_model._base_manager.filter(**{f"{field.name}__in": objs}).order_by()[
                : DELETION_SUMMARY_COUNT_CAP + 1
            ]
        )
        labels = [f"{related_model._meta.verbose_name}: {row}" for row in rows[:DELETION_SUMMARY_COUNT_CAP]]
        if len(rows) > DELETION_SUMMARY_COUNT_CAP:
            labels.append(f"More {related_model._meta.verbose_name_plural}, not listed here")
        return labels

    def delete_view(self, request, object_id, extra_context=None):
        if request.method == "POST" and not _deletion_reason(request):
            messages.error(request, "Add a reason for deleting this user, then confirm again.")
            return HttpResponseRedirect(request.get_full_path())
        return super().delete_view(
            request,
            object_id,
            {"deletion_summary_count_cap": DELETION_SUMMARY_COUNT_CAP, **(extra_context or {})},
        )

    def log_deletions(self, request, queryset):
        # An ActivityLog row has to be scoped to an organization or a team, so an account that has
        # already left every organization has nowhere to record one. Django's own admin log always
        # takes the reason, and it's where "recent actions" reads from.
        return LogEntry.objects.log_actions(
            user_id=request.user.pk,
            queryset=queryset,
            action_flag=DELETION,
            change_message=f"Reason: {_deletion_reason(request)}",
        )

    def delete_model(self, request, obj):
        # Read what the log entries need first: the cascade takes the memberships that scope them,
        # and the delete blanks the instance's primary key.
        reason = _deletion_reason(request)
        organization_ids = list(obj.organization_memberships.values_list("organization_id", flat=True))
        deleted_user_id = obj.pk
        name = f"{obj.first_name} {obj.last_name}".strip() or obj.email
        email = obj.email

        super().delete_model(request, obj)

        detail = Detail(
            name=name,
            type="admin_user_deletion",
            context=UserDeletionActivityContext(reason=reason, email=email),
        )
        bulk_log_activity(
            [
                LogActivityEntry(
                    organization_id=organization_id,
                    team_id=None,
                    user=request.user,
                    item_id=deleted_user_id,
                    scope="User",
                    activity="deleted",
                    detail=detail,
                    was_impersonated=is_impersonated(request),
                )
                for organization_id in organization_ids
            ]
        )

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
