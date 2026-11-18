import re
from typing import Any
from uuid import UUID

from django import forms
from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse

from posthog.admin.console.records import RECORD_TYPES
from posthog.admin.console.registry import console
from posthog.admin.console.team_panels import DEV_EXPERIENCE
from posthog.admin.console.tools import Cell, ConsoleTool, Notice, Page, Row, Table, ToolOperation
from posthog.models.organization import Organization
from posthog.utils import pluralize


class BulkDeactivateOrganizationsForm(forms.Form):
    CUSTOM_REASON = "__custom__"
    MAX_ORGANIZATIONS = 100

    organization_ids = forms.CharField(
        label="Organization IDs",
        widget=forms.Textarea(
            attrs={"rows": 10, "placeholder": "Paste one organization ID per line, or separate IDs with commas."}
        ),
        help_text=f"Up to {MAX_ORGANIZATIONS} organization IDs, separated by new lines, commas or spaces.",
    )
    reason = forms.ChoiceField(
        label="Reason",
        choices=[*Organization.DeactivationReason.choices, (CUSTOM_REASON, "Custom reason")],
        initial=Organization.DeactivationReason.DESKTOP_ABUSE,
        help_text="Members of the organization see this reason.",
    )
    custom_reason = forms.CharField(
        label="Custom reason",
        required=False,
        max_length=Organization._meta.get_field("is_not_active_reason").max_length,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Used only when the reason is Custom reason.",
    )

    def clean_organization_ids(self) -> list[UUID]:
        raw_value = self.cleaned_data["organization_ids"]
        invalid_tokens: list[str] = []
        organization_ids: list[UUID] = []
        seen_ids: set[UUID] = set()
        token_count = 0

        for match in re.finditer(r"[^,\s]+", raw_value):
            token_count += 1
            if token_count > self.MAX_ORGANIZATIONS:
                raise forms.ValidationError(f"Enter {self.MAX_ORGANIZATIONS} organization IDs or fewer.")
            token = match.group()
            try:
                organization_id = UUID(token)
            except ValueError:
                invalid_tokens.append(token)
                continue
            if organization_id not in seen_ids:
                seen_ids.add(organization_id)
                organization_ids.append(organization_id)

        if token_count == 0:
            raise forms.ValidationError("Enter at least one organization ID.")
        if invalid_tokens:
            raise forms.ValidationError(
                "These organization IDs are not valid UUIDs: %(ids)s",
                params={"ids": ", ".join(invalid_tokens[:10])},
            )
        return organization_ids

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean() or {}
        reason = cleaned_data.get("reason")
        custom_reason = (cleaned_data.get("custom_reason") or "").strip()
        if reason == self.CUSTOM_REASON:
            if not custom_reason:
                self.add_error("custom_reason", "Enter a custom reason.")
                return cleaned_data
            cleaned_data["resolved_reason"] = custom_reason
        elif reason:
            cleaned_data["resolved_reason"] = reason
        return cleaned_data


class BulkDeactivation:
    """Which of the pasted organizations a bulk deactivation changes, skips, or cannot find."""

    def __init__(self, organization_ids: list[UUID]) -> None:
        found = Organization.objects.only("id", "name", "is_active", "is_not_active_reason").in_bulk(organization_ids)
        matched = [found[organization_id] for organization_id in organization_ids if organization_id in found]
        self.to_deactivate = [organization for organization in matched if organization.is_active is not False]
        self.already_inactive = [organization for organization in matched if organization.is_active is False]
        self.missing_ids = [
            str(organization_id) for organization_id in organization_ids if organization_id not in found
        ]


def _organization_row(organization: Organization, status: str) -> Row:
    return Row(
        cells=(
            Cell(text=organization.name, href=RECORD_TYPES["organization"].url(organization)),
            Cell(text=str(organization.id), mono=True),
            Cell(text=status),
        )
    )


def preview_bulk_deactivation(request: HttpRequest, form: forms.Form) -> Page:
    deactivation = BulkDeactivation(form.cleaned_data["organization_ids"])
    if not deactivation.to_deactivate:
        message = (
            "All matched organizations are already inactive."
            if deactivation.already_inactive
            else "No organizations matched these IDs."
        )
        form.add_error("organization_ids", message)
        return Page(blocks=())

    rows = [_organization_row(organization, "Deactivates") for organization in deactivation.to_deactivate]
    rows += [
        _organization_row(organization, f"Skipped, already inactive: {organization.is_not_active_reason or '-'}")
        for organization in deactivation.already_inactive
    ]
    blocks: list[Notice | Table] = [
        Notice(
            text=(
                f"Deactivates {pluralize(len(deactivation.to_deactivate), 'organization')} "
                f"with the reason: {form.cleaned_data['resolved_reason']}"
            )
        ),
        Table(columns=("Organization", "ID", "What happens"), rows=tuple(rows)),
    ]
    if deactivation.missing_ids:
        blocks.append(Notice(text=f"Not found, skipped: {', '.join(deactivation.missing_ids)}"))
    return Page(blocks=tuple(blocks))


def bulk_deactivate(request: HttpRequest, form: forms.Form | None) -> HttpResponse | Page | None:
    assert form is not None
    deactivation = BulkDeactivation(form.cleaned_data["organization_ids"])
    reason = form.cleaned_data["resolved_reason"]
    with transaction.atomic():
        # Read the active state again under a lock, so an organization deactivated since the preview keeps
        # its existing reason. No-key, because only plain columns change and child rows may keep inserting.
        locked = list(
            Organization.objects.select_for_update(no_key=True)
            .only("id", "is_active", "is_not_active_reason")
            .filter(id__in=[organization.id for organization in deactivation.to_deactivate])
            .exclude(is_active=False)
        )
        for organization in locked:
            organization.is_active = False
            organization.is_not_active_reason = reason
            organization.save(update_fields=["is_active", "is_not_active_reason", "updated_at"])

    if locked:
        messages.success(request, f"Deactivated {pluralize(len(locked), 'organization')}.")
    if deactivation.missing_ids:
        messages.warning(
            request, f"Skipped {pluralize(len(deactivation.missing_ids), 'organization ID')} that were not found."
        )
    skipped = len(deactivation.already_inactive) + len(deactivation.to_deactivate) - len(locked)
    if skipped:
        messages.warning(request, f"Skipped {pluralize(skipped, 'already inactive organization')}, reason unchanged.")
    return None


@console.register_tool
class OrganizationBulkDeactivationTool(ConsoleTool):
    key = "bulk-deactivate-organizations"
    title = "Bulk deactivate organizations"
    owner = DEV_EXPERIENCE
    group = "Organizations"
    description = "Deactivates organizations from a list of pasted IDs, after a preview."

    def page(self, request: HttpRequest) -> Page:
        return Page(
            blocks=(
                Notice(
                    text=(
                        "Members of a deactivated organization cannot use PostHog until staff reactivate it. "
                        "You see the organizations and what happens to each before anything changes."
                    )
                ),
            )
        )

    def operations(self, request: HttpRequest) -> list[ToolOperation]:
        return [
            ToolOperation(
                key="deactivate",
                label="Deactivate organizations",
                handler=bulk_deactivate,
                preview=preview_bulk_deactivation,
                danger=True,
                description="Deactivates every pasted organization that is still active.",
                form_class=BulkDeactivateOrganizationsForm,
                undo_hint="To undo, reactivate each organization on its Django admin page.",
            )
        ]


console.register_moved_page(
    old_path="admin/posthog/organization/bulk-deactivate/",
    title="Bulk deactivation",
    url="/admin/console/tools/bulk-deactivate-organizations/",
)
