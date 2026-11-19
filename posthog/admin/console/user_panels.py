import datetime
import dataclasses
from collections.abc import Iterable
from typing import cast

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.models import CHANGE, DELETION, LogEntry
from django.db import transaction
from django.db.models import CASCADE, PROTECT, RESTRICT, Model
from django.db.models.deletion import get_candidate_relations_to_delete
from django.db.models.fields.related import ForeignObject
from django.db.models.fields.reverse_related import ForeignObjectRel
from django.db.models.options import Options
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import reverse

from django_otp.plugins.otp_totp.models import TOTPDevice

from posthog.admin.console.panels import MAX_FACTS_PER_PANEL, Fact, Operation, Panel, ReasonForm, Tone
from posthog.admin.console.records import RECORD_TYPES
from posthog.admin.console.registry import console
from posthog.admin.console.team_panels import DEV_EXPERIENCE
from posthog.admin.console.tools import Cell, Notice, Page, Row, Table
from posthog.api.authentication import password_reset_token_generator
from posthog.api.email_verification import email_verification_code_verifier
from posthog.api.two_factor_reset import TwoFactorResetVerifier
from posthog.dataclasses import frozen
from posthog.helpers.impersonation import get_impersonated_user, is_impersonated
from posthog.models.activity_logging.activity_log import (
    ActivityContextBase,
    Detail,
    LogActivityEntry,
    bulk_log_activity,
)
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.models.webauthn_credential import WebauthnCredential
from posthog.session.activity import revoke_other_sessions
from posthog.tasks.email import send_password_reset, send_two_factor_reset_email

# Every relation is counted with its own capped query, so this bounds how much of a table the
# preview reads. The exact figure past the cap doesn't change the operator's decision.
DELETION_SUMMARY_COUNT_CAP = 100


def _when(value: datetime.datetime | None) -> str:
    return value.strftime("%b %-d, %Y") if value else "Never"


def _log_change(request: HttpRequest, user: User, message: str) -> None:
    # The same entry ModelAdmin.log_change writes, so the history on the Django admin page stays complete.
    LogEntry.objects.log_actions(
        user_id=cast(User, request.user).pk,
        queryset=[user],
        action_flag=CHANGE,
        change_message=message,
        single_object=True,
    )


@console.register_panel
class UserOverviewPanel(Panel):
    record = "user"
    key = "overview"
    title = "Overview"
    owner = DEV_EXPERIENCE
    order = 10

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, User)
        facts = [
            Fact(label="Status", value="Active", tone=Tone.SUCCESS)
            if obj.is_active
            else Fact(label="Status", value="Deactivated", tone=Tone.DESTRUCTIVE),
            Fact(label="Joined", value=_when(obj.date_joined)),
            Fact(label="Last login", value=_when(obj.last_login)),
        ]
        if obj.current_organization is not None:
            facts.append(
                Fact(
                    label="Current organization",
                    value=obj.current_organization.name,
                    href=RECORD_TYPES["organization"].url(obj.current_organization),
                )
            )
        if obj.current_team is not None:
            facts.append(
                Fact(label="Current team", value=obj.current_team.name, href=RECORD_TYPES["team"].url(obj.current_team))
            )
        if obj.is_staff:
            facts.append(Fact(label="Staff", value="Yes", tone=Tone.INFO))
        if obj.allow_impersonation is False:
            facts.append(Fact(label="Log in as user", value="Turned off by the user"))
        return facts


@console.register_panel
class UserOrganizationsPanel(Panel):
    record = "user"
    key = "organizations"
    title = "Organizations"
    owner = DEV_EXPERIENCE
    order = 20

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, User)
        memberships = list(
            OrganizationMembership.objects.filter(user=obj)
            .select_related("organization")
            .order_by("joined_at")[: MAX_FACTS_PER_PANEL + 1]
        )
        if not memberships:
            return [Fact(label="Organizations", value="This user is in no organization.")]
        shown = memberships if len(memberships) <= MAX_FACTS_PER_PANEL else memberships[: MAX_FACTS_PER_PANEL - 1]
        organization_record = RECORD_TYPES["organization"]
        facts = [
            Fact(
                label=membership.organization.name,
                value=OrganizationMembership.Level(membership.level).label.capitalize(),
                href=organization_record.url(membership.organization),
            )
            for membership in shown
        ]
        if len(shown) < len(memberships):
            hidden = OrganizationMembership.objects.filter(user=obj).count() - len(shown)
            facts.append(
                Fact(label="More", value=f"{hidden} more organizations. The raw record in Django admin lists all.")
            )
        return facts


