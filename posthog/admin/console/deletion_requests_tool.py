from django import forms
from django.core.paginator import Paginator
from django.db.models import Count, Q, QuerySet
from django.http import HttpRequest
from django.urls import reverse

from posthog.admin.console.deletion_request_panels import CLICKHOUSE, STATUS_TONES
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
)
from posthog.models.data_deletion_request import DataDeletionRequest, RequestStatus, RequestType
from posthog.models.team.team import Team
from posthog.models.user import User

REQUESTS_PER_PAGE = 50

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
        )
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


@console.register_tool
class DeletionRequestsTool(ConsoleTool):
    key = "deletion-requests"
    title = "Deletion requests"
    owner = CLICKHOUSE
    group = "Data"
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
                    rows=tuple(_request_row(obj, team_names, can_approve) for obj in requests),
                    empty_text="No deletion requests match.",
                    numeric_columns=(3,),
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
