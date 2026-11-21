import json
from typing import Any
from uuid import UUID

from django import forms
from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Count, Q, QuerySet
from django.http import HttpRequest

from posthog.admin.console.oauth_application_panels import (
    GROWTH,
    KIND_LABELS,
    OAUTH_APPLICATIONS_TOOL_KEY,
    app_kind,
    decision_operation_links,
    provisioning_status,
    review_page_url,
)
from posthog.admin.console.panels import Tone
from posthog.admin.console.records import RECORD_TYPES
from posthog.admin.console.registry import console
from posthog.admin.console.tools import (
    Cell,
    ConsoleTool,
    FieldGroup,
    Filters,
    Link,
    Links,
    Live,
    Notice,
    Output,
    Page,
    Paging,
    Row,
    Stat,
    Stats,
    Table,
)
from posthog.api.oauth.provisioning_review import partner_provisioning_status, review_workflow_id
from posthog.models.instance_setting import get_instance_setting
from posthog.models.oauth import OAuthApplication
from posthog.models.oauth_provisioning_review import (
    CIMDProvisioningReview,
    PartnerProvisioningStatus,
    ProvisioningReviewStage,
    ProvisioningReviewStatus,
)

APPLICATIONS_PER_PAGE = 50
REFRESH_SECONDS_WHILE_PENDING = 10
STATUS_TONES = {
    ProvisioningReviewStatus.PENDING: Tone.INFO,
    ProvisioningReviewStatus.ACCEPTED: Tone.SUCCESS,
    ProvisioningReviewStatus.REJECTED: Tone.DESTRUCTIVE,
    ProvisioningReviewStatus.NEEDS_HUMAN: Tone.WARNING,
}
REVIEW_COUNT_LABELS = {
    ProvisioningReviewStatus.NEEDS_HUMAN: "Waiting for staff",
    ProvisioningReviewStatus.PENDING: "Reviews running",
    ProvisioningReviewStatus.ACCEPTED: "Accepted partners",
    ProvisioningReviewStatus.REJECTED: "Rejected partners",
}
LOG_TONES = {"error": Tone.DESTRUCTIVE, "warning": Tone.WARNING}
NO_REVIEW = "none"


class ApplicationFilterForm(forms.Form):
    q = forms.CharField(required=False, label="Name or client ID")
    kind = forms.ChoiceField(
        required=False,
        label="Kind",
        choices=[("", "Any kind"), *KIND_LABELS.items()],
    )
    provisioning = forms.ChoiceField(
        required=False,
        label="Provisioning",
        choices=[("", "Anything"), ("partner", "Any partner"), ("on", "On"), ("off", "Off"), ("blocked", "Blocked")],
    )
    review = forms.ChoiceField(
        required=False,
        label="Review",
        choices=[("", "Any review"), *ProvisioningReviewStatus.choices, (NO_REVIEW, "No review")],
    )


def _when(value: Any) -> Cell:
    return Cell(text=value.strftime("%Y-%m-%d %H:%M") if value else "-", muted=value is None)


def _status_cell(review: CIMDProvisioningReview) -> Cell:
    status = ProvisioningReviewStatus(review.status)
    return Cell(text=status.label, tone=STATUS_TONES[status])


KIND_SHORT_LABELS = {"cimd": "CIMD", "dcr": "DCR", "staff": "Staff"}


def _application_row(app: OAuthApplication) -> Row:
    review = getattr(app, "provisioning_review", None)
    status, tone = provisioning_status(app, review)
    return Row(
        cells=(
            Cell(text=app.name, href=RECORD_TYPES["oauth-application"].url(app), detail=app.client_id),
            Cell(text=KIND_SHORT_LABELS[app_kind(app)]),
            Cell(text=status, tone=tone, muted=tone is None),
            _status_cell(review) if review is not None else Cell(text="-", muted=True),
            Cell(text="Run log", href=review_page_url(review)) if review is not None else Cell(text="-", muted=True),
            _when(app.created),
        )
    )


KIND_FILTERS = {
    "cimd": Q(is_cimd_client=True),
    "dcr": Q(is_dcr_client=True),
    "staff": Q(is_cimd_client=False, is_dcr_client=False),
}


