import json
from datetime import UTC, datetime
from typing import Any, ClassVar, cast

from django import forms
from django.contrib import messages
from django.contrib.admin.models import ADDITION, CHANGE, LogEntry
from django.contrib.admin.utils import construct_change_message
from django.db import transaction
from django.db.models import Model
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.defaultfilters import filesizeformat
from django.utils import timezone

from posthog.admin.console.deletion_request_form import (
    UNSUPPORTED_REQUEST_TYPES,
    DataDeletionRequestForm,
    initial_from_query,
)
from posthog.admin.console.panels import MAX_FACTS_PER_PANEL, Fact, Gate, Operation, Owner, Panel, ReasonForm, Tone
from posthog.admin.console.records import RECORD_TYPES, request_type_label
from posthog.admin.console.registry import console
from posthog.admin.console.tools import Cell, ConsoleTool, Notice, Page, Row, Table, ToolOperation
from posthog.dataclasses import frozen
from posthog.models.data_deletion_request import (
    AUTO_APPROVE_INTERVAL_MINUTES,
    AUTO_APPROVE_MAX_EVENTS,
    EDITABLE_STATUSES,
    DataDeletionRequest,
    ExecutionMode,
    RequestStatus,
    RequestType,
    StaffEditNotice,
    count_adhoc_event_deletion_backlog,
    count_remaining_for_request,
    fetch_deletion_stats,
    refresh_deletion_stats,
)
from posthog.models.team.team import Team
from posthog.models.user import User

CLICKHOUSE = Owner(name="ClickHouse", crest="clickhouse", staff_group="ClickHouse Team")

STATUS_TONES = {
    RequestStatus.PENDING: Tone.INFO,
    RequestStatus.APPROVED: Tone.INFO,
    RequestStatus.IN_PROGRESS: Tone.INFO,
    RequestStatus.QUEUED: Tone.INFO,
    RequestStatus.COMPLETED: Tone.SUCCESS,
    RequestStatus.FAILED: Tone.DESTRUCTIVE,
}

# The first mode is the default. Query-backed removals only work deferred, and only event removals can be deferred.
EXECUTION_MODES = {
    RequestType.EVENT_REMOVAL: (ExecutionMode.DEFERRED, ExecutionMode.IMMEDIATE),
    RequestType.HOGQL_EVENT_REMOVAL: (ExecutionMode.DEFERRED,),
    RequestType.PERSON_REMOVAL: (ExecutionMode.IMMEDIATE,),
    RequestType.PROPERTY_REMOVAL: (ExecutionMode.IMMEDIATE,),
}
EXECUTION_MODE_EFFECTS = {
    ExecutionMode.DEFERRED: "Queues the matching event UUIDs. The scheduled deletes job removes them with other batched deletes.",
    ExecutionMode.IMMEDIATE: "Starts a delete on each shard right away.",
}


