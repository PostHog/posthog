import json
from typing import cast
from uuid import UUID

from django import forms
from django.conf import settings
from django.contrib import messages
from django.http import HttpRequest, HttpResponse, QueryDict
from django.urls import reverse

from posthog.admin.console.panels import Owner, Tone
from posthog.admin.console.registry import console
from posthog.admin.console.tools import Cell, ConsoleTool, Notice, Page, Row, Table, ToolOperation
from posthog.models.user import User

from products.data_modeling.backend.facade.api import (
    clear_suspension_markers,
    find_suspension_markers,
    get_dag_tier_report,
)
from products.data_modeling.backend.facade.contracts import (
    DagTierReport,
    SuspensionMarkerKey,
    SuspensionMarkerSummary,
    SuspensionSelection,
    SuspensionSelectionTooBroadError,
    TierSummary,
)
from products.data_modeling.backend.facade.models import DataModelingJobEngine

DATA_MODELING = Owner(name="Data modeling", crest="data-modeling")

NODE_STATUS_TONES = {
    "ok": Tone.SUCCESS,
    "failed": Tone.DESTRUCTIVE,
    "suspended": Tone.WARNING,
    "cancelled": Tone.WARNING,
    "missing": Tone.WARNING,
    "running": Tone.INFO,
    "blocked": Tone.DEFAULT,
    "not_materializing": Tone.DEFAULT,
}


class ClearNodeSuspensionsForm(forms.Form):
    engine = forms.ChoiceField(
        choices=[("", "All engines"), *DataModelingJobEngine.choices], required=False, initial="clickhouse"
    )
    reason_contains = forms.CharField(
        label="Error text contains",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Case-sensitive. Enter one error text per line to match any of them.",
    )
    team_id = forms.IntegerField(label="Team ID", required=False, min_value=1)
    node_ids = forms.CharField(label="Node IDs", required=False, help_text="Comma-separated UUIDs.")
    saved_query_ids = forms.CharField(label="Saved query IDs", required=False, help_text="Comma-separated UUIDs.")
    suspended_from = forms.DateTimeField(
        required=False, help_text="Inclusive. Use an ISO date and time with a UTC offset."
    )
    suspended_to = forms.DateTimeField(
        required=False, help_text="Exclusive. Use an ISO date and time with a UTC offset."
    )
    by = forms.CharField(
        label="By / note",
        required=False,
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Optional. Explain why you are clearing these suspensions. Leave empty to use your admin user ID.",
    )
    # The preview fills this with the markers it showed, and the signed confirm token carries them. The confirm
    # step clears only those, so a model that suspends again or for the first time after the preview keeps its
    # suspension.
    previewed_markers = forms.CharField(widget=forms.HiddenInput, required=False)

    def _uuid_list(self, field: str) -> tuple[UUID, ...]:
        try:
            return tuple(UUID(item.strip()) for item in self.cleaned_data[field].split(",") if item.strip())
        except ValueError:
            raise forms.ValidationError("Enter valid comma-separated UUIDs.")

    def clean_node_ids(self) -> tuple[UUID, ...]:
        return self._uuid_list("node_ids")

    def clean_saved_query_ids(self) -> tuple[UUID, ...]:
        return self._uuid_list("saved_query_ids")

    def clean_previewed_markers(self) -> tuple[SuspensionMarkerKey, ...]:
        raw = self.cleaned_data["previewed_markers"]
        if not raw:
            return ()
        try:
            return tuple(
                SuspensionMarkerKey(node_id=UUID(item["node_id"]), engine=item["engine"], at=item["at"])
                for item in json.loads(raw)
            )
        except (TypeError, KeyError, ValueError):
            raise forms.ValidationError("The previewed suspensions could not be read. Preview again.")

    def record_preview(self, markers: list[SuspensionMarkerSummary]) -> None:
        assert isinstance(self.data, QueryDict)
        data = self.data.copy()
        data["previewed_markers"] = json.dumps(
            [{"node_id": str(marker.node_id), "engine": marker.engine, "at": marker.at} for marker in markers]
        )
        self.data = data

    def clean(self) -> dict:
        cleaned = super().clean()
        assert cleaned is not None
        reasons = tuple(line for line in cleaned.get("reason_contains", "").splitlines() if line.strip())
        cleaned["reason_contains"] = reasons
        if not (reasons or cleaned.get("node_ids") or cleaned.get("saved_query_ids")):
            raise forms.ValidationError("Enter error text, node IDs, or saved query IDs to select suspensions.")
        start, end = cleaned.get("suspended_from"), cleaned.get("suspended_to")
        if start and end and start >= end:
            raise forms.ValidationError("Suspended to must be after suspended from.")
        return cleaned

    def selection(self) -> SuspensionSelection:
        data = self.cleaned_data
        return SuspensionSelection(
            team_id=data["team_id"],
            node_ids=data["node_ids"],
            saved_query_ids=data["saved_query_ids"],
            engine=data["engine"] or None,
            reason_contains=data["reason_contains"],
            suspended_from=data["suspended_from"],
            suspended_to=data["suspended_to"],
        )

    def resumed_by(self, request: HttpRequest) -> str:
        return self.cleaned_data["by"] or f"admin:{cast(User, request.user).pk}"