# A config written before a flag existed has no key for it, and the model reads that as False.
ACTIVE_OFF = Q(_provisioning_config__active=False) | Q(_provisioning_config__active__isnull=True)
DISABLED_OFF = Q(_provisioning_config__disabled=False) | Q(_provisioning_config__disabled__isnull=True)

# These follow the partner gates, and `_provisioning_filter` adds the organization link when staff require one.
# `provisioning_status` labels the same states.
PROVISIONING_FILTERS = {
    "partner": Q(is_provisioning_partner=True),
    "on": Q(is_provisioning_partner=True, _provisioning_config__active=True),
    "off": Q(is_provisioning_partner=True) & ACTIVE_OFF & DISABLED_OFF,
    "blocked": Q(_provisioning_config__disabled=True) & (ACTIVE_OFF | Q(is_provisioning_partner=False)),
}


def _provisioning_filter(state: str) -> Q:
    if not get_instance_setting("CIMD_PROVISIONING_REQUIRES_ORGANIZATION"):
        return PROVISIONING_FILTERS[state]
    # The gates also refuse an active self-registered partner with no organization behind it.
    held_back = Q(
        is_cimd_client=True,
        organization__isnull=True,
        organization_link_issuer="",
        _provisioning_config__active=True,
    )
    if state == "on":
        return PROVISIONING_FILTERS["on"] & ~held_back
    if state == "off":
        return PROVISIONING_FILTERS["off"] | (Q(is_provisioning_partner=True) & held_back)
    return PROVISIONING_FILTERS[state]


def _filtered_applications(form: ApplicationFilterForm) -> QuerySet[OAuthApplication]:
    applications = OAuthApplication.objects.select_related("provisioning_review").order_by("-created")
    if not form.is_valid():
        return applications
    if query := form.cleaned_data["q"].strip():
        applications = applications.filter(Q(name__icontains=query) | Q(client_id__icontains=query))
    if kind := form.cleaned_data["kind"]:
        applications = applications.filter(KIND_FILTERS[kind])
    if provisioning := form.cleaned_data["provisioning"]:
        applications = applications.filter(_provisioning_filter(provisioning))
    if review := form.cleaned_data["review"]:
        applications = (
            applications.filter(provisioning_review__isnull=True)
            if review == NO_REVIEW
            else applications.filter(provisioning_review__status=review)
        )
    return applications


def _review_counts() -> Stats:
    counts = dict(CIMDProvisioningReview.objects.values_list("status").annotate(total=Count("id")))
    return Stats(
        items=tuple(
            Stat(label=label, value=str(counts.get(status.value, 0)), tone=STATUS_TONES[status])
            for status, label in REVIEW_COUNT_LABELS.items()
        )
    )


def _log_table(review: CIMDProvisioningReview) -> Table:
    entries = list(reversed(review.run_log))
    return Table(
        title="Run log",
        columns=("Time", "Step", "What happened"),
        rows=tuple(
            Row(
                cells=(
                    Cell(text=str(entry.get("at", ""))[:19].replace("T", " "), mono=True),
                    Cell(text=str(entry.get("step", ""))),
                    Cell(text=str(entry.get("message", "")), tone=LOG_TONES.get(str(entry.get("level")))),
                )
            )
            for entry in entries
        ),
        empty_text="Nothing has run yet.",
    )


def _run_log(review: CIMDProvisioningReview) -> Live:
    return Live(
        key="run-log",
        block=_log_table(review),
        refresh_seconds=REFRESH_SECONDS_WHILE_PENDING if review.status == ProvisioningReviewStatus.PENDING else None,
    )


def _evidence_text(review: CIMDProvisioningReview) -> str:
    sections = {
        "Jev judgment": review.research_judgment,
        "Research evidence": review.research_evidence,
        "Metadata document": review.metadata_document,
    }
    return "\n\n".join(
        f"{title}\n{json.dumps(value, indent=2, sort_keys=True)}" for title, value in sections.items() if value
    )


def _temporal_url(review: CIMDProvisioningReview) -> str:
    workflow_id = review_workflow_id(str(review.application_id))
    return f"{settings.TEMPORAL_UI_HOST}/namespaces/{settings.TEMPORAL_NAMESPACE}/workflows/{workflow_id}"


