import json
import uuid
from datetime import datetime
from typing import Any

from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q, QuerySet
from django.http import HttpRequest, HttpResponse
from django.urls import reverse

from posthog.admin.console.deletion_request_panels import (
    CLICKHOUSE,
    EXECUTION_MODE_EFFECTS,
    EXECUTION_MODES,
    STATUS_TONES,
    ApprovalReasonForm,
    approve_reviewed,
    criteria_values,
)
from posthog.admin.console.panels import Gate, Tone
from posthog.admin.console.records import RECORD_TYPES, request_type_label
from posthog.admin.console.registry import console
from posthog.admin.console.tools import (
    Cell,
    ConsoleTool,
    FieldGroup,
    Filters,
    Notice,
    Page,
    Paging,
    Row,
    Stat,
    Stats,
    Table,
    TableSelect,
    ToolOperation,
)
from posthog.models.data_deletion_request import DataDeletionRequest, ExecutionMode, RequestStatus, RequestType
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.utils import pluralize

REQUESTS_PER_PAGE = 50
# Staff tick the requests on one page of the list, so one approval covers at most one page.
MAX_BULK_APPROVALS = REQUESTS_PER_PAGE
# The preview shows the start of each request's criteria. The request page shows all of them.
CRITERIA_PREVIEW_CHARS = 200

STATUS_COUNTS = (
    ("Drafts", (RequestStatus.DRAFT,), None),
    ("Waiting for approval", (RequestStatus.PENDING,), Tone.WARNING),
    ("Approved or running", (RequestStatus.APPROVED, RequestStatus.QUEUED, RequestStatus.IN_PROGRESS), Tone.INFO),
    ("Failed", (RequestStatus.FAILED,), Tone.DESTRUCTIVE),
)


CREATED_BY_STAFF = "staff"
CREATED_BY_NOT_STAFF = "not-staff"
# created_by_staff is null on old requests and on requests that a system job creates, such as the support ticket
# purge. The deletion pickup sensor queues null behind staff requests, so the filter counts null as not staff.
CREATED_BY_FILTERS = {
    CREATED_BY_STAFF: Q(created_by_staff=True),
    CREATED_BY_NOT_STAFF: Q(created_by_staff=False) | Q(created_by_staff__isnull=True),
}


def _sentence_case(label: str) -> str:
    return label if label.startswith("HogQL") else label.capitalize()


class DeletionRequestFilterForm(forms.Form):
    status = forms.ChoiceField(
        required=False,
        label="Status",
        choices=[("", "Any status"), *((value, _sentence_case(label)) for value, label in RequestStatus.choices)],
    )
    request_type = forms.ChoiceField(
        required=False,
        label="Type",
        choices=[("", "Any type"), *((value, _sentence_case(label)) for value, label in RequestType.choices)],
    )
    team_id = forms.IntegerField(required=False, min_value=1, label="Team ID")
    created_by = forms.ChoiceField(
        required=False,
        label="Created by",
        choices=[("", "Anyone"), (CREATED_BY_STAFF, "Staff"), (CREATED_BY_NOT_STAFF, "Not staff")],
    )


def _filtered_requests(form: DeletionRequestFilterForm) -> QuerySet[DataDeletionRequest]:
    requests = DataDeletionRequest.objects.order_by("-created_at")
    if not form.is_valid():
        return requests
    if status := form.cleaned_data["status"]:
        requests = requests.filter(status=status)
    if request_type := form.cleaned_data["request_type"]:
        requests = requests.filter(request_type=request_type)
    if team_id := form.cleaned_data["team_id"]:
        requests = requests.filter(team_id=team_id)
    if created_by := form.cleaned_data["created_by"]:
        requests = requests.filter(CREATED_BY_FILTERS[created_by])
    return requests


def _status_counts() -> Stats:
    counts = dict(DataDeletionRequest.objects.values_list("status").annotate(total=Count("id")))
    items = []
    for label, statuses, tone in STATUS_COUNTS:
        total = sum(counts.get(status.value, 0) for status in statuses)
        items.append(Stat(label=label, value=f"{total:,}", tone=tone if total else None))
    return Stats(items=tuple(items))