def _team_url(team_id: int) -> str:
    return reverse("admin_console_team", kwargs={"pk": team_id})


def preview_suspensions(request: HttpRequest, form: forms.Form) -> Page:
    assert isinstance(form, ClearNodeSuspensionsForm)
    try:
        markers = find_suspension_markers(form.selection())
    except SuspensionSelectionTooBroadError as error:
        form.add_error(None, str(error))
        return Page(blocks=())
    if not markers:
        form.add_error(None, "No suspensions match this selection.")
        return Page(blocks=())
    form.record_preview(markers)
    return Page(
        blocks=(
            Notice(
                text=(
                    f"{len(markers)} matching suspension(s). New or changed suspensions will not be cleared. "
                    f"Other engines will keep their suspensions. By / note: {form.resumed_by(request)}"
                )
            ),
            Table(
                columns=("Team", "Node", "Node ID", "Saved query", "Engine", "Suspended at", "Error"),
                rows=tuple(
                    Row(
                        cells=(
                            Cell(text=str(marker.team_id), href=_team_url(marker.team_id)),
                            Cell(text=marker.node_name),
                            Cell(text=str(marker.node_id), mono=True),
                            Cell(text=str(marker.saved_query_id or "None"), mono=True),
                            Cell(text=marker.engine),
                            Cell(text=marker.at),
                            Cell(text=marker.reason),
                        )
                    )
                    for marker in markers
                ),
            ),
        )
    )


def clear_suspensions(request: HttpRequest, form: forms.Form | None) -> HttpResponse | None:
    assert isinstance(form, ClearNodeSuspensionsForm)
    result = clear_suspension_markers(
        form.cleaned_data["previewed_markers"], resumed_by=form.resumed_by(request), user_id=cast(User, request.user).pk
    )
    messages.success(
        request,
        f"Cleared {result.cleared} suspension(s). Left {result.skipped} suspension(s) that changed or no longer exist.",
    )
    return None


@console.register_tool
class ClearNodeSuspensionsTool(ConsoleTool):
    key = "clear-node-suspensions"
    title = "Clear node suspensions"
    owner = DATA_MODELING
    group = "Data"
    description = "Clears suspensions of data modeling nodes in this region, so their models run again."

    def page(self, request: HttpRequest) -> Page:
        return Page(
            blocks=(
                Notice(
                    text=(
                        "Select suspensions in this region and review the matches before clearing them. Models "
                        "can run on their next scheduled run. Clearing does not start a run."
                    )
                ),
            )
        )

    def operations(self, request: HttpRequest) -> list[ToolOperation]:
        return [
            ToolOperation(
                key="clear",
                label="Clear suspensions",
                handler=clear_suspensions,
                description="Clears the selected suspensions, so the models run on their next scheduled run.",
                form_class=ClearNodeSuspensionsForm,
                preview=preview_suspensions,
            )
        ]


class TemporalLinks:
    @staticmethod
    def url(path: str) -> str | None:
        if not settings.TEMPORAL_UI_HOST:
            return None
        return f"{settings.TEMPORAL_UI_HOST}/namespaces/{settings.TEMPORAL_NAMESPACE}/{path}"


def _link_cell(text: str, path: str | None) -> Cell:
    href = TemporalLinks.url(path) if path is not None else None
    if href is None:
        return Cell(text="—", muted=True)
    return Cell(text=text, href=href)


