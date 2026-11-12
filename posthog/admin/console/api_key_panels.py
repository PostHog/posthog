from collections import defaultdict
from datetime import datetime
from typing import cast

from django import forms
from django.contrib import messages
from django.contrib.admin.models import CHANGE, LogEntry
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Model, QuerySet
from django.http import HttpRequest, HttpResponse, QueryDict
from django.urls import reverse
from django.utils import timezone

from kombu.exceptions import OperationalError

from posthog.admin.console.moved import MovedRecord
from posthog.admin.console.panels import MAX_FACTS_PER_PANEL, Fact, Operation, Panel
from posthog.admin.console.records import RECORD_TYPES
from posthog.admin.console.registry import console
from posthog.admin.console.team_panels import DEV_EXPERIENCE
from posthog.admin.console.tools import Cell, ConsoleTool, Notice, Page, Row, Table
from posthog.api.personal_api_key import PersonalAPIKeySerializer
from posthog.api.project_secret_api_key import revoke_exposed_project_secret_api_key
from posthog.exceptions_capture import capture_exception
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey, get_organization_personal_api_keys
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.tasks.email import send_personal_api_key_exposed
from posthog.utils import pluralize


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


KEYS_LIST_LIMIT = 500
ORGANIZATION_KEYS_TOOL_KEY = "organization-personal-api-keys"


class OrganizationPersonalApiKeys:
    """The personal API keys of an organization's members that can reach the organization."""

    def __init__(self, organization: Organization) -> None:
        self.organization = organization

    def count(self) -> int:
        return get_organization_personal_api_keys(self.organization).count()

    def keys(self, limit: int | None = None) -> list[PersonalAPIKey]:
        keys = get_organization_personal_api_keys(self.organization).order_by("user__email", "-created_at")
        return list(keys[:limit] if limit is not None else keys)

    def reaching_other_organizations(self, keys: list[PersonalAPIKey]) -> set[str]:
        """The ids of the keys that also work in another organization of their owner."""
        memberships: defaultdict[int, set[str]] = defaultdict(set)
        for user_id, organization_id in OrganizationMembership.objects.filter(
            user_id__in={key.user_id for key in keys}
        ).values_list("user_id", "organization_id"):
            memberships[user_id].add(str(organization_id))
        scoped_team_ids = {team_id for key in keys for team_id in key.scoped_teams or []}
        team_organizations = {
            team_id: str(organization_id)
            for team_id, organization_id in Team.objects.filter(pk__in=scoped_team_ids).values_list(
                "id", "organization_id"
            )
        }
        reaching: set[str] = set()
        for key in keys:
            reach = memberships[key.user_id] - {str(self.organization.pk)}
            # Authentication applies each non-empty scope list as its own limit, so an organization must pass both.
            if key.scoped_teams:
                reach &= {team_organizations[team_id] for team_id in key.scoped_teams if team_id in team_organizations}
            if key.scoped_organizations:
                reach &= set(key.scoped_organizations)
            if reach:
                reaching.add(key.pk)
        return reaching

    def previewed(self, key_ids: list[str]) -> QuerySet[PersonalAPIKey]:
        """The keys the preview listed that still reach the organization."""
        return get_organization_personal_api_keys(self.organization).filter(pk__in=key_ids)

    def lock_previewed(self, key_id: str, rolled_before: datetime | None) -> PersonalAPIKey | None:
        # Postgres refuses FOR UPDATE with the DISTINCT of the reach query, so the lock is taken by primary key and
        # the reach is checked once the row is locked.
        # nosemgrep: idor-lookup-without-user -- staff-only console action; the ID comes from the signed preview
        key = PersonalAPIKey.objects.select_for_update(of=("self",)).select_related("user").filter(pk=key_id).first()
        qualifying = self.previewed([key_id])
        if rolled_before is not None:
            qualifying = qualifying.exclude(last_rolled_at__gte=rolled_before)
        return key if key is not None and qualifying.exists() else None

    def blocks(self) -> list[Notice | Table]:
        keys = self.keys(KEYS_LIST_LIMIT + 1)
        shown = keys[:KEYS_LIST_LIMIT]
        blocks: list[Notice | Table] = [self.table(shown)]
        if len(keys) > len(shown):
            blocks.append(Notice(text=f"{self.count() - len(shown)} more keys are not listed."))
        return blocks

    def table(self, keys: list[PersonalAPIKey]) -> Table:
        reaching = self.reaching_other_organizations(keys)
        user_record = RECORD_TYPES["user"]
        return Table(
            columns=("Key", "Value", "Owner", "Works in", "Last used", "Last rolled"),
            rows=tuple(
                Row(
                    cells=(
                        Cell(text=key.label or "No label"),
                        Cell(text=key.mask_value or "", mono=True),
                        Cell(text=key.user.email, href=user_record.url(key.user)),
                        Cell(text="Other organizations too" if key.pk in reaching else "This organization only"),
                        Cell(
                            text=key.last_used_at.strftime("%b %-d, %Y") if key.last_used_at else "Never",
                            muted=key.last_used_at is None,
                        ),
                        # The time of day is shown so staff can confirm a roll they ran a moment ago.
                        Cell(
                            text=key.last_rolled_at.strftime("%b %-d, %Y, %H:%M UTC")
                            if key.last_rolled_at
                            else "Never",
                            muted=key.last_rolled_at is None,
                        ),
                    )
                )
                for key in keys
            ),
            empty_text="No personal API key can reach this organization.",
        )