def _team_cell(team_id: int, team_names: dict[int, str]) -> Cell:
    name = team_names.get(team_id)
    if name is None:
        return Cell(text=f"Team {team_id}", detail="No longer exists", muted=True)
    return Cell(
        text=name, detail=f"Team {team_id}", href=reverse(RECORD_TYPES["team"].url_name, kwargs={"pk": team_id})
    )


def _action_cell(obj: DataDeletionRequest, can_approve: bool) -> Cell:
    if obj.status != RequestStatus.PENDING:
        return Cell(text="-", muted=True)
    if not can_approve:
        return Cell(text="Waiting for the ClickHouse Team", muted=True)
    approve_url = reverse(
        RECORD_TYPES["deletion-request"].operation_url_name,
        kwargs={"pk": obj.pk, "panel_key": "workflow", "operation_key": "approve"},
    )
    return Cell(text="Approve", href=approve_url)


def _request_row(obj: DataDeletionRequest, team_names: dict[int, str], can_approve: bool) -> Row:
    status = RequestStatus(obj.status)
    return Row(
        select_value=str(obj.pk) if can_approve and status == RequestStatus.PENDING else "",
        cells=(
            Cell(text=request_type_label(obj), href=RECORD_TYPES["deletion-request"].url(obj), detail=str(obj.pk)),
            _team_cell(obj.team_id, team_names),
            Cell(text=_sentence_case(status.label), tone=STATUS_TONES.get(status)),
            Cell(text="-" if obj.count is None else f"{obj.count:,}", muted=obj.count is None),
            Cell(
                text=obj.created_at.strftime("%Y-%m-%d %H:%M"),
                detail="By staff" if obj.created_by_staff else "Not by staff",
            ),
            _action_cell(obj, can_approve),
        ),
    )


def _clickhouse_team_members() -> Table:
    members = (
        User.objects.filter(groups__name=CLICKHOUSE.staff_group, is_active=True, is_staff=True)
        .order_by("first_name", "email")
        .distinct()
    )
    return Table(
        title="ClickHouse Team",
        columns=("Name", "Email"),
        rows=tuple(
            Row(
                cells=(
                    Cell(text=member.get_full_name() or member.email, href=RECORD_TYPES["user"].url(member)),
                    Cell(text=member.email, mono=True),
                )
            )
            for member in members
        ),
        empty_text="Nobody is in the ClickHouse Team group. Add staff to it in Django admin.",
    )


def _pending_requests(picked: list[str]) -> list[DataDeletionRequest]:
    pks = []
    for value in picked[:MAX_BULK_APPROVALS]:
        try:
            pks.append(uuid.UUID(value))
        except ValueError:
            continue
    return list(
        DataDeletionRequest.objects.filter(status=RequestStatus.PENDING, pk__in=pks)
        .select_related("created_by")
        .order_by("created_at")
    )


def _creator(obj: DataDeletionRequest) -> str:
    return obj.created_by.email if obj.created_by else "No user recorded"


def _matching_events(obj: DataDeletionRequest) -> str:
    return "no stats" if obj.count is None else f"{obj.count:,} events"


def _revision(obj: DataDeletionRequest) -> str:
    return obj.criteria_updated_at.isoformat() if obj.criteria_updated_at else ""