def _when(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _number(value: int | None) -> str:
    return "-" if value is None else f"{value:,}"


def _log_change(
    request: HttpRequest, obj: DataDeletionRequest, message: str | list[dict], action_flag: int = CHANGE
) -> None:
    # The same entry ModelAdmin.log_change writes, so the history on the Django admin page stays complete.
    LogEntry.objects.log_actions(
        user_id=cast(User, request.user).pk,
        queryset=[obj],
        action_flag=action_flag,
        change_message=message,
        single_object=True,
    )


def _missing_criteria(obj: DataDeletionRequest) -> str | None:
    """What the request lacks before it can be submitted, or None when it is complete."""
    if obj.request_type == RequestType.PROPERTY_REMOVAL and not obj.properties and not obj.person_properties:
        return "Add at least one property or person property."
    if obj.request_type == RequestType.PERSON_REMOVAL:
        if not (obj.person_uuids or obj.person_distinct_ids):
            return "Add at least one person UUID or distinct ID."
        if not (obj.person_drop_profiles or obj.person_drop_events or obj.person_drop_recordings):
            return "Set at least one drop flag: profiles, events or recordings."
    return None


def _criteria_lookup(revision: datetime | None) -> dict[str, Any]:
    if revision is None:
        return {"criteria_updated_at__isnull": True}
    return {"criteria_updated_at": revision}


def _person_selector_count(obj: DataDeletionRequest) -> int:
    # Person removals have no ClickHouse count query, so their stats count the selectors.
    return len(obj.person_uuids) + len(obj.person_distinct_ids)


@console.register_panel
class DeletionRequestOverviewPanel(Panel):
    record = "deletion-request"
    key = "overview"
    title = "Overview"
    owner = CLICKHOUSE
    order = 10

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, DataDeletionRequest)
        team = Team.objects.filter(pk=obj.team_id).only("id", "name").first()
        if team is None:
            team_fact = Fact(label="Team", value=f"Team {obj.team_id} no longer exists", tone=Tone.WARNING)
        else:
            team_fact = Fact(label="Team", value=f"{team.name} ({team.pk})", href=RECORD_TYPES["team"].url(team))
        if obj.approved_automatically:
            approved = f"Automatically, {_when(obj.approved_at)}"
        elif obj.approved:
            approver = obj.approved_by.email if obj.approved_by else "a deleted user"
            approved = f"By {approver}, {_when(obj.approved_at)}"
        else:
            approved = "Not yet"
        facts = [
            Fact(label="Status", value=obj.get_status_display(), tone=STATUS_TONES.get(RequestStatus(obj.status))),
            Fact(label="Type", value=request_type_label(obj)),
            team_fact,
            Fact(label="Requires approval", value="Yes" if obj.requires_approval else "No"),
            Fact(label="Approved", value=approved),
            Fact(
                label="Execution mode",
                value=obj.get_execution_mode_display() if obj.approved else "Chosen at approval",
            ),
            Fact(label="Attempts", value=str(obj.attempt_count)),
        ]
        if obj.last_dagster_run_id:
            # Facts link within PostHog only. The Django admin page links to the run in Dagster.
            facts.append(Fact(label="Last Dagster run", value=obj.last_dagster_run_id, mono=True))
        return facts