class TwoFactor:
    @staticmethod
    def methods(user: User) -> list[str]:
        methods = []
        if TOTPDevice.objects.filter(user=user, confirmed=True).exists():
            methods.append("Authenticator app")
        if user.passkeys_enabled_for_2fa and WebauthnCredential.objects.filter(user=user, verified=True).exists():
            methods.append("Passkeys")
        return methods


def send_verification_email(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert isinstance(obj, User)
    try:
        email_verification_code_verifier.send_code(obj)
    except Exception as error:
        messages.error(request, f"Failed to send verification email: {error}")
        return HttpResponse(status=500)
    _log_change(request, obj, "Sent verification email.")
    messages.success(request, f"Verification email sent to {obj.email}")
    return None


def send_password_reset_email(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert isinstance(obj, User)
    try:
        # The timestamp is part of the token hash (PasswordResetTokenGenerator._make_hash_value), so it is saved
        # before the token is made.
        obj.requested_password_reset_at = datetime.datetime.now(datetime.UTC)
        obj.save(update_fields=["requested_password_reset_at"])
        token = password_reset_token_generator.make_token(obj)
        send_password_reset.delay(obj.pk, token)
    except Exception as error:
        messages.error(request, f"Failed to send password reset email: {error}")
        return HttpResponse(status=500)
    _log_change(request, obj, "Sent password reset email.")
    messages.success(request, f"Password reset email sent to {obj.email}")
    return None


def send_two_factor_reset(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert isinstance(obj, User)
    try:
        obj.requested_2fa_reset_at = datetime.datetime.now(datetime.UTC)
        obj.save(update_fields=["requested_2fa_reset_at"])
        token = TwoFactorResetVerifier.create_token(obj)
        send_two_factor_reset_email.delay(obj.pk, token)
    except Exception as error:
        messages.error(request, f"Failed to send 2FA reset email: {error}")
        return HttpResponse(status=500)
    _log_change(request, obj, "Sent 2FA reset email.")
    messages.success(request, f"2FA reset email sent to {obj.email}")
    return None


def revoke_sessions(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert isinstance(obj, User)
    try:
        revoked = revoke_other_sessions(obj, keep_session_key=None)
    except Exception as error:
        messages.error(request, f"Failed to revoke sessions: {error}")
        return HttpResponse(status=500)
    _log_change(request, obj, f"Revoked {revoked} web session(s).")
    messages.success(request, f"Revoked {revoked} session(s)")
    return None


@console.register_panel
class UserSignInPanel(Panel):
    record = "user"
    key = "sign-in"
    title = "Sign-in"
    owner = DEV_EXPERIENCE
    order = 30

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, User)
        two_factor = TwoFactor.methods(obj)
        facts = [
            Fact(label="Email", value="Verified", tone=Tone.SUCCESS)
            if obj.is_email_verified
            else Fact(label="Email", value="Not verified", tone=Tone.WARNING),
            Fact(label="Two-factor", value=", ".join(two_factor) if two_factor else "Not set up"),
            Fact(label="Password", value="Set" if obj.has_usable_password() else "Not set"),
        ]
        if obj.pending_email:
            facts.insert(1, Fact(label="Changing email to", value=obj.pending_email))
        return facts

    def operations(self, obj: Model) -> list[Operation]:
        assert isinstance(obj, User)
        operations = []
        if not obj.is_email_verified:
            operations.append(
                Operation(
                    key="send-verification",
                    label="Send verification email",
                    handler=send_verification_email,
                    description="The user gets an email with a code that verifies their address.",
                )
            )
        operations.append(
            Operation(
                key="send-password-reset",
                label="Send password reset email",
                handler=send_password_reset_email,
                description="The user gets an email with a link to set a new password.",
            )
        )
        if TwoFactor.methods(obj):
            operations.append(
                Operation(
                    key="send-2fa-reset",
                    label="Send 2FA reset email",
                    handler=send_two_factor_reset,
                    danger=True,
                    description=(
                        "The user gets an email with a link that turns off two-factor authentication. Anyone "
                        "who can read their inbox can then sign in with the password alone."
                    ),
                    form_class=ReasonForm,
                    undo_hint="An email cannot be recalled. Sending another one makes the earlier link stop working.",
                )
            )
        operations.append(
            Operation(
                key="revoke-sessions",
                label="Revoke all web sessions",
                handler=revoke_sessions,
                danger=True,
                description="Signs the user out on every device. API keys and OAuth apps keep working.",
                form_class=ReasonForm,
                undo_hint="This cannot be undone. The user signs in again to get a new session.",
            )
        )
        return operations


@frozen
class CascadeSummary:
    counts: tuple[tuple[str, str], ...]
    perms_needed: frozenset[str]
    protected: tuple[str, ...]


class UserCascade:
    """What deleting a user takes with it, as a capped count per relation.

    Django's NestedObjects collector loads every cascading row, and recorded views alone reach into the millions on a
    long-lived account, so collecting them times out before anything is deleted.
    """

    def __init__(self, request: HttpRequest, site: admin.AdminSite = admin.site) -> None:
        self.request = request
        self.site = site

    def summarize(self, user: User) -> CascadeSummary:
        counts: list[tuple[str, int]] = []
        perms_needed: set[str] = set()
        protected: list[str] = []
        # The same relations Django's own collector walks. `User._meta.related_objects` drops the
        # ones declared with `related_name="+"`, which still cascade and include some of the
        # highest-volume tables, so the summary would understate what gets deleted.
        relations = cast(
            Iterable[ForeignObjectRel], get_candidate_relations_to_delete(cast("Options[Model]", User._meta))
        )
        for related in relations:
            field = related.field
            related_model = field.model
            if related_model._meta.auto_created:
                continue
            on_delete = field.remote_field.on_delete
            if on_delete in (PROTECT, RESTRICT):
                protected.extend(self._protected_rows(field, user))
                continue
            if on_delete is not CASCADE:
                continue
            count = (
                # nosemgrep: orm-field-injection -- field.name comes from User._meta, never a request
                related_model._base_manager.filter(**{field.name: user})
                .order_by()[: DELETION_SUMMARY_COUNT_CAP + 1]
                .count()
            )
            if count:
                counts.append((str(related_model._meta.verbose_name_plural), count))
                if not self._may_delete_related(related_model):
                    perms_needed.add(str(related_model._meta.verbose_name))

        counts.sort(key=lambda entry: (-entry[1], entry[0]))
        summary = [(str(User._meta.verbose_name_plural), "1")]
        for label, count in counts:
            summary.append(
                (label, f"{DELETION_SUMMARY_COUNT_CAP}+" if count > DELETION_SUMMARY_COUNT_CAP else str(count))
            )
        return CascadeSummary(counts=tuple(summary), perms_needed=frozenset(perms_needed), protected=tuple(protected))

    def _may_delete_related(self, related_model: type[Model]) -> bool:
        # Django refuses a delete that cascades through a model whose admin refuses deletion, such as AI assistant
        # conversations. A model with no admin has nobody to ask.
        related_admin = self.site._registry.get(related_model)
        if related_admin is None:
            return True
        # Django asks per row. Asking once per model is what keeps this bounded, so an admin that
        # refuses only some of its rows is answered by whatever it says for the model as a whole.
        return related_admin.has_delete_permission(self.request)

    def _protected_rows(self, field: ForeignObject, user: User) -> list[str]:
        # Django raises for PROTECT and RESTRICT part of the way through a delete, so they refuse it before it starts.
        # RESTRICT counts even when the row also cascades away: a refused delete is recoverable, a half-done one is not.
        related_model = field.model
        rows = list(
            # nosemgrep: orm-field-injection -- field.name comes from User._meta, never a request
            related_model._base_manager.filter(**{field.name: user}).order_by()[: DELETION_SUMMARY_COUNT_CAP + 1]
        )
        labels = [f"{related_model._meta.verbose_name}: {row}" for row in rows[:DELETION_SUMMARY_COUNT_CAP]]
        if len(rows) > DELETION_SUMMARY_COUNT_CAP:
            labels.append(f"More {related_model._meta.verbose_name_plural}, not listed here")
        return labels


def is_acting_as(request: HttpRequest, user: User) -> bool:
    # Deleting the account you act as ends the session mid-request and cascades away the actor of its own log entries.
    if user.pk == request.user.pk:
        return True
    # On `/admin/` paths `AdminImpersonationMiddleware` swaps `request.user` back to the staff
    # operator, so the impersonated account passes the check above while its session is the one
    # the delete would break. `get_impersonated_user` reads the session instead of `request.user`.
    impersonated = get_impersonated_user(request)
    return impersonated is not None and user.pk == impersonated.pk


def deletion_refusal(request: HttpRequest, user: User, summary: CascadeSummary) -> str | None:
    """Why this user cannot be deleted from here, or None when nothing stands in the way."""
    if is_acting_as(request, user):
        return "You cannot delete the account you are signed in as or logged in as."
    if summary.protected:
        return f"Other rows protect this account, so it cannot be deleted: {'; '.join(summary.protected)}"
    if summary.perms_needed:
        return (
            "Deleting this account would also delete rows that Django admin does not let staff delete: "
            f"{', '.join(sorted(summary.perms_needed))}."
        )
    return None


@dataclasses.dataclass(frozen=True)
class UserDeletionActivityContext(ActivityContextBase):
    reason: str
    # The item_id of the log entry points at a row that no longer exists, so the address the
    # account was deleted under is the only thing that identifies it afterwards.
    email: str


class DeleteUserForm(forms.Form):
    reason = forms.CharField(
        max_length=400,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Goes into the activity log of every organization the user is in, and the audit log.",
    )


def preview_user_deletion(request: HttpRequest, obj: Model, form: forms.Form) -> Page:
    assert isinstance(obj, User)
    summary = UserCascade(request).summarize(obj)
    refusal = deletion_refusal(request, obj, summary)
    if refusal is not None:
        form.add_error(None, refusal)
        return Page(blocks=())
    return Page(
        blocks=(
            Notice(
                text=(
                    f"Deleting {obj.email} removes their account, their personal API keys, their two-factor "
                    "devices, and their membership of every organization they belong to. Insights, dashboards, "
                    "and anything else they created stays, with no creator on it."
                )
            ),
            Notice(
                text=(
                    "If the account is only in the way of a new one, changing its email address is usually the "
                    "better fix."
                )
            ),
            Table(
                columns=("Deleted with the account", "Rows"),
                rows=tuple(
                    Row(cells=(Cell(text=label), Cell(text=count, mono=True))) for label, count in summary.counts
                ),
            ),
            Notice(
                text=(
                    f"Counts stop at {DELETION_SUMMARY_COUNT_CAP}+, so a big account doesn't slow this page down. "
                    "Only rows attached directly to the account are counted. Rows that belong to those go too."
                )
            ),
        )
    )


def delete_user(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert isinstance(obj, User) and form is not None
    reason = form.cleaned_data["reason"].strip()
    refusal = deletion_refusal(request, obj, UserCascade(request).summarize(obj))
    if refusal is not None:
        messages.error(request, refusal)
        return HttpResponse(status=409)

    # The cascade takes the memberships that scope the log entries, and the delete blanks the primary key.
    organization_ids = list(obj.organization_memberships.values_list("organization_id", flat=True))
    deleted_user_id = obj.pk
    name = f"{obj.first_name} {obj.last_name}".strip() or obj.email
    email = obj.email
    with transaction.atomic():
        # An account in no organization has nowhere to scope an ActivityLog row, so the admin log takes the reason.
        LogEntry.objects.log_actions(
            user_id=cast(User, request.user).pk,
            queryset=[obj],
            action_flag=DELETION,
            change_message=f"Reason: {reason}",
        )
        obj.delete()
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
                    user=cast(User, request.user),
                    item_id=deleted_user_id,
                    scope="User",
                    activity="deleted",
                    detail=detail,
                    was_impersonated=is_impersonated(request),
                )
                for organization_id in organization_ids
            ]
        )
    messages.success(request, f"Deleted the user {email}.")
    return HttpResponseRedirect(reverse("admin_console_home"))


@console.register_panel
class UserDeletionPanel(Panel):
    record = "user"
    key = "deletion"
    title = "Deletion"
    owner = DEV_EXPERIENCE
    operation_keys = frozenset({"delete"})
    order = 10
    danger = True

    def operations(self, obj: Model) -> list[Operation]:
        return [
            Operation(
                key="delete",
                label="Delete user",
                handler=delete_user,
                preview=preview_user_deletion,
                danger=True,
                description=(
                    "Removes the account, its personal API keys, two-factor devices and organization memberships. "
                    "You see what is deleted with it before anything changes."
                ),
                form_class=DeleteUserForm,
                undo_hint="This cannot be undone.",
            )
        ]


console.register_moved_action(old_path="admin/posthog/user/<int:pk>/delete/", record="user", target="deletion/delete/")
# Django's set-password form, which PostHog turns off. The Reset password button on the Django admin user page
# still links to it, and staff email a reset link from the Sign-in panel instead.
console.register_moved_action(old_path="admin/posthog/user/<int:pk>/password/", record="user", target="#panel-sign-in")