class BulkApproveForm(ApprovalReasonForm):
    requests = forms.MultipleChoiceField(label="Requests", widget=forms.CheckboxSelectMultiple)
    execution_mode = forms.ChoiceField(
        label="Execution mode",
        choices=ExecutionMode.choices,
        help_text=" ".join(f"{mode.label}: {effect}" for mode, effect in EXECUTION_MODE_EFFECTS.items()),
    )
    # Which edit of each request's criteria the form showed. An approval only lands on that edit.
    criteria_revisions = forms.CharField(required=False, widget=forms.HiddenInput)
    field_order = ["requests", "execution_mode", "reason"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        picked = [
            str(value) for value in (self["requests"].data if self.is_bound else self.initial.get("requests")) or []
        ]
        self.picked_too_many = len(picked) > MAX_BULK_APPROVALS
        self.pending = {str(obj.pk): obj for obj in _pending_requests(picked)}
        if not self.is_bound:
            self.initial = {
                **self.initial,
                "requests": list(self.pending),
                "criteria_revisions": json.dumps({pk: _revision(obj) for pk, obj in self.pending.items()}),
            }
        team_names = dict(
            Team.objects.filter(pk__in={obj.team_id for obj in self.pending.values()}).values_list("id", "name")
        )
        field = self.fields["requests"]
        assert isinstance(field, forms.MultipleChoiceField)
        field.choices = [
            (
                pk,
                f"{request_type_label(obj)}, {team_names.get(obj.team_id, 'deleted team')} ({obj.team_id}), "
                f"{_matching_events(obj)}, by {_creator(obj)}",
            )
            for pk, obj in self.pending.items()
        ]

    def clean_criteria_revisions(self) -> dict[str, datetime | None]:
        try:
            revisions = json.loads(self.cleaned_data["criteria_revisions"] or "{}")
            return {pk: datetime.fromisoformat(value) if value else None for pk, value in revisions.items()}
        except (ValueError, AttributeError, TypeError):
            raise forms.ValidationError("Tick the requests again on the deletion requests page.")

    def clean(self) -> dict:
        cleaned = super().clean() or {}
        if self.picked_too_many:
            raise forms.ValidationError(f"Tick at most {MAX_BULK_APPROVALS} requests.")
        selected = [self.pending[pk] for pk in cleaned.get("requests", []) if pk in self.pending]
        revisions = cleaned.get("criteria_revisions")
        if revisions is not None and any(str(obj.pk) not in revisions for obj in selected):
            raise forms.ValidationError("Tick the requests again on the deletion requests page.")
        if mode := cleaned.get("execution_mode"):
            unsupported = [
                obj for obj in selected if ExecutionMode(mode) not in EXECUTION_MODES[RequestType(obj.request_type)]
            ]
            if unsupported:
                self.add_error(
                    "execution_mode",
                    f"{ExecutionMode(mode).label} does not apply to: "
                    + ", ".join(f"{request_type_label(obj)} {obj.pk}" for obj in unsupported),
                )
        cleaned["selected"] = selected
        return cleaned


def _criteria_summary(obj: DataDeletionRequest) -> str:
    summary = "; ".join(
        f"{criterion.label}: {criterion.value}"
        for criterion in criteria_values(obj)
        if criterion.label not in ("Type", "Team")
    )
    return summary if len(summary) <= CRITERIA_PREVIEW_CHARS else f"{summary[:CRITERIA_PREVIEW_CHARS].rstrip()}…"


def preview_bulk_approval(request: HttpRequest, form: forms.Form) -> Page:
    selected: list[DataDeletionRequest] = form.cleaned_data["selected"]
    mode = ExecutionMode(form.cleaned_data["execution_mode"])
    without_stats = sum(1 for obj in selected if obj.stats_calculated_at is None)
    blocks: list[Notice | Table] = [
        Notice(text=f"Approves {pluralize(len(selected), 'request')}. {mode.label}: {EXECUTION_MODE_EFFECTS[mode]}"),
        Table(
            columns=("Request", "Team", "Matching events", "Created by", "Criteria"),
            rows=tuple(
                Row(
                    cells=(
                        Cell(
                            text=request_type_label(obj),
                            href=RECORD_TYPES["deletion-request"].url(obj),
                            detail=str(obj.pk),
                        ),
                        Cell(text=str(obj.team_id)),
                        Cell(text=_matching_events(obj), muted=obj.count is None),
                        Cell(text=_creator(obj)),
                        Cell(text=_criteria_summary(obj), mono=True),
                    )
                )
                for obj in selected
            ),
        ),
    ]
    if without_stats:
        blocks.append(
            Notice(
                text=f"{pluralize(without_stats, 'request')} {'has' if without_stats == 1 else 'have'} no stats. "
                "Open a request to fetch them before you approve.",
                tone=Tone.WARNING,
            )
        )
    return Page(blocks=tuple(blocks))


def bulk_approve(request: HttpRequest, form: forms.Form | None) -> HttpResponse | None:
    assert form is not None
    mode = form.cleaned_data["execution_mode"]
    revisions = form.cleaned_data["criteria_revisions"]
    approved = 0
    changed = []
    for obj in form.cleaned_data["selected"]:
        if approve_reviewed(request, obj, mode, revisions[str(obj.pk)]):
            approved += 1
        else:
            changed.append(str(obj.pk))
    if approved:
        messages.success(request, f"Approved {pluralize(approved, 'deletion request')} ({ExecutionMode(mode).label}).")
    if changed:
        messages.warning(
            request,
            f"Skipped {pluralize(len(changed), 'request')} that changed since you reviewed them: {', '.join(changed)}.",
        )
    return None


@console.register_tool
class DeletionRequestsTool(ConsoleTool):
    key = "deletion-requests"
    title = "Deletion requests"
    owner = CLICKHOUSE
    group = "Data deletion"
    description = (
        "Every request to delete data of a team, with its status, and the ClickHouse Team members who approve them."
    )

    def page(self, request: HttpRequest) -> Page:
        form = DeletionRequestFilterForm(request.GET or None)
        page = Paginator(_filtered_requests(form), REQUESTS_PER_PAGE).get_page(request.GET.get("page"))
        requests = list(page.object_list)
        team_names = dict(Team.objects.filter(pk__in={obj.team_id for obj in requests}).values_list("id", "name"))
        can_approve = Gate.owner().resolve(self.owner).allows(request)
        query = request.GET.copy()
        rows = tuple(_request_row(obj, team_names, can_approve) for obj in requests)

        def page_url(number: int) -> str:
            query["page"] = str(number)
            return f"?{query.urlencode()}"

        return Page(
            blocks=(
                Notice(
                    text=(
                        "Open a request to see its criteria and stats. Requests waiting for approval need a member "
                        "of the ClickHouse Team, listed below."
                    ),
                    link_text="New deletion request",
                    href="/admin/console/tools/new-deletion-request/",
                ),
                _status_counts(),
                Filters(
                    form=form,
                    groups=(
                        FieldGroup(
                            title="Filter", field_names=("status", "request_type", "team_id", "created_by"), inline=True
                        ),
                    ),
                    submit_label="Filter",
                ),
                Table(
                    columns=("Request", "Team", "Status", "Matching events", "Created", "Action"),
                    rows=rows,
                    empty_text="No deletion requests match.",
                    numeric_columns=(3,),
                    select=(
                        TableSelect(
                            operation_key="approve",
                            field="requests",
                            label="Approve selected",
                            values={key: request.GET[key] for key in request.GET if key != "requests"},
                        )
                        if any(row.select_value for row in rows)
                        else None
                    ),
                ),
                *(
                    (
                        Paging(
                            number=page.number,
                            num_pages=page.paginator.num_pages,
                            summary=f"{page.paginator.count:,} requests",
                            previous_url=page_url(page.previous_page_number()) if page.has_previous() else None,
                            next_url=page_url(page.next_page_number()) if page.has_next() else None,
                        ),
                    )
                    if page.paginator.count
                    else ()
                ),
                _clickhouse_team_members(),
            )
        )

    def operations(self, request: HttpRequest) -> list[ToolOperation]:
        if not DataDeletionRequest.objects.filter(status=RequestStatus.PENDING).exists():
            return []
        return [
            ToolOperation(
                key="approve",
                label="Approve requests",
                handler=bulk_approve,
                preview=preview_bulk_approval,
                danger=True,
                form_class=BulkApproveForm,
                form_initial={"execution_mode": ExecutionMode.DEFERRED.value},
                description=(
                    "Approves the requests you ticked on the deletion requests page. The deletion job picks them up "
                    "and deletes the matching data."
                ),
                undo_hint=(
                    "Until the deletion job picks a request up, move it back to draft on its page. "
                    "Data that a run already deleted cannot be restored."
                ),
                gate=Gate.owner(),
                # The table on the page opens it with the ticked requests, so the Actions card does not offer it.
                listed=False,
            )
        ]