def fetch_stats(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert isinstance(obj, DataDeletionRequest)
    if obj.request_type == RequestType.PERSON_REMOVAL:
        obj.count = _person_selector_count(obj)
        obj.stats_calculated_at = timezone.now()
        obj.save(update_fields=["count", "stats_calculated_at", "updated_at"])
        _log_change(request, obj, "Counted person_removal selectors.")
        messages.success(request, f"Selector count: {obj.count} person targets.")
        return None
    try:
        stats = refresh_deletion_stats(obj, user_id=request.user.pk)
    except Exception as error:
        messages.error(request, f"Could not fetch stats: {error}")
        return HttpResponse(status=502)
    _log_change(request, obj, "Fetched ClickHouse stats.")
    messages.success(request, f"Stats fetched: {stats['count']:,} matching events.")
    return None


def preview_stats(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert isinstance(obj, DataDeletionRequest)
    if obj.request_type == RequestType.PERSON_REMOVAL:
        messages.info(request, f"Selector count: {_person_selector_count(obj)} person targets. Not saved.")
        return None
    try:
        stats = fetch_deletion_stats(obj, user_id=request.user.pk)
    except Exception as error:
        messages.error(request, f"Could not preview stats: {error}")
        return HttpResponse(status=502)
    messages.info(
        request,
        f"{stats['count']:,} matching events, from {_when(stats['min_timestamp'])} to {_when(stats['max_timestamp'])}. "
        f"{_number(stats['part_count'])} parts, {filesizeformat(stats['parts_size'] or 0)}, "
        f"{_number(stats['parts_row_count'])} rows in those parts. Not saved to the request.",
    )
    return None


@console.register_panel
class DeletionRequestStatsPanel(Panel):
    record = "deletion-request"
    key = "stats"
    title = "ClickHouse stats"
    owner = CLICKHOUSE
    order = 20

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, DataDeletionRequest)
        if obj.stats_calculated_at is None:
            return [Fact(label="Stats", value="Not fetched yet")]
        return [
            Fact(label="Matching events", value=_number(obj.count)),
            Fact(label="Parts", value=_number(obj.part_count)),
            Fact(label="Parts size", value=filesizeformat(obj.parts_size or 0)),
            Fact(label="Rows in those parts", value=_number(obj.parts_row_count)),
            Fact(label="Earliest event", value=_when(obj.min_timestamp)),
            Fact(label="Latest event", value=_when(obj.max_timestamp)),
            Fact(label="Calculated", value=_when(obj.stats_calculated_at)),
        ]

    def operations(self, obj: Model) -> list[Operation]:
        return [
            Operation(
                key="fetch",
                label="Fetch stats",
                handler=fetch_stats,
                description="Counts the matching events in ClickHouse and saves the numbers on the request.",
            ),
            Operation(
                key="preview",
                label="Preview stats",
                handler=preview_stats,
                description="Counts the matching events without saving, for example while you change the criteria.",
                gate=Gate.owner(),
            ),
        ]


class AutoApprovableSubmitForm(ReasonForm):
    requires_approval = forms.BooleanField(
        required=False, label="Do not approve automatically. Send it to the ClickHouse Team instead."
    )
    field_order = ["requires_approval", "reason"]


def submit(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert isinstance(obj, DataDeletionRequest) and form is not None
    # Only event removals are offered the opt-out. Every other type still records True: the field means
    # "a human must approve this", and False would hide the request from the changelist's "requires approval"
    # filter, on precisely the requests a reviewer needs to find.
    requires_approval = not isinstance(form, AutoApprovableSubmitForm) or form.cleaned_data["requires_approval"]
    updated = DataDeletionRequest.objects.filter(pk=obj.pk, status=RequestStatus.DRAFT).update(
        status=RequestStatus.PENDING, requires_approval=requires_approval, updated_at=timezone.now()
    )
    if not updated:
        messages.error(request, "The request is no longer a draft.")
        return HttpResponse(status=409)
    obj.refresh_from_db()
    _log_change(request, obj, "Submitted: status changed from draft to pending.")
    if requires_approval:
        messages.success(request, "Request submitted. It waits for approval by the ClickHouse Team.")
    else:
        messages.success(
            request,
            f"Request submitted. The auto-approval job checks it within {AUTO_APPROVE_INTERVAL_MINUTES} minutes and "
            f"approves it if it matches fewer than {AUTO_APPROVE_MAX_EVENTS:,} events.",
        )
    return None


class ApproveForm(ReasonForm):
    execution_mode = forms.ChoiceField(label="Execution mode", choices=ExecutionMode.choices)
    # Which edit of the criteria staff reviewed. The approval only lands on that edit.
    criteria_revision = forms.CharField(required=False, widget=forms.HiddenInput)
    field_order = ["execution_mode", "reason"]

    modes: ClassVar[tuple[ExecutionMode, ...]] = tuple(ExecutionMode)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        mode_field = self.fields["execution_mode"]
        assert isinstance(mode_field, forms.ChoiceField)
        mode_field.choices = [(mode.value, mode.label) for mode in self.modes]
        mode_field.help_text = " ".join(f"{mode.label}: {EXECUTION_MODE_EFFECTS[mode]}" for mode in self.modes)

    def clean_criteria_revision(self) -> datetime | None:
        value = self.cleaned_data["criteria_revision"]
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            raise forms.ValidationError("Open the form again from the request page.")

    @classmethod
    def for_request(cls, obj: DataDeletionRequest) -> type["ApproveForm"]:
        modes = EXECUTION_MODES[RequestType(obj.request_type)]
        return type("ApproveForm", (cls,), {"modes": modes})


# The preview names the actual targets, so two requests with the same counts never look alike. Past this many it
# counts the rest, and the Django admin page has the full list.
MAX_LISTED_TARGETS = 20


def _listed(values: list[str]) -> str:
    if not values:
        return ""
    shown = ", ".join(values[:MAX_LISTED_TARGETS])
    hidden = len(values) - MAX_LISTED_TARGETS
    return f"{shown} and {hidden:,} more" if hidden > 0 else shown


@frozen
class Criterion:
    label: str
    value: str


def _criteria_values(obj: DataDeletionRequest) -> list[Criterion]:
    criteria = [
        ("Type", request_type_label(obj)),
        ("Team", str(obj.team_id)),
        ("Time range", f"{_when(obj.start_time)} to {_when(obj.end_time)}"),
        ("Events", "All events" if obj.delete_all_events else ", ".join(obj.events)),
        ("Properties", ", ".join(obj.properties)),
        ("Person properties", ", ".join(obj.person_properties or [])),
        ("HogQL filter", obj.hogql_predicate),
        ("HogQL query", obj.hogql_query),
        ("HogQL variables", json.dumps(obj.hogql_variables, sort_keys=True) if obj.hogql_variables else ""),
        ("Person UUIDs", _listed([str(uuid) for uuid in obj.person_uuids])),
        ("Person distinct IDs", _listed(obj.person_distinct_ids)),
    ]
    if obj.request_type == RequestType.PERSON_REMOVAL:
        dropped = [
            name
            for name, flag in (
                ("profiles", obj.person_drop_profiles),
                ("events", obj.person_drop_events),
                ("recordings", obj.person_drop_recordings),
            )
            if flag
        ]
        criteria.append(("Drops", ", ".join(dropped)))
    return [Criterion(label=label, value=value) for label, value in criteria if value]


def _criteria_rows(obj: DataDeletionRequest) -> list[Row]:
    return [
        Row(cells=(Cell(text=criterion.label), Cell(text=criterion.value, mono=True)))
        for criterion in _criteria_values(obj)
    ]


def _stats_block(obj: DataDeletionRequest) -> Notice | Table:
    if obj.stats_calculated_at is None:
        return Notice(text="No stats were fetched for these criteria. Fetch stats before you approve.")
    rows = [
        ("Matching events", _number(obj.count)),
        ("Parts", _number(obj.part_count)),
        ("Parts size", filesizeformat(obj.parts_size or 0)),
        ("Calculated", _when(obj.stats_calculated_at)),
    ]
    return Table(columns=("Stored stats", ""), rows=tuple(Row(cells=(Cell(text=k), Cell(text=v))) for k, v in rows))


def _backlog_notice(obj: DataDeletionRequest) -> Notice:
    # The backlog only informs the approver, so a ClickHouse failure must not block approval.
    try:
        backlog = count_adhoc_event_deletion_backlog(obj.team_id)
    except Exception as error:
        return Notice(text=f"Could not count the events already queued for deletion: {error}")
    return Notice(
        text=f"{backlog.total:,} events are queued for deletion and not deleted yet, "
        f"{backlog.for_team:,} of them for team {obj.team_id}."
    )


def preview_approval(request: HttpRequest, obj: Model, form: forms.Form) -> Page:
    assert isinstance(obj, DataDeletionRequest)
    if form.cleaned_data["criteria_revision"] != obj.criteria_updated_at:
        form.add_error(None, "The criteria changed since you opened this form. Review them again.")
        return Page(blocks=())
    mode = ExecutionMode(form.cleaned_data["execution_mode"])
    return Page(
        blocks=(
            Notice(text=f"Execution mode: {mode.label}. {EXECUTION_MODE_EFFECTS[mode]}"),
            Table(columns=("Criteria", ""), rows=tuple(_criteria_rows(obj))),
            _stats_block(obj),
            _backlog_notice(obj),
        )
    )


def approve(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert isinstance(obj, DataDeletionRequest) and form is not None
    execution_mode = form.cleaned_data["execution_mode"]
    now = timezone.now()
    updated = DataDeletionRequest.objects.filter(
        pk=obj.pk, status=RequestStatus.PENDING, **_criteria_lookup(form.cleaned_data["criteria_revision"])
    ).update(
        status=RequestStatus.APPROVED,
        approved=True,
        approved_by=request.user,
        approved_at=now,
        execution_mode=execution_mode,
        updated_at=now,
    )
    if not updated:
        messages.error(request, "The request changed since you reviewed it, so it was not approved. Review it again.")
        return HttpResponse(status=409)
    obj.refresh_from_db()
    _log_change(request, obj, f"Approved deletion request (execution_mode={execution_mode}).")
    messages.success(request, f"Deletion request approved ({obj.get_execution_mode_display()}).")
    return None


def revert_to_draft(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert isinstance(obj, DataDeletionRequest)
    updated = DataDeletionRequest.objects.filter(
        pk=obj.pk, status__in=[RequestStatus.PENDING, RequestStatus.APPROVED]
    ).update(
        status=RequestStatus.DRAFT,
        approved=False,
        approved_automatically=False,
        approved_by=None,
        approved_at=None,
        updated_at=timezone.now(),
    )
    if not updated:
        messages.error(request, "Only pending or approved requests can move back to draft.")
        return HttpResponse(status=409)
    obj.refresh_from_db()
    _log_change(request, obj, "Reverted to draft: cleared approval.")
    messages.success(request, "Request moved back to draft.")
    return None


def retry(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert isinstance(obj, DataDeletionRequest)
    # Keeps approved_by and approved_at: the retry runs the same approval again. The job bumps attempt_count
    # and last_executed_at when it starts.
    updated = DataDeletionRequest.objects.filter(pk=obj.pk, status=RequestStatus.FAILED).update(
        status=RequestStatus.APPROVED, updated_at=timezone.now()
    )
    if not updated:
        messages.error(request, "Only failed requests can be retried.")
        return HttpResponse(status=409)
    obj.refresh_from_db()
    _log_change(request, obj, f"Retry triggered (attempt #{obj.attempt_count + 1}): status FAILED → APPROVED.")
    messages.success(request, "Request requeued. The pickup sensor starts a new run on its next tick.")
    return None


def verify(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert isinstance(obj, DataDeletionRequest)
    # Read before counting, so a criteria edit during the count cannot mark the new criteria completed.
    revision = obj.criteria_updated_at
    prior_status = obj.status
    try:
        remaining = count_remaining_for_request(obj)
    except Exception as error:
        messages.error(request, f"Could not verify: {error}")
        return HttpResponse(status=502)
    if remaining:
        messages.warning(
            request,
            f"{remaining:,} matching rows are still in ClickHouse. The request stays "
            f"{obj.get_status_display().lower()}. Verify again after the next scheduled deletion.",
        )
        return None
    promoted = (
        DataDeletionRequest.objects.filter(pk=obj.pk, **_criteria_lookup(revision))
        .exclude(status=RequestStatus.COMPLETED)
        .update(status=RequestStatus.COMPLETED, updated_at=timezone.now())
    )
    if promoted:
        obj.refresh_from_db()
        _log_change(request, obj, f"Verified: 0 matching rows remain, status {prior_status} → completed.")
        messages.success(request, "Verified: no matching rows remain. Marked completed.")
        return None
    obj.refresh_from_db()
    if obj.status == RequestStatus.COMPLETED:
        messages.info(request, "Verified: no matching rows remain. It was already completed.")
        return None
    messages.error(request, "The criteria changed while verifying, so the request was not completed. Verify again.")
    return HttpResponse(status=409)


UNVERIFIABLE_TYPES = (RequestType.PERSON_REMOVAL, RequestType.HOGQL_EVENT_REMOVAL)


@console.register_panel
class DeletionRequestWorkflowPanel(Panel):
    record = "deletion-request"
    key = "workflow"
    title = "Workflow"
    owner = CLICKHOUSE
    operation_keys = frozenset({"submit", "approve", "revert-to-draft", "retry", "verify"})
    order = 30
    danger = True

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, DataDeletionRequest)
        facts = []
        missing = _missing_criteria(obj) if obj.status == RequestStatus.DRAFT else None
        if missing is not None:
            facts.append(Fact(label="Cannot submit", value=missing, tone=Tone.WARNING))
        if obj.request_type in UNVERIFIABLE_TYPES and obj.status != RequestStatus.COMPLETED:
            facts.append(
                Fact(
                    label="Verification",
                    value="Not automated for this request type. Verify manually.",
                )
            )
        return facts

    def operations(self, obj: Model) -> list[Operation]:
        assert isinstance(obj, DataDeletionRequest)
        operations = []
        if obj.status == RequestStatus.DRAFT and _missing_criteria(obj) is None:
            operations.append(self._submit(obj))
        if obj.status == RequestStatus.PENDING:
            operations.append(
                Operation(
                    key="approve",
                    label="Approve deletion",
                    handler=approve,
                    preview=preview_approval,
                    danger=True,
                    form_class=ApproveForm.for_request(obj),
                    form_initial={
                        "execution_mode": EXECUTION_MODES[RequestType(obj.request_type)][0].value,
                        "criteria_revision": obj.criteria_updated_at.isoformat() if obj.criteria_updated_at else "",
                    },
                    description="The deletion job picks up the request and deletes the matching data.",
                    undo_hint=(
                        "Until the deletion job picks it up, move the request back to draft. "
                        "Data that a run already deleted cannot be restored."
                    ),
                    gate=Gate.owner(),
                )
            )
        if obj.status in (RequestStatus.PENDING, RequestStatus.APPROVED):
            operations.append(
                Operation(
                    key="revert-to-draft",
                    label="Move back to draft",
                    handler=revert_to_draft,
                    description="Clears the approval, so the criteria can be edited again.",
                )
            )
        if obj.status == RequestStatus.FAILED:
            operations.append(
                Operation(
                    key="retry",
                    label="Retry deletion",
                    handler=retry,
                    danger=True,
                    form_class=ReasonForm,
                    description=(
                        f"Queues the request again after {obj.attempt_count} failed attempts. The original approval "
                        "stays."
                    ),
                    undo_hint=(
                        "Until the next run starts, move the request back to draft. Data that a run already "
                        "deleted cannot be restored."
                    ),
                    gate=Gate.owner(),
                )
            )
        if obj.status != RequestStatus.COMPLETED and obj.request_type not in UNVERIFIABLE_TYPES:
            operations.append(
                Operation(
                    key="verify",
                    label="Verify deletion",
                    handler=verify,
                    description="Counts the matching rows in ClickHouse. When none remain, the request is completed.",
                    gate=Gate.owner(),
                )
            )
        return operations

    def _submit(self, obj: DataDeletionRequest) -> Operation:
        # Staff usually explain the request in its notes, so the reason starts from them.
        form_initial: dict[str, object] | None = {"reason": obj.notes} if obj.notes.strip() else None
        if obj.request_type == RequestType.EVENT_REMOVAL:
            return Operation(
                key="submit",
                label="Submit for approval",
                handler=submit,
                # Unless staff tick the opt-out, the auto-approval job can approve it with no other human step.
                danger=True,
                form_class=AutoApprovableSubmitForm,
                form_initial=form_initial,
                undo_hint=(
                    "Until the deletion job picks it up, move the request back to draft. Data that a run already "
                    "deleted cannot be restored."
                ),
                description=(
                    f"Moves the request to pending. Every {AUTO_APPROVE_INTERVAL_MINUTES} minutes a job refreshes "
                    f"the stats of pending event removals, and approves those that match fewer than "
                    f"{AUTO_APPROVE_MAX_EVENTS:,} events and whose time range has ended. The rest wait for the "
                    "ClickHouse Team."
                ),
            )
        return Operation(
            key="submit",
            label="Submit for approval",
            handler=submit,
            form_class=ReasonForm,
            form_initial=form_initial,
            description=(
                "Moves the request to pending. Only event removals are approved automatically, so this one waits "
                "for the ClickHouse Team."
            ),
        )


def _show_notices(request: HttpRequest, notices: list[StaffEditNotice]) -> None:
    for notice in notices:
        if notice.warning:
            messages.warning(request, notice.text)
        else:
            messages.info(request, notice.text)


def _refuse_clickhouse_team_type(request: HttpRequest, form: DataDeletionRequestForm) -> HttpResponse | None:
    # The create form hides these types from everyone else, and the edit form cannot, because record forms are
    # built without the request. This check covers both, and a hand-built POST.
    staff_gate = Gate.owner().resolve(CLICKHOUSE)
    if not form.needs_clickhouse_team() or staff_gate.allows(request):
        return None
    form.add_error("request_type", f"Only {staff_gate.label} can pick this type.")
    return HttpResponse(status=400)


def create_request(request: HttpRequest, form: forms.Form | None) -> HttpResponse | Page | None:
    assert isinstance(form, DataDeletionRequestForm)
    refused = _refuse_clickhouse_team_type(request, form)
    if refused is not None:
        return refused
    obj = form.instance
    notices = obj.apply_staff_edit(cast(User, request.user), form.changed_data, is_new=True)
    obj.save()
    _log_change(request, obj, construct_change_message(form, [], add=True), action_flag=ADDITION)
    _show_notices(request, notices)
    messages.success(request, "Draft created. Fetch its stats, then submit it for approval.")
    return HttpResponseRedirect(RECORD_TYPES["deletion-request"].url(obj))


def edit_criteria(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert isinstance(obj, DataDeletionRequest) and isinstance(form, DataDeletionRequestForm)
    refused = _refuse_clickhouse_team_type(request, form)
    if refused is not None:
        return refused
    if not form.has_changed():
        messages.info(request, "Nothing changed.")
        return None
    change_message = construct_change_message(form, [], add=False)
    with transaction.atomic():
        # The lock makes a concurrent approval wait for this save, and then miss the request it moved to draft.
        current = (
            DataDeletionRequest.objects.select_for_update()
            .filter(pk=obj.pk)
            .values_list("status", "updated_at")
            .first()
        )
        if current is None or current[1].isoformat() != form.cleaned_data["revision"]:
            messages.error(request, "Someone changed the request since you opened this form. Reload it.")
            return HttpResponse(status=409)
        if current[0] not in EDITABLE_STATUSES:
            messages.error(request, "The request was approved or started since you opened this form. Reload it.")
            return HttpResponse(status=409)
        notices = obj.apply_staff_edit(cast(User, request.user), form.changed_data, is_new=False)
        obj.save()
    _log_change(request, obj, change_message)
    _show_notices(request, notices)
    messages.success(request, "Criteria saved.")
    return None


def duplicate(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert isinstance(obj, DataDeletionRequest)
    original_url = request.build_absolute_uri(RECORD_TYPES["deletion-request"].url(obj))
    copy = obj.duplicate_as_draft(
        cast(User, request.user), copy_note=f"Copy of data deletion request {obj.pk} ({original_url})."
    )
    _log_change(request, copy, [{"added": {}}], action_flag=ADDITION)
    messages.success(request, "Duplicated as a new draft. This is the copy.")
    return HttpResponseRedirect(RECORD_TYPES["deletion-request"].url(copy))


@console.register_panel
class DeletionRequestCriteriaPanel(Panel):
    record = "deletion-request"
    key = "criteria"
    title = "Criteria"
    owner = CLICKHOUSE
    order = 40

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, DataDeletionRequest)
        facts = [
            Fact(label=criterion.label, value=criterion.value, mono=True)
            for criterion in _criteria_values(obj)
            if criterion.label not in ("Type", "Team")
        ]
        if obj.criteria_updated_at is not None:
            editor = obj.criteria_updated_by.email if obj.criteria_updated_by else "a deleted user"
            facts.append(Fact(label="Last changed", value=f"By {editor}, {_when(obj.criteria_updated_at)}"))
        return facts[:MAX_FACTS_PER_PANEL]

    def operations(self, obj: Model) -> list[Operation]:
        assert isinstance(obj, DataDeletionRequest)
        operations = []
        if obj.status in EDITABLE_STATUSES:
            operations.append(
                Operation(
                    key="edit",
                    label="Edit criteria",
                    handler=edit_criteria,
                    form_class=DataDeletionRequestForm.for_request(obj),
                    description=(
                        "Changes what the request matches. A changed criterion clears the stats, and a pending "
                        "request goes back to draft."
                    ),
                )
            )
        operations.append(
            Operation(
                key="duplicate",
                label="Duplicate as a new draft",
                handler=duplicate,
                description="Creates a draft with the same criteria and opens it.",
                # A copy is a new request, so only ClickHouse Team members copy types the create form does not
                # offer everyone.
                gate=Gate.owner() if obj.request_type in UNSUPPORTED_REQUEST_TYPES else None,
            )
        )
        return operations


@console.register_tool
class NewDeletionRequestTool(ConsoleTool):
    key = "new-deletion-request"
    title = "New deletion request"
    owner = CLICKHOUSE
    group = "Data"
    description = "Creates a draft request to delete events, or properties from events, of one team."

    def page(self, request: HttpRequest) -> Page:
        return Page(
            blocks=(
                Notice(
                    text="A new request starts as a draft. Nothing is deleted until it is submitted and approved.",
                    link_text="All requests in Django admin",
                    href="/admin/posthog/datadeletionrequest/",
                ),
            )
        )

    def operations(self, request: HttpRequest) -> list[ToolOperation]:
        return [
            ToolOperation(
                key="create",
                label="Create deletion request",
                handler=create_request,
                form_class=DataDeletionRequestForm.for_staff(Gate.owner().resolve(self.owner).allows(request)),
                # Support links prefill the form, for example ?team_id=2&events=$pageview.
                form_initial={"request_type": RequestType.EVENT_REMOVAL.value, **initial_from_query(request.GET)},
                description="Creates a draft and opens it. Nothing is deleted yet.",
            )
        ]


for old, target in {
    "submit": "workflow/submit/",
    "approve": "workflow/approve/",
    "retry": "workflow/retry/",
    "revert-to-draft": "#panel-workflow",
    "verify": "#panel-workflow",
    "fetch-stats": "#panel-stats",
    "preview-stats": "#panel-stats",
}.items():
    console.register_moved_action(
        old_path=f"admin/posthog/datadeletionrequest/<uuid:pk>/{old}/", record="deletion-request", target=target
    )
console.register_moved_page(
    old_path="admin/posthog/datadeletionrequest/add/",
    title="Creating a deletion request",
    url="/admin/console/tools/new-deletion-request/create/",
)
