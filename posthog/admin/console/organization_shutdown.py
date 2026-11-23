"""Shutting down an organization that abuses PostHog: deactivate it, then stop the work it runs in the background.

The bulk deactivation tool and the organization page both run `shut_down_organizations`, so the two entry points
cannot drift apart.
"""

from collections.abc import Callable, Collection, Sequence
from functools import partial
from typing import Any
from uuid import UUID

from django import forms
from django.db import transaction
from django.urls import reverse

import structlog

from posthog.admin.console.panels import Tone
from posthog.admin.console.records import RECORD_TYPES
from posthog.admin.console.tools import Cell, GroupRow, Notice, Page, Row, Table
from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models.organization import Organization
from posthog.models.personal_api_key import get_organization_personal_api_keys
from posthog.utils import pluralize

from products.alerts.backend.facade import api as alerts
from products.batch_exports.backend.facade import api as batch_exports
from products.cdp.backend.facade import api as cdp
from products.subscriptions.backend.facade import api as subscriptions
from products.warehouse_sources.backend.facade import staff as warehouse
from products.workflows.backend.facade import writes as workflows

logger = structlog.get_logger(__name__)

# The note on each paused batch export's Temporal schedule.
PAUSE_NOTE = "Paused for Terms of Service violation"
AUDIT_EVENT = "admin_console_organization_shutdown"
STOP_NOTICE = (
    "Stops the background work listed below, also for an organization that is already inactive. "
    "Reactivating an organization later does not restart it."
)
UNDO_HINT = (
    "To undo, reactivate the organization on its Django admin page. That does not restart the background work "
    f"this stopped. Turn each item back on by hand: the result page and the {AUDIT_EVENT} event in the audit log "
    "list every stopped ID."
)

HOG_FUNCTION_LABELS = {
    "destination": "Destinations",
    "site_destination": "Site destinations",
    "internal_destination": "Internal destinations",
    "legacy_destination": "Legacy destinations",
    "source_webhook": "Webhook sources",
    "warehouse_source_webhook": "Warehouse webhook sources",
    "site_app": "Site apps",
    "transformation": "Transformations",
    "transformation_log": "Log transformations",
}


def _hog_function_label(function_type: str) -> str:
    return HOG_FUNCTION_LABELS.get(function_type) or f"Hog functions of type {function_type or 'none'}"


class OrganizationShutdownForm(forms.Form):
    CUSTOM_REASON = "__custom__"

    reason = forms.ChoiceField(
        label="Reason",
        choices=[*Organization.DeactivationReason.choices, (CUSTOM_REASON, "Custom reason")],
        initial=Organization.DeactivationReason.TERMS_OF_SERVICE_VIOLATION_SECURITY,
        help_text="Members of the organization see this reason.",
    )
    custom_reason = forms.CharField(
        label="Custom reason",
        required=False,
        max_length=Organization._meta.get_field("is_not_active_reason").max_length,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Used only when the reason is Custom reason.",
    )
    stop_background_work = forms.BooleanField(
        label="Stop background work",
        required=False,
        initial=True,
        help_text=(
            "Disables destinations, transformations, site apps, webhook sources, legacy plugins, subscriptions and "
            "insight alerts, moves active workflows to draft, pauses batch exports, warehouse syncs and CDC "
            "extraction, and stops warehouse sources from syncing new tables by themselves. "
            "This also runs for an organization that is already inactive, which keeps its reason."
        ),
    )

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


def planned_action(organization: Organization, *, stop_background_work: bool) -> str:
    """What a shutdown does to the organization, as the preview tells staff."""
    if organization.is_active is not False:
        return "Deactivates and stops background work" if stop_background_work else "Deactivates"
    reason = organization.is_not_active_reason or "-"
    if stop_background_work:
        return f"Already inactive, keeps its reason: {reason}. Stops background work"
    return f"Skipped, already inactive: {reason}"


@frozen
class BackgroundWork:
    """The running items of one kind, such as the enabled destinations of an organization, and how to stop one.

    `stop(resource_id, team_id=...)` stops one item of that team, and returns False when it no longer runs.
    """

    label: str
    ids: tuple[str, ...]
    stop: Callable[..., bool]


def _hog_function_work(team_ids: Collection[int]) -> list[BackgroundWork]:
    return [
        BackgroundWork(
            label=_hog_function_label(function_type),
            ids=tuple(ids),
            stop=cdp.disable_hog_function,
        )
        for function_type, ids in cdp.enabled_hog_function_ids_by_type(team_ids).items()
    ]


def _work_of_one_kind(
    label: str,
    find: Callable[[Collection[int]], list[str]],
    stop: Callable[..., bool],
    team_ids: Collection[int],
) -> list[BackgroundWork]:
    return [BackgroundWork(label=label, ids=tuple(find(team_ids)), stop=stop)]


