import json
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from django import forms
from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Count, QuerySet
from django.http import HttpRequest

from posthog.admin.console.oauth_application_panels import GROWTH, REVIEW_TOOL_PATH
from posthog.admin.console.panels import Tone
from posthog.admin.console.records import RECORD_TYPES
from posthog.admin.console.registry import console
from posthog.admin.console.tools import (
    Cell,
    ConsoleTool,
    FieldGroup,
    Filters,
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
from posthog.api.oauth.provisioning_review import review_workflow_id
from posthog.models.oauth_provisioning_review import (
    CIMDProvisioningReview,
    ProvisioningReviewStage,
    ProvisioningReviewStatus,
)

REVIEWS_PER_PAGE = 50
REFRESH_SECONDS_WHILE_PENDING = 10
STATUS_TONES = {
    ProvisioningReviewStatus.PENDING: Tone.INFO,
    ProvisioningReviewStatus.ACCEPTED: Tone.SUCCESS,
    ProvisioningReviewStatus.REJECTED: Tone.DESTRUCTIVE,
    ProvisioningReviewStatus.NEEDS_HUMAN: Tone.WARNING,
}
LOG_TONES = {"error": Tone.DESTRUCTIVE, "warning": Tone.WARNING}


class ReviewFilterForm(forms.Form):
    status = forms.ChoiceField(
        required=False, choices=[("", "Any status"), *ProvisioningReviewStatus.choices], label="Status"
    )
    domain = forms.CharField(required=False, label="Domain", help_text="The registrable domain, like example.com.")


def _when(value: Any) -> Cell:
    return Cell(text=value.strftime("%Y-%m-%d %H:%M") if value else "-", muted=value is None)


def _status_cell(review: CIMDProvisioningReview) -> Cell:
    status = ProvisioningReviewStatus(review.status)
    return Cell(text=status.label, tone=STATUS_TONES[status])


def _review_url(review_id: object) -> str:
    return f"{REVIEW_TOOL_PATH}?{urlencode({'review': str(review_id)})}"


def _review_row(review: CIMDProvisioningReview) -> Row:
    app = review.application
    return Row(
        cells=(
            Cell(text=app.name, href=RECORD_TYPES["oauth-application"].url(app), detail=app.client_id),
            Cell(text=review.domain, mono=True),
            _status_cell(review),
            Cell(text=review.reason or "See the run log", href=_review_url(review.pk)),
            _when(review.created_at),
            _when(review.decided_at),
        )
    )


def _filtered_reviews(form: ReviewFilterForm) -> QuerySet[CIMDProvisioningReview]:
    reviews = CIMDProvisioningReview.objects.select_related("application").order_by("-created_at")
    if not form.is_valid():
        return reviews
    if status := form.cleaned_data["status"]:
        reviews = reviews.filter(status=status)
    if domain := form.cleaned_data["domain"].strip().lower():
        reviews = reviews.filter(domain=domain)
    return reviews


def _status_counts() -> Stats:
    counts = dict(CIMDProvisioningReview.objects.values_list("status").annotate(total=Count("id")))
    return Stats(
        items=tuple(
            Stat(label=status.label, value=str(counts.get(status.value, 0)), tone=STATUS_TONES[status])
            for status in ProvisioningReviewStatus
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
class CIMDProvisioningReviewTool(ConsoleTool):
    key = "cimd-provisioning-reviews"
    title = "Provisioning partner reviews"
    owner = GROWTH
    group = "Access"
    description = "Reviews of apps that registered themselves as provisioning partners, with what each review found."

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
        log = self.live(request, "run-log")
        assert log is not None
        app = review.application
        evidence = _evidence_text(review)
        return Page(
            blocks=(
                Notice(
                    text=(
                        f"{app.name} registered for provisioning from {app.client_id}. Accept or block the partner, "
                        "and change its capabilities, on the app's page."
                    ),
                    link_text="Open the app",
                    href=RECORD_TYPES["oauth-application"].url(app),
                ),
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
        form = ReviewFilterForm(request.GET or None)
        reviews = _filtered_reviews(form)
        page = Paginator(reviews, REVIEWS_PER_PAGE).get_page(request.GET.get("page"))
        query = request.GET.copy()

        def page_url(number: int) -> str:
            query["page"] = str(number)
            return f"?{query.urlencode()}"

        return Page(
            blocks=(
                Notice(
                    text=(
                        "Every app that registers itself as a provisioning partner is reviewed before it can create "
                        "accounts. Jev judges the registration with research from the web. Reviews it cannot settle "
                        "wait here for staff, who accept or block the partner on the app's page and can change that "
                        "decision later."
                    )
                ),
                _status_counts(),
                Filters(
                    form=form,
                    groups=(FieldGroup(title="Filter", field_names=("status", "domain"), inline=True),),
                    submit_label="Filter",
                ),
                Table(
                    columns=("App", "Domain", "Review", "Reason", "Opened", "Decided"),
                    rows=tuple(_review_row(review) for review in page.object_list),
                    empty_text="No reviews match.",
                ),
                *(
                    (
                        Paging(
                            number=page.number,
                            num_pages=page.paginator.num_pages,
                            summary=f"{page.paginator.count} reviews",
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
        return Live(
            key="run-log",
            block=_log_table(review),
            refresh_seconds=REFRESH_SECONDS_WHILE_PENDING
            if review.status == ProvisioningReviewStatus.PENDING
            else None,
        )