def _tier_summary(report: DagTierReport) -> Table:
    rows = []
    for tier in report.tiers:
        counts = dict(tier.counts)
        if tier.parent_workflow_id:
            last_run = f"{'legacy ' if tier.run_is_legacy else ''}{tier.started_at}"
        else:
            last_run = "never ran"
        rows.append(
            Row(
                cells=(
                    Cell(text=tier.label),
                    _link_cell("schedule ↗", f"schedules/execute-dag-{tier.schedule_id}"),
                    Cell(text=str(tier.declared)),
                    Cell(text=str(tier.ran)),
                    Cell(text=str(counts["ok"])),
                    Cell(text=str(counts["failed"])),
                    Cell(text=str(counts["running"])),
                    Cell(text=str(counts["cancelled"])),
                    Cell(text=str(counts["suspended"])),
                    Cell(text=str(counts["blocked"])),
                    Cell(text=str(counts["missing"])),
                    Cell(text=str(counts["not_materializing"])),
                    Cell(text=last_run),
                    _link_cell(
                        "workflow ↗", f"workflows/{tier.parent_workflow_id}" if tier.parent_workflow_id else None
                    ),
                )
            )
        )
    return Table(
        columns=(
            "Tier",
            "Schedule",
            "Declared",
            "Ran",
            "OK",
            "Failed",
            "Running",
            "Cancelled",
            "Suspended",
            "Blocked",
            "No job",
            "Non-materializing",
            "Last run",
            "Run",
        ),
        rows=tuple(rows),
        empty_text="No node on this DAG declares a freshness target, so it has no tiers.",
    )


def _tier_run_notice(tier: TierSummary) -> Notice:
    heading = f"{tier.label}: {tier.declared} materializing node(s)."
    if tier.run_is_legacy:
        return Notice(
            text=(
                f"{heading} This DAG has no schedule for this tier. The statuses below come from its pre-tier "
                f"single DAG-wide schedule, {tier.parent_workflow_id}, started {tier.started_at}, so the nodes "
                "may be materializing, only not on a per-tier schedule."
            )
        )
    if tier.parent_workflow_id:
        return Notice(text=f"{heading} Last run {tier.parent_workflow_id} started {tier.started_at}.")
    return Notice(
        text=f"{heading} This tier has never produced a job. Its schedule does not exist or has not fired yet."
    )


def _tier_nodes(tier: TierSummary) -> Table:
    return Table(
        columns=("Node", "Type", "Status", "Detail", "Run"),
        rows=tuple(
            Row(
                cells=(
                    Cell(text=node.name),
                    Cell(text=node.node_type),
                    Cell(text=node.status, tone=NODE_STATUS_TONES.get(node.status, Tone.DEFAULT)),
                    Cell(text=node.detail, muted=True),
                    _link_cell(
                        "workflow ↗",
                        f"workflows/{node.workflow_id}/{node.workflow_run_id}" if node.workflow_id else None,
                    ),
                )
            )
            for node in tier.nodes
        ),
    )


def dag_tiers_page(report: DagTierReport) -> Page:
    interval = report.sync_frequency_interval or "—"
    blocks: list = [
        Notice(
            text=f"DAG {report.dag_name} ({report.dag_id}), team {report.team_name} ({report.team_id}). "
            f"DAG interval {interval}.",
            link_text="Open the team",
            href=_team_url(report.team_id),
        ),
        _tier_summary(report),
    ]
    for tier in report.tiers:
        blocks.extend((_tier_run_notice(tier), _tier_nodes(tier)))
    if report.untargeted:
        blocks.append(
            Notice(
                text=(
                    f"No declared target ({len(report.untargeted)}). These nodes belong to no tier, so no schedule "
                    "fires them. Source tables are expected here. A matview or endpoint is not."
                )
            )
        )
        blocks.append(
            Table(
                columns=("Node", "Type"),
                rows=tuple(Row(cells=(Cell(text=node.name), Cell(text=node.node_type))) for node in report.untargeted),
            )
        )
    return Page(blocks=tuple(blocks))


class DagIdParam:
    @staticmethod
    def parse(request: HttpRequest) -> UUID | None:
        try:
            return UUID(request.GET.get("dag", "").strip())
        except ValueError:
            return None


@console.register_tool
class DagTiersTool(ConsoleTool):
    key = "dag-tiers"
    title = "DAG schedule tiers"
    owner = DATA_MODELING
    group = "Data"
    description = "What each cadence tier of a data modeling DAG holds, and what its last run did."

    def page(self, request: HttpRequest) -> Page:
        dag_id = DagIdParam.parse(request)
        report = get_dag_tier_report(dag_id) if dag_id is not None else None
        if report is None:
            return Page(
                blocks=(
                    Notice(
                        text="Open this page from the Tiers link of a DAG in Django admin.",
                        link_text="Find a DAG",
                        href="/admin/data_modeling/dag/",
                    ),
                )
            )
        return dag_tiers_page(report)


console.register_moved_page(
    old_path="admin/data_modeling/dag/clear-suspensions/",
    title="Clearing node suspensions",
    url="/admin/console/tools/clear-node-suspensions/",
)
console.register_moved_page(
    old_path="admin/data_modeling/dag/<str:dag_id>/tiers/",
    title="DAG schedule tiers",
    url="/admin/console/tools/dag-tiers/?dag={dag_id}",
)
