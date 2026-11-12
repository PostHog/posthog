import re
from typing import Any, cast

from django import forms
from django.db.models import Model
from django.http import HttpRequest, HttpResponse

from posthog.admin.console.member_email_migration import MemberEmailChange, MemberEmailMigration, RequestedEmailChange
from posthog.admin.console.panels import MAX_FACTS_PER_PANEL, Fact, Operation, Panel, Tone
from posthog.admin.console.records import RECORD_TYPES
from posthog.admin.console.registry import console
from posthog.admin.console.team_panels import DEV_EXPERIENCE
from posthog.admin.console.tools import Cell, Notice, Page, Row, Table
from posthog.models.organization import Organization
from posthog.models.user import User
from posthog.utils import pluralize


class ChangeMemberEmailsForm(forms.Form):
    MAX_MEMBERS = 500
    # A line holds the current email and, optionally, the new one. Staff paste lists from sheets and
    # chats, so spaces, commas, semicolons and arrows all separate the two.
    _SEPARATORS = re.compile(r"(?:\s|,|;|->|=>|→)+")

    members = forms.CharField(
        label="Members to change",
        widget=forms.Textarea(attrs={"rows": 12}),
        help_text=(
            "One member per line. Delete a line to leave that member unchanged. "
            "To choose the new email yourself, add it on the same line after a space, "
            "for example: ada@old.example.com ada.lovelace@new.example.com. "
            f"Up to {MAX_MEMBERS} members at a time."
        ),
    )
    new_domain = forms.CharField(
        label="New domain",
        required=False,
        help_text="Used for every line without a new email. The part before the @ stays the same.",
    )
    notify = forms.BooleanField(
        label="Email each member about the change, at the old and the new address", required=False, initial=True
    )
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), help_text="Goes into the audit log.")

    def clean_members(self) -> list[RequestedEmailChange]:
        requested = []
        invalid_lines = []
        for line in self.cleaned_data["members"].splitlines():
            parts = [part for part in self._SEPARATORS.split(line.strip()) if part]
            if not parts:
                continue
            if len(parts) > 2 or any("@" not in part for part in parts):
                invalid_lines.append(line.strip())
                continue
            requested.append(
                RequestedEmailChange(current_email=parts[0], new_email=parts[1] if len(parts) == 2 else None)
            )
        if invalid_lines:
            raise forms.ValidationError(
                "These lines are not a current email, or a current email and a new one: %(lines)s",
                params={"lines": "; ".join(invalid_lines[:10])},
            )
        if not requested:
            raise forms.ValidationError("Enter at least one member.")
        if len(requested) > self.MAX_MEMBERS:
            raise forms.ValidationError(f"Enter {self.MAX_MEMBERS} members or fewer.")
        return requested

    def clean_new_domain(self) -> str:
        return self.cleaned_data["new_domain"].strip().lstrip("@").lower()

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean() or {}
        requested = cleaned_data.get("members") or []
        if not cleaned_data.get("new_domain") and any(request.new_email is None for request in requested):
            self.add_error("new_domain", "Enter a new domain, or type a new email on every line.")
        return cleaned_data


def _migration(organization: Organization, form: forms.Form) -> MemberEmailMigration:
    return MemberEmailMigration(
        organization=organization,
        requested=form.cleaned_data["members"],
        new_domain=form.cleaned_data["new_domain"] or None,
    )


def _change_row(change: MemberEmailChange, changed_text: str) -> Row:
    return Row(
        cells=(
            Cell(
                text=change.current_email,
                href=RECORD_TYPES["user"].url(change.user) if change.user is not None else None,
                mono=True,
            ),
            Cell(text=change.new_email or "-", mono=True),
            Cell(text=changed_text)
            if change.changes
            else Cell(text=f"Skipped: {change.skip_reason}", tone=Tone.WARNING),
        )
    )


def _changes_table(changes: list[MemberEmailChange], changed_text: str) -> Table:
    # Rows that change lead, so staff read what happens before what does not.
    ordered = sorted(changes, key=lambda change: not change.changes)
    return Table(
        columns=("Current email", "New email", "What happens"),
        rows=tuple(_change_row(change, changed_text) for change in ordered),
    )