@console.register_tool
class OAuthApplicationsTool(ConsoleTool):
    key = OAUTH_APPLICATIONS_TOOL_KEY
    title = "OAuth applications"
    owner = GROWTH
    group = "Access"
    description = "Every OAuth application, with its provisioning partner status and the review of each partner that registered itself."

    def _review(self, request: HttpRequest) -> CIMDProvisioningReview | None:
        try:
            review_id = UUID(request.GET.get("review", ""))
        except ValueError:
            return None
        return (
            CIMDProvisioningReview.objects.select_related("application", "application__organization")
            .filter(pk=review_id)
            .first()
        )

    def page(self, request: HttpRequest) -> Page:
        review = self._review(request)
        if review is None:
            return self._list_page(request)
        log = _run_log(review)
        app = review.application
        evidence = _evidence_text(review)
        app_url = RECORD_TYPES["oauth-application"].url(app)
        decisions = decision_operation_links(app)
        if partner_provisioning_status(app, review) == PartnerProvisioningStatus.WAITING_FOR_STAFF:
            summary = Notice(
                text=(
                    f"{app.name} is waiting for a staff decision. Read the review below, then accept or block the "
                    "partner."
                ),
                tone=Tone.WARNING,
            )
        else:
            summary = Notice(
                text=(
                    f"{app.name} registered for provisioning from {app.client_id}. Change the decision or its "
                    "capabilities on the app's page."
                )
            )
        return Page(
            blocks=(
                summary,
                Links(items=(*decisions, Link(label="Open the app", href=app_url, primary=not decisions))),
                Stats(
                    items=(
                        Stat(label="Status", value=_status_cell(review).text, tone=_status_cell(review).tone),
                        Stat(
                            label="Decided by",
                            value=ProvisioningReviewStage(review.decided_stage).label if review.decided_stage else "-",
                        ),
                        Stat(label="Domain", value=review.domain),
                        Stat(label="Attested organization", value=app.organization.name if app.organization else "-"),
                    )
                ),
                *((Notice(text=review.reason),) if review.reason else ()),
                log,
                *((Output(text=evidence),) if evidence else ()),
                Table(
                    columns=("Temporal workflow",),
                    rows=(
                        Row(
                            cells=(
                                Cell(
                                    text=review_workflow_id(str(review.application_id)),
                                    href=_temporal_url(review),
                                    mono=True,
                                ),
                            )
                        ),
                    ),
                ),
            )
        )

    def _list_page(self, request: HttpRequest) -> Page:
        form = ApplicationFilterForm(request.GET or None)
        applications = _filtered_applications(form)
        page = Paginator(applications, APPLICATIONS_PER_PAGE).get_page(request.GET.get("page"))
        query = request.GET.copy()

        def page_url(number: int) -> str:
            query["page"] = str(number)
            return f"?{query.urlencode()}"

        return Page(
            blocks=(
                Notice(
                    text=(
                        "Open an app to manage it. Every app that registers itself as a provisioning partner is "
                        "reviewed before it can create accounts, and reviews the pipeline cannot settle wait for "
                        "staff. Staff accept or block a partner on its page, and can change that decision later."
                    )
                ),
                _review_counts(),
                Filters(
                    form=form,
                    groups=(
                        FieldGroup(title="Filter", field_names=("q", "kind", "provisioning", "review"), inline=True),
                    ),
                    submit_label="Filter",
                ),
                Table(
                    columns=("App", "Kind", "Provisioning", "Review", "Evidence", "Created"),
                    rows=tuple(_application_row(app) for app in page.object_list),
                    empty_text="No OAuth applications match.",
                ),
                *(
                    (
                        Paging(
                            number=page.number,
                            num_pages=page.paginator.num_pages,
                            summary=f"{page.paginator.count} applications",
                            previous_url=page_url(page.previous_page_number()) if page.has_previous() else None,
                            next_url=page_url(page.next_page_number()) if page.has_next() else None,
                        ),
                    )
                    if page.paginator.count
                    else ()
                ),
            )
        )

    def live(self, request: HttpRequest, key: str) -> Live | None:
        review = self._review(request)
        if key != "run-log" or review is None:
            return None
        return _run_log(review)