def organization_keys_tool_url(organization: Organization) -> str:
    tool_url = reverse("admin_console_tool", kwargs={"tool_key": ORGANIZATION_KEYS_TOOL_KEY})
    return f"{tool_url}?organization={organization.pk}"


class OrganizationKeysForm(forms.Form):
    # The preview fills these in and the confirmation token signs them. The confirm step then changes only the keys
    # staff saw, and a second confirm of the same preview skips the keys that the first one rolled.
    previewed_key_ids = forms.CharField(widget=forms.HiddenInput, required=False)
    previewed_at = forms.DateTimeField(widget=forms.HiddenInput, required=False)

    def remember_preview(self, keys: list[PersonalAPIKey], at: datetime) -> None:
        assert isinstance(self.data, QueryDict)
        data = self.data.copy()
        data["previewed_key_ids"] = ",".join(key.pk for key in keys)
        data["previewed_at"] = at.isoformat()
        self.data = data

    def clean_previewed_key_ids(self) -> list[str]:
        return [key_id for key_id in self.cleaned_data["previewed_key_ids"].split(",") if key_id]


class RollOrganizationKeysForm(OrganizationKeysForm):
    exposed_at = forms.CharField(
        label="Where the keys were exposed",
        required=False,
        help_text="Optional, for example a URL. The notification emails include it.",
    )
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), help_text="Goes into the audit log.")


class RevokeOrganizationKeysForm(OrganizationKeysForm):
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), help_text="Goes into the audit log.")


def _preview_organization_keys(obj: Model, form: forms.Form, notice: str) -> Page:
    assert isinstance(obj, Organization) and isinstance(form, OrganizationKeysForm)
    organization_keys = OrganizationPersonalApiKeys(obj)
    keys = organization_keys.keys(KEYS_LIST_LIMIT + 1)
    if len(keys) > KEYS_LIST_LIMIT:
        form.add_error(
            None,
            f"More than {KEYS_LIST_LIMIT} personal API keys can reach this organization, which is too many to "
            "change at once. Roll the keys from each owner's page instead.",
        )
        return Page(blocks=())
    form.remember_preview(keys, timezone.now())
    return Page(blocks=(Notice(text=notice), organization_keys.table(keys)))


def preview_roll_organization_keys(request: HttpRequest, obj: Model, form: forms.Form) -> Page:
    return _preview_organization_keys(
        obj,
        form,
        "Every key below gets a new value. A key that works in other organizations too stops working there as "
        "well, until its owner rolls it.",
    )


def preview_revoke_organization_keys(request: HttpRequest, obj: Model, form: forms.Form) -> Page:
    return _preview_organization_keys(
        obj,
        form,
        "Every key below is deleted. A key that works in other organizations too is deleted for those "
        "organizations as well. The owners get no email.",
    )


def _report_skipped(request: HttpRequest, form: forms.Form, changed: int) -> None:
    skipped = len(form.cleaned_data["previewed_key_ids"]) - changed
    if skipped:
        messages.warning(request, f"Skipped {pluralize(skipped, 'key')} that changed since the preview.")


