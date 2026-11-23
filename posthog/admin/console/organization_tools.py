import re
from typing import Any, cast
from urllib.parse import urlencode
from uuid import UUID, uuid4

from django import forms
from django.contrib import messages
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect

from posthog.admin.console.organization_shutdown import (
    RUN_FOLLOW_UP,
    STOP_NOTICE,
    UNDO_HINT,
    OrganizationShutdownForm,
    ShutdownRuns,
    deactivate_organizations,
    inventory_table,
    planned_action,
    run_table,
    shut_down_organizations,
    take_inventory,
)
from posthog.admin.console.registry import console
from posthog.admin.console.tools import ConsoleTool, Live, Notice, Page, Table, ToolOperation
from posthog.models.organization import Organization
from posthog.models.user import User
from posthog.tasks.organization_shutdown import stop_organizations_background_work
from posthog.utils import pluralize

TOOL_URL = "/admin/console/tools/bulk-deactivate-organizations/"
RUN_REFRESH_SECONDS = 3


class BulkDeactivateOrganizationsForm(OrganizationShutdownForm):
    MAX_ORGANIZATIONS = 100

    organization_ids = forms.CharField(
        label="Organization IDs",
        widget=forms.Textarea(
            attrs={"rows": 10, "placeholder": "Paste one organization ID per line, or separate IDs with commas."}
        ),
        help_text=f"Up to {MAX_ORGANIZATIONS} organization IDs, separated by new lines, commas or spaces.",
    )
    field_order = ["organization_ids", "reason", "custom_reason", "stop_background_work"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["reason"].initial = Organization.DeactivationReason.DESKTOP_ABUSE

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


class BulkDeactivation:
    """Which of the pasted organizations a bulk deactivation changes, skips, or cannot find."""

    def __init__(self, organization_ids: list[UUID], *, stop_background_work: bool) -> None:
        found = Organization.objects.in_bulk(organization_ids)
        self.matched = [found[organization_id] for organization_id in organization_ids if organization_id in found]
        self.to_deactivate = [organization for organization in self.matched if organization.is_active is not False]
        self.already_inactive = [organization for organization in self.matched if organization.is_active is False]
        self.missing_ids = [
            str(organization_id) for organization_id in organization_ids if organization_id not in found
        ]
        # An organization that is already inactive can still run work in the background, so stopping that work
        # acts on it too. Without that, it is skipped as before.
        self.acted_on = self.matched if stop_background_work else self.to_deactivate


def preview_bulk_deactivation(request: HttpRequest, form: forms.Form) -> Page:
    stop_background_work = form.cleaned_data["stop_background_work"]
    deactivation = BulkDeactivation(form.cleaned_data["organization_ids"], stop_background_work=stop_background_work)
    if not deactivation.acted_on:
        message = (
            "All matched organizations are already inactive."
            if deactivation.already_inactive
            else "No organizations matched these IDs."
        )
        form.add_error("organization_ids", message)
        return Page(blocks=())

    blocks: list[Notice | Table] = [
        Notice(
            text=(
                f"Deactivates {pluralize(len(deactivation.to_deactivate), 'organization')} "
                f"with the reason: {form.cleaned_data['resolved_reason']}"
            )
        )
    ]
    if stop_background_work:
        blocks.append(Notice(text=STOP_NOTICE))
    actions = {
        organization.id: planned_action(organization, stop_background_work=stop_background_work)
        for organization in deactivation.matched
    }
    blocks.append(inventory_table([take_inventory(organization) for organization in deactivation.matched], actions))
    if deactivation.missing_ids:
        blocks.append(Notice(text=f"Not found, skipped: {', '.join(deactivation.missing_ids)}"))
    return Page(blocks=tuple(blocks))


def _run_id(request: HttpRequest) -> str:
    # The form nonce names the run, so a confirm submitted twice starts one run.
    try:
        return str(UUID(request.POST.get("form_nonce", "")))
    except ValueError:
        return str(uuid4())


def bulk_deactivate(request: HttpRequest, form: forms.Form | None) -> HttpResponse | Page | None:
    assert form is not None
    stop_background_work = form.cleaned_data["stop_background_work"]
    deactivation = BulkDeactivation(form.cleaned_data["organization_ids"], stop_background_work=stop_background_work)
    organization_ids = [organization.id for organization in deactivation.acted_on]
    reason = form.cleaned_data["resolved_reason"]
    triggered_by = cast(User, request.user).email
    if deactivation.missing_ids:
        messages.warning(
            request, f"Skipped {pluralize(len(deactivation.missing_ids), 'organization ID')} that were not found."
        )

    if stop_background_work:
        deactivated = deactivate_organizations(organization_ids, reason)
        run_id = _run_id(request)
        if ShutdownRuns.start(run_id, total=len(organization_ids)):
            stop_organizations_background_work.delay(
                run_id,
                [str(organization_id) for organization_id in organization_ids],
                [str(organization_id) for organization_id in deactivated],
                reason,
                triggered_by,
            )
        messages.success(
            request,
            f"Deactivated {pluralize(len(deactivated), 'organization')}. Their background work stops in a background "
            "job, and this page follows it.",
        )
        return HttpResponseRedirect(f"{TOOL_URL}?{urlencode({'run': run_id})}")

    results = shut_down_organizations(
        organization_ids, reason=reason, stop_background_work=False, triggered_by=triggered_by
    )
    deactivated_count = sum(result.deactivated for result in results)
    if deactivated_count:
        messages.success(request, f"Deactivated {pluralize(deactivated_count, 'organization')}.")
    skipped = len(deactivation.matched) - deactivated_count
    if skipped:
        messages.warning(request, f"Skipped {pluralize(skipped, 'already inactive organization')}, reason unchanged.")
    return None


def _requested_run(request: HttpRequest) -> str | None:
    try:
        return str(UUID(request.GET.get("run", "")))
    except ValueError:
        return None


@console.register_tool
class OrganizationBulkDeactivationTool(ConsoleTool):
    key = "bulk-deactivate-organizations"
    title = "Bulk deactivate organizations"
    owner = None
    group = "Organizations"
    description = (
        "Deactivates organizations from a list of pasted IDs and stops their background work, after a preview."
    )

    def page(self, request: HttpRequest) -> Page:
        intro = Notice(
            text=(
                "Members of a deactivated organization cannot use PostHog until staff reactivate it. "
                "You see the organizations, the work each runs in the background, and what happens to each "
                "before anything changes."
            )
        )
        run = self.live(request, "run")
        if run is None:
            return Page(blocks=(intro,))
        return Page(blocks=(Notice(text=RUN_FOLLOW_UP, link_text="Start another", href=TOOL_URL), run))

    def live(self, request: HttpRequest, key: str) -> Live | None:
        run_id = _requested_run(request)
        if key != "run" or run_id is None:
            return None
        run = ShutdownRuns.read(run_id)
        if run is None:
            return Live(key="run", block=Notice(text="This run is unknown or too old to show. The audit log keeps it."))
        return Live(key="run", block=run_table(run), refresh_seconds=None if run.finished else RUN_REFRESH_SECONDS)

    def operations(self, request: HttpRequest) -> list[ToolOperation]:
        return [
            ToolOperation(
                key="deactivate",
                label="Deactivate organizations",
                handler=bulk_deactivate,
                preview=preview_bulk_deactivation,
                danger=True,
                description=(
                    "Deactivates every pasted organization that is still active, and stops the background work "
                    "of each one unless you turn that off."
                ),
                form_class=BulkDeactivateOrganizationsForm,
                undo_hint=UNDO_HINT,
                pending_label="Deactivating...",
            )
        ]


console.register_moved_page(
    old_path="admin/posthog/organization/bulk-deactivate/",
    title="Bulk deactivation",
    url=TOOL_URL,
)
