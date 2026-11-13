from typing import cast

from django import forms
from django.contrib import messages
from django.contrib.admin.models import CHANGE, LogEntry
from django.db.models import Model
from django.http import HttpRequest, HttpResponse

from posthog.admin.console.moved import MovedRecord
from posthog.admin.console.panels import MAX_FACTS_PER_PANEL, Fact, Operation, Panel
from posthog.admin.console.registry import console
from posthog.admin.console.team_panels import DEV_EXPERIENCE
from posthog.api.personal_api_key import PersonalAPIKeySerializer
from posthog.api.project_secret_api_key import revoke_exposed_project_secret_api_key
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.tasks.email import send_personal_api_key_exposed


class ExposedKeyForm(forms.Form):
    key = forms.ChoiceField(label="Key")
    exposed_at = forms.CharField(
        label="Where the key was exposed",
        required=False,
        help_text="Optional, for example a URL. The notification email includes it.",
    )
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), help_text="Goes into the audit log.")


def _exposed_key_form(keys: list[PersonalAPIKey] | list[ProjectSecretAPIKey]) -> type[forms.Form]:
    # The keys differ per record, so each record page builds its own form class with them as the choices.
    choices = [(key.pk, f"{key.label} ({key.mask_value})") for key in keys]
    return type("ExposedKeyForm", (ExposedKeyForm,), {"key": forms.ChoiceField(label="Key", choices=choices)})


def _more_info(form: forms.Form) -> str:
    exposed_at = form.cleaned_data["exposed_at"].strip()
    return f"This key was detected at {exposed_at}." if exposed_at else ""


def _log_change(request: HttpRequest, key: Model, message: str) -> None:
    # The same entry ModelAdmin.log_change writes, so the history on the key's Django admin page stays complete.
    LogEntry.objects.log_actions(
        user_id=cast(User, request.user).pk,
        queryset=[key],
        action_flag=CHANGE,
        change_message=message,
        single_object=True,
    )


def _key_facts(keys: list[PersonalAPIKey] | list[ProjectSecretAPIKey], total: int, empty: str) -> list[Fact]:
    if not keys:
        return [Fact(label="Keys", value=empty)]
    shown = keys if total <= MAX_FACTS_PER_PANEL else keys[: MAX_FACTS_PER_PANEL - 1]
    facts = [Fact(label=key.label or "No label", value=key.mask_value or "", mono=True) for key in shown]
    if len(shown) < total:
        facts.append(Fact(label="More", value=f"{total - len(shown)} more keys. Pick any of them when you roll one."))
    return facts


def roll_personal_api_key(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert isinstance(obj, User) and form is not None
    key = PersonalAPIKey.objects.filter(user=obj, pk=form.cleaned_data["key"]).first()
    if key is None:
        messages.error(request, "This key no longer exists.")
        return HttpResponse(status=404)
    old_mask_value = key.mask_value
    PersonalAPIKeySerializer(instance=key).roll(key)
    send_personal_api_key_exposed(key.user_id, key.id, old_mask_value, _more_info(form))
    _log_change(request, key, "Rolled key.")
    messages.success(request, "Personal API key rolled and user notified.")
    return None


@console.register_panel
class PersonalApiKeysPanel(Panel):
    record = "user"
    key = "personal-api-keys"
    title = "Personal API keys"
    owner = DEV_EXPERIENCE
    order = 40
    danger = True

    def _keys(self, user: User) -> list[PersonalAPIKey]:
        return list(PersonalAPIKey.objects.filter(user=user).order_by("-created_at"))

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, User)
        keys = self._keys(obj)
        return _key_facts(keys, len(keys), "This user has no personal API keys.")

    def operations(self, obj: Model) -> list[Operation]:
        assert isinstance(obj, User)
        keys = self._keys(obj)
        if not keys:
            return []
        return [
            Operation(
                key="roll",
                label="Roll an exposed key",
                handler=roll_personal_api_key,
                danger=True,
                description=(
                    "The key gets a new value, so whatever uses the old one stops working. "
                    "The user gets an email that the key was exposed."
                ),
                form_class=_exposed_key_form(keys),
                undo_hint="This cannot be undone. The user copies the new value in their personal API key settings.",
            )
        ]


def revoke_project_secret_api_key(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert isinstance(obj, Team) and form is not None
    key = ProjectSecretAPIKey.objects.filter(team=obj, pk=form.cleaned_data["key"]).first()
    if key is None:
        messages.error(request, "This key no longer exists.")
        return HttpResponse(status=404)
    was_legacy_mirror = revoke_exposed_project_secret_api_key(key, _more_info(form))
    # A key that mirrored the team's legacy secret token is deleted, so the Django admin history has no row to hang
    # the entry on. The audit log still has the operation.
    if not was_legacy_mirror:
        _log_change(request, key, "Rolled key.")
    messages.success(request, "Project secret API key revoked and project admins notified.")
    return None


@console.register_panel
class ProjectSecretApiKeysPanel(Panel):
    record = "team"
    key = "secret-api-keys"
    title = "Project secret API keys"
    owner = DEV_EXPERIENCE
    order = 40
    danger = True

    def _keys(self, team: Team) -> list[ProjectSecretAPIKey]:
        return list(ProjectSecretAPIKey.objects.filter(team=team).order_by("-created_at"))

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, Team)
        keys = self._keys(obj)
        return _key_facts(keys, len(keys), "This team has no project secret API keys.")

    def operations(self, obj: Model) -> list[Operation]:
        assert isinstance(obj, Team)
        keys = self._keys(obj)
        if not keys:
            return []
        return [
            Operation(
                key="revoke",
                label="Revoke an exposed key",
                handler=revoke_project_secret_api_key,
                danger=True,
                description=(
                    "The key gets a new value, so whatever uses the old one stops working, and the project's "
                    "admins get an email. A key that mirrors the team's legacy secret token is deleted instead, "
                    "and the email asks the admins to rotate that token."
                ),
                form_class=_exposed_key_form(keys),
                undo_hint="This cannot be undone. The project's admins create or roll a key in project settings.",
            )
        ]


class MovedKeyOwners:
    """API keys have no console page of their own. An old roll URL leads to the page of the user or team that owns the key."""

    @staticmethod
    def personal_api_key(pk: str) -> MovedRecord | None:
        # nosemgrep: idor-lookup-without-user -- staff-only redirect behind admin_view; it finds the key's owner to link there
        user_id = PersonalAPIKey.objects.filter(pk=pk).values_list("user_id", flat=True).first()
        return MovedRecord(pk=user_id) if user_id is not None else None

    @staticmethod
    def project_secret_api_key(pk: str) -> MovedRecord | None:
        # nosemgrep: idor-lookup-without-team -- staff-only redirect behind admin_view; it finds the key's team to link there
        team_id = ProjectSecretAPIKey.objects.filter(pk=pk).values_list("team_id", flat=True).first()
        return MovedRecord(pk=team_id) if team_id is not None else None


console.register_moved_action(
    old_path="admin/posthog/personalapikey/<str:pk>/roll/",
    record="user",
    target="#panel-personal-api-keys",
    resolver=MovedKeyOwners.personal_api_key,
)
console.register_moved_action(
    old_path="admin/posthog/projectsecretapikey/<str:pk>/roll/",
    record="team",
    target="#panel-secret-api-keys",
    resolver=MovedKeyOwners.project_secret_api_key,
)