def roll_organization_personal_api_keys(
    request: HttpRequest, obj: Model, form: forms.Form | None
) -> HttpResponse | None:
    assert isinstance(obj, Organization) and isinstance(form, OrganizationKeysForm)
    more_info = _more_info(form)
    organization_keys = OrganizationPersonalApiKeys(obj)
    keys: list[PersonalAPIKey] = []
    not_notified: set[str] = set()
    # Each key is saved on its own, because the auth cache invalidation and the activity log run on per-row signals.
    for key_id in form.cleaned_data["previewed_key_ids"]:
        # The roll saves every field of the row, so the lock keeps an owner's edit or delete from landing between
        # the check and the save and being undone.
        with transaction.atomic():
            key = organization_keys.lock_previewed(key_id, rolled_before=form.cleaned_data["previewed_at"])
            if key is None:
                continue
            old_mask_value = key.mask_value
            PersonalAPIKeySerializer(instance=key).roll(key)
            _log_change(request, key, "Rolled key.")
        keys.append(key)
        try:
            send_personal_api_key_exposed.delay(key.user_id, key.id, old_mask_value, more_info)
        except OperationalError as error:
            # The key already has its new value, so a broker outage must not stop the roll of the other keys.
            capture_exception(error)
            not_notified.add(key.user.email)
    if keys and not not_notified:
        messages.success(request, f"Rolled {pluralize(len(keys), 'personal API key')} and notified the owners.")
    elif keys:
        messages.success(request, f"Rolled {pluralize(len(keys), 'personal API key')}.")
        messages.warning(
            request,
            f"Could not email these owners: {', '.join(sorted(not_notified))}. Tell them that their keys changed.",
        )
    _report_skipped(request, form, len(keys))
    return None


def revoke_organization_personal_api_keys(
    request: HttpRequest, obj: Model, form: forms.Form | None
) -> HttpResponse | None:
    assert isinstance(obj, Organization) and isinstance(form, OrganizationKeysForm)
    organization_keys = OrganizationPersonalApiKeys(obj)
    deleted = 0
    # Each key is deleted on its own, because the auth cache invalidation and the activity log run on per-row signals.
    for key_id in form.cleaned_data["previewed_key_ids"]:
        with transaction.atomic():
            key = organization_keys.lock_previewed(key_id, rolled_before=None)
            if key is None:
                continue
            key.delete()
        deleted += 1
    if deleted:
        messages.success(request, f"Deleted {pluralize(deleted, 'personal API key')}.")
    _report_skipped(request, form, deleted)
    return None


@console.register_panel
class OrganizationPersonalApiKeysPanel(Panel):
    record = "organization"
    key = "personal-api-keys"
    title = "Personal API keys"
    owner = DEV_EXPERIENCE
    danger = True

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, Organization)
        count = OrganizationPersonalApiKeys(obj).count()
        if not count:
            return [Fact(label="Keys", value="No personal API key can reach this organization.")]
        return [
            Fact(
                label="Keys",
                value=f"{pluralize(count, 'key')} of members can reach this organization",
                href=organization_keys_tool_url(obj),
            )
        ]

    def operations(self, obj: Model) -> list[Operation]:
        assert isinstance(obj, Organization)
        if not get_organization_personal_api_keys(obj).exists():
            return []
        return [
            Operation(
                key="roll-all",
                label="Roll all keys",
                handler=roll_organization_personal_api_keys,
                preview=preview_roll_organization_keys,
                danger=True,
                description=(
                    "Every personal API key that can reach this organization gets a new value, so whatever uses "
                    "the old one stops working. Each owner gets an email that the key was exposed."
                ),
                form_class=RollOrganizationKeysForm,
                undo_hint="This cannot be undone. Each owner rolls the key in their personal API key settings.",
            ),
            Operation(
                key="revoke-all",
                label="Revoke all keys",
                handler=revoke_organization_personal_api_keys,
                preview=preview_revoke_organization_keys,
                danger=True,
                description=(
                    "Deletes every personal API key that can reach this organization, so whatever uses one stops "
                    "working. The owners get no email."
                ),
                form_class=RevokeOrganizationKeysForm,
                undo_hint="This cannot be undone. Each owner creates a new key in their personal API key settings.",
            ),
        ]


@console.register_tool
class OrganizationPersonalApiKeysTool(ConsoleTool):
    key = ORGANIZATION_KEYS_TOOL_KEY
    title = "Organization personal API keys"
    owner = DEV_EXPERIENCE
    group = "Access"
    description = "Lists the personal API keys that can reach one organization."

    def page(self, request: HttpRequest) -> Page:
        organization_id = request.GET.get("organization", "")
        try:
            organization = Organization.objects.filter(pk=organization_id).first() if organization_id else None
        except ValidationError:
            organization = None
        if organization is None:
            return Page(
                blocks=(Notice(text="Open an organization's keys from the Personal API keys panel on its page."),)
            )
        return Page(
            blocks=(
                Notice(
                    text=f"These personal API keys can reach {organization.name}.",
                    link_text="Back to the organization",
                    href=RECORD_TYPES["organization"].url(organization) + "#panel-personal-api-keys",
                ),
                *OrganizationPersonalApiKeys(organization).blocks(),
            )
        )


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