def preview_member_email_changes(request: HttpRequest, obj: Model, form: forms.Form) -> Page:
    assert isinstance(obj, Organization)
    new_domain = form.cleaned_data["new_domain"]
    verified = MemberEmailMigration.verified_domains(obj)
    if new_domain and new_domain not in verified:
        form.add_error(
            "new_domain",
            f"This organization has not verified {new_domain}. Its verified domains: {', '.join(sorted(verified))}.",
        )
        return Page(blocks=())
    changes = _migration(obj, form).plan()
    changing = [change for change in changes if change.changes]
    if not changing:
        form.add_error("members", "None of these emails can be changed.")
        emails_by_reason: dict[str, list[str]] = {}
        for change in changes:
            emails_by_reason.setdefault(change.skip_reason or "", []).append(change.current_email)
        for reason, emails in emails_by_reason.items():
            more = f" and {len(emails) - 3} more" if len(emails) > 3 else ""
            form.add_error("members", f"{reason}: {', '.join(emails[:3])}{more}")
        return Page(blocks=())

    blocks: list[Notice | Table] = [
        Notice(
            text=(
                f"Changes the email of {pluralize(len(changing), 'member')}. Each one is signed out of PostHog "
                "and signs in with the new email from then on. The account and its access stay the same."
            )
        )
    ]
    if obj.identity_provider_configs.filter(scim_enabled=True).exists():
        blocks.append(
            Notice(
                text=(
                    "SCIM is on for this organization. The identity provider can change an email back on its "
                    "next sync, so check that it no longer sends the old address."
                ),
                tone=Tone.WARNING,
            )
        )
    blocks.append(_changes_table(changes, "Changes"))
    return Page(blocks=tuple(blocks))


def change_member_emails(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | Page | None:
    assert isinstance(obj, Organization) and form is not None
    results = _migration(obj, form).apply(
        notify=form.cleaned_data["notify"], changed_by=cast(User, request.user), reason=form.cleaned_data["reason"]
    )
    changed = sum(1 for result in results if result.changes)
    skipped = len(results) - changed
    summary = f"Changed the email of {pluralize(changed, 'member')}."
    if skipped:
        summary += f" Skipped {pluralize(skipped, 'member')}."
    return Page(
        blocks=(
            Notice(text=summary, tone=Tone.WARNING if skipped else Tone.SUCCESS),
            _changes_table(results, "Changed"),
        )
    )


@console.register_panel
class OrganizationSignInPanel(Panel):
    record = "organization"
    key = "sign-in"
    title = "Sign-in"
    owner = DEV_EXPERIENCE
    order = 25

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, Organization)
        domains = list(obj.domains.order_by("domain")[: MAX_FACTS_PER_PANEL + 1])
        if not domains:
            return [Fact(label="Authentication domains", value="None")]
        shown = domains if len(domains) <= MAX_FACTS_PER_PANEL else domains[: MAX_FACTS_PER_PANEL - 1]
        facts = []
        for domain in shown:
            if domain.verified_at is None:
                facts.append(Fact(label=domain.domain, value="Not verified", tone=Tone.WARNING))
            elif domain.sso_enforcement:
                facts.append(Fact(label=domain.domain, value=f"Verified, enforces {domain.sso_enforcement} sign-in"))
            else:
                facts.append(Fact(label=domain.domain, value="Verified, SSO not enforced"))
        if len(shown) < len(domains):
            facts.append(Fact(label="More", value=f"{obj.domains.count() - len(shown)} more domains."))
        return facts

    def operations(self, obj: Model) -> list[Operation]:
        assert isinstance(obj, Organization)
        emails = MemberEmailMigration.eligible_emails(obj, limit=ChangeMemberEmailsForm.MAX_MEMBERS)
        if not emails:
            return []
        return [
            Operation(
                key="change-member-emails",
                label="Change member emails",
                handler=change_member_emails,
                preview=preview_member_email_changes,
                danger=True,
                description="Changes members' emails in bulk.",
                form_class=ChangeMemberEmailsForm,
                form_initial={"members": "\n".join(emails)},
                undo_hint=(
                    "There is no undo. To reverse it, run this again with the new emails and change them back. "
                    "SSO links and sessions are not restored."
                ),
                pending_label="Changing emails",
            )
        ]