def _finders(team_ids: Collection[int]) -> list[tuple[str, Callable[[], list[BackgroundWork]]]]:
    """How to list each kind of work, by the name staff see when the listing itself fails."""
    kinds: tuple[tuple[str, Callable[[Collection[int]], list[str]], Callable[..., bool]], ...] = (
        ("Workflows", workflows.active_workflow_ids, workflows.move_workflow_to_draft),
        (
            "Batch exports",
            batch_exports.unpaused_batch_export_ids,
            partial(batch_exports.pause_running_batch_export, note=PAUSE_NOTE),
        ),
        # Sources go before their tables: a source counts as running CDC only while one of its CDC tables syncs.
        ("Warehouse sources", warehouse.running_source_ids_for_staff, warehouse.stop_source_for_staff),
        ("Warehouse syncs", warehouse.syncing_schema_ids_for_staff, warehouse.stop_schema_syncing_for_staff),
        ("Legacy plugins", cdp.enabled_plugin_config_ids, cdp.disable_plugin_config),
        ("Subscriptions", subscriptions.enabled_subscription_ids, subscriptions.disable_subscription),
        ("Insight alerts", alerts.enabled_alert_ids, alerts.disable_alert),
    )
    return [
        ("Hog functions", partial(_hog_function_work, team_ids)),
        *((label, partial(_work_of_one_kind, label, find, stop, team_ids)) for label, find, stop in kinds),
    ]


@frozen
class BackgroundWorkListing:
    running: tuple[BackgroundWork, ...]
    # Kinds whose listing failed. Staff see them, so a failed query never reads as nothing running.
    unlisted: tuple[str, ...]

    def summary(self) -> str:
        parts = [f"{work.label}: {len(work.ids)}" for work in self.running]
        parts += [f"{kind}: could not list" for kind in self.unlisted]
        return ", ".join(parts) or "None running"


def find_background_work(team_ids: Collection[int]) -> BackgroundWorkListing:
    """Every kind of work the teams run without anyone signed in, with at least one item running."""
    running: list[BackgroundWork] = []
    unlisted: list[str] = []
    for kind, find in _finders(team_ids):
        try:
            running += [work for work in find() if work.ids]
        except Exception as error:
            capture_exception(error)
            unlisted.append(kind)
    return BackgroundWorkListing(running=tuple(running), unlisted=tuple(unlisted))


@frozen
class OrganizationInventory:
    organization_id: UUID
    name: str
    member_count: int
    personal_key_count: int
    background_work: BackgroundWorkListing


def take_inventory(organization: Organization) -> OrganizationInventory:
    team_ids = list(organization.teams.values_list("id", flat=True))
    return OrganizationInventory(
        organization_id=organization.id,
        name=organization.name,
        member_count=organization.members.count(),
        personal_key_count=get_organization_personal_api_keys(organization).count(),
        background_work=find_background_work(team_ids),
    )


@frozen
class StoppedWork:
    label: str
    ids: tuple[str, ...]


@frozen
class StopFailure:
    label: str
    resource_id: str
    error: str


@frozen
class ShutdownResult:
    organization_id: UUID
    name: str
    deactivated: bool
    stopped: tuple[StoppedWork, ...]
    failures: tuple[StopFailure, ...]


def _deactivate(organization_ids: Sequence[UUID], reason: str) -> set[UUID]:
    with transaction.atomic():
        # Read the active state again under a lock, so an organization deactivated since the preview keeps
        # its existing reason. No-key, because only plain columns change and child rows may keep inserting.
        locked = list(
            Organization.objects.select_for_update(no_key=True)
            .only("id", "is_active", "is_not_active_reason")
            .filter(id__in=organization_ids)
            .exclude(is_active=False)
        )
        for organization in locked:
            organization.is_active = False
            organization.is_not_active_reason = reason
            organization.save(update_fields=["is_active", "is_not_active_reason", "updated_at"])
    return {organization.id for organization in locked}


def _stop_background_work(organization: Organization) -> tuple[list[StoppedWork], list[StopFailure]]:
    stopped: dict[str, list[str]] = {}
    failures: list[StopFailure] = []
    # Each kind is listed, and each item stopped, on its own, so one that fails, such as a Temporal schedule that
    # refuses to pause, leaves the rest to stop and shows on the result page. Each stop names its team, so it can
    # never reach an item outside the organization.
    for team_id in organization.teams.order_by("id").values_list("id", flat=True):
        for kind, find in _finders([team_id]):
            try:
                found = find()
            except Exception as error:
                failures.append(_failure(organization, StopFailure(label=kind, resource_id="", error=_describe(error))))
                capture_exception(error)
                continue
            for work in found:
                for resource_id in work.ids:
                    try:
                        if work.stop(resource_id, team_id=team_id):
                            stopped.setdefault(work.label, []).append(resource_id)
                    except Exception as error:
                        failure = StopFailure(label=work.label, resource_id=resource_id, error=_describe(error))
                        failures.append(_failure(organization, failure))
                        capture_exception(error)
    return [StoppedWork(label=label, ids=tuple(ids)) for label, ids in stopped.items()], failures


