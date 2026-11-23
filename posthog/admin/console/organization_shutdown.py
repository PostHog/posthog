"""Shutting down an organization that abuses PostHog: deactivate it, then stop the work it runs in the background.

The bulk deactivation tool and the organization page both run `shut_down_organizations`, so the two entry points
cannot drift apart.
"""

import json
from collections.abc import Callable, Collection, Sequence
from functools import partial
from typing import Any
from urllib.parse import urlencode
from uuid import UUID, uuid4

from django import forms
from django.core.cache import caches
from django.db import transaction
from django.http import HttpRequest
from django.urls import reverse

import structlog

from posthog.admin.console.panels import Tone
from posthog.admin.console.records import RECORD_TYPES
from posthog.admin.console.tools import Cell, GroupRow, Row, Table
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
    f"this stopped. Turn each item back on by hand: the page that follows the shutdown and the {AUDIT_EVENT} event "
    "in the audit log list every stopped ID."
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


def deactivate_organizations(organization_ids: Sequence[UUID], reason: str) -> set[UUID]:
    """Deactivates each organization that is still active, and returns their IDs."""
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


def stop_organization_background_work(
    organization_id: UUID, *, deactivated: bool, reason: str, triggered_by: str
) -> ShutdownResult | None:
    """Stops what the organization runs in the background, and writes each stopped ID to the audit log, because
    reactivating an organization does not restart its work: staff turn it back on by hand. Nothing is deleted.

    None when the organization no longer exists.
    """
    organization = Organization.objects.only("id", "name").filter(id=organization_id).first()
    if organization is None:
        return None
    stopped, failures = _stop_background_work(organization)
    result = ShutdownResult(
        organization_id=organization.id,
        name=organization.name,
        deactivated=deactivated,
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
    return result


def shut_down_organizations(
    organization_ids: Sequence[UUID], *, reason: str, stop_background_work: bool, triggered_by: str
) -> list[ShutdownResult]:
    """Deactivates each organization that is still active with `reason`, and with `stop_background_work`, stops
    what every one of them runs in the background, the already inactive ones included, within this request."""
    deactivated = deactivate_organizations(organization_ids, reason)
    if not stop_background_work:
        organizations = Organization.objects.only("id", "name").in_bulk(organization_ids)
        return [
            ShutdownResult(
                organization_id=organization_id,
                name=organizations[organization_id].name,
                deactivated=organization_id in deactivated,
                stopped=(),
                failures=(),
            )
            for organization_id in organization_ids
            if organization_id in organizations
        ]
    results = [
        stop_organization_background_work(
            organization_id, deactivated=organization_id in deactivated, reason=reason, triggered_by=triggered_by
        )
        for organization_id in organization_ids
    ]
    return [result for result in results if result is not None]


@frozen
class ShutdownRun:
    total: int
    finished: bool
    crashed: bool
    results: tuple[ShutdownResult, ...]


class ShutdownRuns:
    """The progress of a bulk shutdown that a Celery task runs, kept in the cache as JSON for the tool page to follow.

    The audit log keeps every stopped ID for good, so the cache only has to outlive the time staff watch the run.
    """

    TTL_SECONDS = 7 * 24 * 60 * 60
    # The console's own alias reads from the primary, so the task never builds on a lagging replica's copy.
    CACHE_ALIAS = "admin_console_results"

    @staticmethod
    def _key(run_id: str) -> str:
        return f"admin_console_organization_shutdown_run:{run_id}"

    @classmethod
    def start(cls, run_id: str, *, total: int) -> bool:
        """False when the run already started, for example from a confirm submitted twice."""
        state = {"total": total, "finished": False, "crashed": False, "results": []}
        return caches[cls.CACHE_ALIAS].add(cls._key(run_id), json.dumps(state), cls.TTL_SECONDS)

    @classmethod
    def forget(cls, run_id: str) -> None:
        caches[cls.CACHE_ALIAS].delete(cls._key(run_id))

    @classmethod
    def record(cls, run_id: str, result: ShutdownResult) -> None:
        """Adds an organization's result. A task that runs again after a lost worker merges its items into the
        first pass's, because the first pass already stopped them and they no longer show as running."""

        def merge(state: dict[str, Any]) -> None:
            earlier = next(
                (entry for entry in state["results"] if entry["organization_id"] == str(result.organization_id)),
                None,
            )
            if earlier is None:
                state["results"].append(_result_json(result))
                return
            stopped = {label: list(ids) for label, ids in earlier["stopped"]}
            for work in result.stopped:
                stopped.setdefault(work.label, []).extend(work.ids)
            earlier["stopped"] = [[label, ids] for label, ids in stopped.items()]
            earlier["failures"] = _result_json(result)["failures"]

        cls._update(run_id, merge)

    @classmethod
    def finish(cls, run_id: str, *, crashed: bool = False) -> None:
        cls._update(run_id, lambda state: state.update(finished=True, crashed=crashed))

    @classmethod
    def _update(cls, run_id: str, change: Callable[[dict[str, Any]], object]) -> None:
        # Only the run's own task writes after the start, so a read and a write cannot race.
        raw = caches[cls.CACHE_ALIAS].get(cls._key(run_id))
        if raw is None:
            return
        state = json.loads(raw)
        change(state)
        caches[cls.CACHE_ALIAS].set(cls._key(run_id), json.dumps(state), cls.TTL_SECONDS)

    @classmethod
    def read(cls, run_id: str) -> ShutdownRun | None:
        raw = caches[cls.CACHE_ALIAS].get(cls._key(run_id))
        if raw is None:
            return None
        state = json.loads(raw)
        return ShutdownRun(
            total=state["total"],
            finished=state["finished"],
            crashed=state["crashed"],
            results=tuple(_result_from_json(result) for result in state["results"]),
        )


def _result_json(result: ShutdownResult) -> dict[str, Any]:
    return {
        "organization_id": str(result.organization_id),
        "name": result.name,
        "deactivated": result.deactivated,
        "stopped": [[work.label, list(work.ids)] for work in result.stopped],
        "failures": [[failure.label, failure.resource_id, failure.error] for failure in result.failures],
    }


def _result_from_json(state: dict[str, Any]) -> ShutdownResult:
    return ShutdownResult(
        organization_id=UUID(state["organization_id"]),
        name=state["name"],
        deactivated=state["deactivated"],
        stopped=tuple(StoppedWork(label=label, ids=tuple(ids)) for label, ids in state["stopped"]),
        failures=tuple(
            StopFailure(label=label, resource_id=resource_id, error=error)
            for label, resource_id, error in state["failures"]
        ),
    )


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


RUN_FOLLOW_UP = (
    "Reactivating an organization does not restart this work, and the "
    f"{AUDIT_EVENT} event in the audit log keeps every stopped ID. A failure can come after the change was "
    "saved, so check each failed item. Run the shutdown again to retry the ones still running."
)


def run_table(run: ShutdownRun) -> Table:
    stopped = sum(len(work.ids) for result in run.results for work in result.stopped)
    failed = sum(len(result.failures) for result in run.results)
    if run.crashed:
        title = f"Stopped early after {len(run.results)} of {run.total} organizations. Run the shutdown again."
    elif run.finished:
        title = f"Finished: stopped {pluralize(stopped, 'item')}, {failed} failed"
    else:
        title = f"Stopping background work: {len(run.results)} of {run.total} organizations done"
    rows: list[Row | GroupRow] = []
    for result in run.results:
        rows.append(
            GroupRow(
                text=result.name,
                detail=f"{result.organization_id} · {'deactivated' if result.deactivated else 'already inactive'}",
                href=_organization_url(result.organization_id),
            )
        )
        rows += [
            Row(
                cells=(
                    Cell(text=work.label),
                    Cell(text=resource_id, mono=True),
                    Cell(text="Stopped", tone=Tone.SUCCESS),
                    Cell(text=""),
                )
            )
            for work in result.stopped
            for resource_id in work.ids
        ]
        rows += [
            Row(
                cells=(
                    Cell(text=failure.label),
                    Cell(text=failure.resource_id or "Could not list them", mono=bool(failure.resource_id)),
                    Cell(text="Failed", tone=Tone.DESTRUCTIVE),
                    Cell(text=failure.error),
                )
            )
            for failure in result.failures
        ]
    return Table(
        title=title,
        columns=("Kind", "ID", "Status", "Error"),
        rows=tuple(rows),
        empty_text="No organization is done yet.",
    )


RUN_PAGE_PATH = "/admin/console/tools/bulk-deactivate-organizations/"


def run_page_url(run_id: str) -> str:
    return f"{RUN_PAGE_PATH}?{urlencode({'run': run_id})}"


def start_background_stop(
    run_id: str, organization_ids: Sequence[UUID], *, deactivated: set[UUID], reason: str, triggered_by: str
) -> bool:
    """Starts the job that stops the organizations' background work, once per run. False when the job could not be
    queued, which leaves the run free to start again."""
    # Deferred: the task module imports this module when it runs.
    from posthog.tasks.organization_shutdown import stop_organizations_background_work  # noqa: PLC0415

    if not ShutdownRuns.start(run_id, total=len(organization_ids)):
        return True
    try:
        stop_organizations_background_work.delay(
            run_id,
            [str(organization_id) for organization_id in organization_ids],
            [str(organization_id) for organization_id in deactivated],
            reason,
            triggered_by,
        )
    except Exception as error:
        capture_exception(error)
        ShutdownRuns.forget(run_id)
        return False
    return True


JOB_NOT_STARTED = (
    "Deactivated, but the job that stops background work could not start. Confirm the shutdown again to retry."
)


def run_id_of(request: HttpRequest) -> str:
    # The form nonce names the run, so a confirm submitted twice starts one run.
    try:
        return str(UUID(request.POST.get("form_nonce", "")))
    except ValueError:
        return str(uuid4())