def _failure(organization: Organization, failure: StopFailure) -> StopFailure:
    logger.warning(
        "organization_shutdown_stop_failed",
        organization_id=str(organization.id),
        kind=failure.label,
        resource_id=failure.resource_id,
        error=failure.error,
    )
    return failure


def _describe(error: Exception) -> str:
    message = str(error).strip()
    return f"{type(error).__name__}: {message}"[:300] if message else type(error).__name__


def shut_down_organizations(
    organization_ids: Sequence[UUID], *, reason: str, stop_background_work: bool, triggered_by: str
) -> list[ShutdownResult]:
    """Deactivates each organization that is still active with `reason`, and with `stop_background_work`, stops
    what every one of them runs in the background, the already inactive ones included.

    Nothing is deleted. Each stopped ID goes to the audit log, because reactivating an organization does not restart
    its work: staff turn it back on by hand.
    """
    deactivated = _deactivate(organization_ids, reason)
    organizations = Organization.objects.only("id", "name").in_bulk(organization_ids)
    results: list[ShutdownResult] = []
    for organization_id in organization_ids:
        organization = organizations.get(organization_id)
        if organization is None:
            continue
        stopped, failures = _stop_background_work(organization) if stop_background_work else ([], [])
        result = ShutdownResult(
            organization_id=organization.id,
            name=organization.name,
            deactivated=organization.id in deactivated,
            stopped=tuple(stopped),
            failures=tuple(failures),
        )
        logger.info(
            AUDIT_EVENT,
            organization_id=str(organization.id),
            triggered_by=triggered_by,
            reason=reason,
            deactivated=result.deactivated,
            stopped={work.label: list(work.ids) for work in result.stopped},
            failed=[{"kind": failure.label, "id": failure.resource_id} for failure in result.failures],
        )
        results.append(result)
    return results


def _organization_url(organization_id: UUID) -> str:
    return reverse(RECORD_TYPES["organization"].url_name, kwargs={"pk": organization_id})


def inventory_table(inventories: Sequence[OrganizationInventory], actions: dict[UUID, str]) -> Table:
    rows = [
        Row(
            cells=(
                Cell(text=inventory.name, href=_organization_url(inventory.organization_id)),
                Cell(text=str(inventory.organization_id), mono=True),
                Cell(text=actions[inventory.organization_id]),
                Cell(text=str(inventory.member_count)),
                Cell(text=str(inventory.personal_key_count)),
                Cell(text=inventory.background_work.summary()),
            )
        )
        for inventory in inventories
    ]
    return Table(
        columns=("Organization", "ID", "What happens", "Members", "Personal API keys", "Background work"),
        rows=tuple(rows),
        numeric_columns=(3, 4),
    )


def result_page(results: Sequence[ShutdownResult], notices: Sequence[Notice] = ()) -> Page:
    deactivated = sum(result.deactivated for result in results)
    stopped_count = sum(len(work.ids) for result in results for work in result.stopped)
    failures = [(result, failure) for result in results for failure in result.failures]
    summary = (
        f"Deactivated {pluralize(deactivated, 'organization')} and stopped {pluralize(stopped_count, 'item')} "
        "of background work. Reactivating an organization does not restart them. Copy this list now: "
        f"the page shows once, and the {AUDIT_EVENT} event in the audit log keeps the same IDs."
    )
    stopped_rows: list[Row | GroupRow] = []
    for result in results:
        if not result.stopped:
            continue
        stopped_rows.append(
            GroupRow(
                text=result.name,
                detail=str(result.organization_id),
                href=_organization_url(result.organization_id),
            )
        )
        stopped_rows += [
            Row(cells=(Cell(text=work.label), Cell(text=resource_id, mono=True)))
            for work in result.stopped
            for resource_id in work.ids
        ]
    blocks: list[Notice | Table] = [Notice(text=summary)]
    if failures:
        blocks.append(
            Notice(
                text=(
                    f"{pluralize(len(failures), 'item')} failed. A failure can come after the change was saved, so "
                    "check each one. Run the shutdown again to retry the ones still running, or ask the team that "
                    "owns them."
                ),
                tone=Tone.WARNING,
            )
        )
        blocks.append(
            Table(
                title="Failed",
                columns=("Organization", "Kind", "ID", "Error"),
                rows=tuple(
                    Row(
                        cells=(
                            Cell(text=result.name),
                            Cell(text=failure.label),
                            Cell(text=failure.resource_id or "Could not list them", mono=bool(failure.resource_id)),
                            Cell(text=failure.error),
                        )
                    )
                    for result, failure in failures
                ),
            )
        )
    blocks.append(
        Table(
            title="Stopped",
            columns=("Kind", "ID"),
            rows=tuple(stopped_rows),
            empty_text="Nothing was running, so nothing was stopped.",
        )
    )
    blocks += notices
    return Page(blocks=tuple(blocks))
