from dataclasses import replace
from datetime import timedelta
from typing import cast
from urllib.parse import quote, urlencode

from django import forms
from django.conf import settings
from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.utils import timezone

import structlog

from posthog.admin.console.panels import Owner, ReasonForm, Tone
from posthog.admin.console.registry import console
from posthog.admin.console.tools import (
    Block,
    Cell,
    Choice,
    ConsoleTool,
    Decision,
    FieldGroup,
    Filters,
    Notice,
    Page,
    Row,
    Stat,
    Stats,
    Table,
    ToolOperation,
)
from posthog.admin.console.usage_reports_tool import ReportDateForm
from posthog.dataclasses import frozen
from posthog.models.user import User

from products.ai_observability.backend.facade.admin import (
    EvalSuggestionReviewVerdict,
    LabelTarget,
    ReviewCard,
    UsageReportRefused,
    count_unlabeled_cards,
    dataset_retention_enabled,
    delete_unlabeled_cards,
    label_card,
    label_target,
    load_labeled_cards,
    load_review_cards,
    queue_usage_report,
    set_dataset_retention_enabled,
    usage_report_skips_existing_reports,
)

logger = structlog.get_logger(__name__)

AI_OBSERVABILITY = Owner(name="AI observability", crest="ai-observability")

USAGE_REPORT_NOTICE = (
    "Usage report: the date is the day the report would have run, and the report covers the day before. "
    "If the dashboards are missing a day, send the report for the day after it. Sending a date again while its run "
    "is still going is refused. US and EU each report their own organizations, so backfill each region separately."
)
SKIPS_EXISTING_NOTICE = (
    "Organizations that already have a report for the period are skipped. This check cannot see a report sent in "
    "the last few minutes, so after a run finishes, wait for it to be ingested before you send the same date again."
)
CANNOT_SKIP_NOTICE = (
    "This region cannot check which organizations already have a report, because reports go to the US project. "
    "Sending a date that was already sent counts its usage twice, and the duplicates cannot be removed. Before you "
    "send, check the daily llm analytics usage event volume for that date in the internal usage-tracking project."
)
DATASET_CLEANUP_NOTICE = (
    "Cleanup permanently deletes unused active datasets after 90 days, and archived datasets and old revisions after "
    "30 days, with a 12-hour margin for recent use. Evaluation results and scores are kept. Pausing stops new expiry "
    "and deletion, including deletion in progress. A running sweep finishes its current dataset first. Expired "
    "datasets stay unavailable and deleted content is not restored. Resuming restarts the hourly schedule. Change "
    "this setting in each region separately."
)


def send_usage_report(request: HttpRequest, form: forms.Form | None) -> HttpResponse | Page | None:
    assert form is not None
    report_date = form.cleaned_data["report_date"]
    try:
        queue_usage_report(report_date)
    except UsageReportRefused as refused:
        messages.error(request, refused.detail)
        return HttpResponse(status=400)
    messages.success(request, f"Queued the AI observability usage report for {report_date}.")
    return None


class DatasetCleanupHandler:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def __call__(self, request: HttpRequest, form: forms.Form | None) -> HttpResponse | Page | None:
        set_dataset_retention_enabled(enabled=self.enabled, user_id=cast(User, request.user).pk)
        messages.success(request, f"Dataset cleanup is now {'on' if self.enabled else 'paused'} in this region.")
        return None


@console.register_tool
class AIObservabilityTool(ConsoleTool):
    key = "ai-observability"
    title = "AI observability"
    owner = AI_OBSERVABILITY
    group = "AI"
    description = "Sends a missing daily usage report, and pauses or resumes dataset cleanup in this region."

    def page(self, request: HttpRequest) -> Page:
        cleanup = "on" if dataset_retention_enabled() else "paused"
        return Page(
            blocks=(
                Notice(text=f"Dataset cleanup is {cleanup} in this region. {DATASET_CLEANUP_NOTICE}"),
                Notice(text=USAGE_REPORT_NOTICE),
                Notice(text=SKIPS_EXISTING_NOTICE if usage_report_skips_existing_reports() else CANNOT_SKIP_NOTICE),
            )
        )

    def operations(self, request: HttpRequest) -> list[ToolOperation]:
        send = ToolOperation(
            key="send-usage-report",
            label="Send usage report",
            handler=send_usage_report,
            description="Queues the AI observability usage report of every organization in this region for one day.",
            form_class=ReportDateForm,
        )
        if dataset_retention_enabled():
            cleanup = ToolOperation(
                key="pause-dataset-cleanup",
                label="Pause dataset cleanup",
                handler=DatasetCleanupHandler(enabled=False),
                description="Stops expiring and deleting datasets in this region until cleanup is resumed.",
            )
        else:
            cleanup = ToolOperation(
                key="resume-dataset-cleanup",
                label="Resume dataset cleanup",
                handler=DatasetCleanupHandler(enabled=True),
                danger=True,
                description="Customers' unused and archived datasets in this region get deleted permanently again.",
                form_class=ReasonForm,
                undo_hint="To stop it, use Pause dataset cleanup. Datasets deleted in the meantime cannot be restored.",
            )
        return [send, cleanup]


console.register_moved_page(
    old_path="admin/posthog/organization/send-ai-observability-usage-report/",
    title="Sending AI observability usage reports",
    url="/admin/console/tools/ai-observability/",
)
console.register_moved_page(
    old_path="admin/posthog/organization/ai-observability-dataset-retention/",
    title="AI observability dataset retention",
    url="/admin/console/tools/ai-observability/",
)


REVIEW_TOOL_URL = "/admin/console/tools/eval-suggestion-review/"
REVIEW_NOTICE = (
    "Cards the eval suggestions pipeline published, one at a time, newest run first. Label a card good when you "
    "would want it on your own evals page, and bad otherwise, with a note on what is wrong. Press the right arrow "
    "for good, the left arrow for bad and the down arrow to skip. Customers never see the labels."
)


class ReviewFilterForm(forms.Form):
    team = forms.IntegerField(label="Team ID", required=False, min_value=1)
    days = forms.TypedChoiceField(
        label="Runs from the last",
        choices=[(7, "7 days"), (30, "30 days"), (90, "90 days")],
        coerce=int,
        initial=30,
        required=False,
    )
    unlabeled = forms.BooleanField(label="Only cards without a label", required=False, initial=True)


def preview_unlabeled_deletion(request: HttpRequest, form: forms.Form) -> Page:
    counts = count_unlabeled_cards()
    return Page(
        blocks=(
            Stats(
                items=(
                    Stat(label="Proposed cards", value=f"{counts.proposed:,}"),
                    Stat(label="Expired cards", value=f"{counts.expired:,}"),
                    Stat(label="Teams", value=f"{counts.teams:,}"),
                )
            ),
        )
    )


def delete_unlabeled(request: HttpRequest, form: forms.Form | None) -> None:
    deleted = delete_unlabeled_cards()
    logger.info("eval_suggestions_unlabeled_deleted", deleted=deleted, staff_id=cast(User, request.user).pk)
    messages.success(request, f"Deleted {deleted:,} unlabeled {'card' if deleted == 1 else 'cards'}.")


class LabelSuggestionForm(forms.Form):
    team = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    suggestion = forms.UUIDField(widget=forms.HiddenInput)
    verdict = forms.ChoiceField(label="Label", choices=EvalSuggestionReviewVerdict.choices)
    note = forms.CharField(
        label="What is right or wrong with it", required=False, widget=forms.Textarea, max_length=2000
    )


def label_suggestion(request: HttpRequest, form: forms.Form | None) -> HttpResponse | Page | None:
    assert form is not None
    verdict = EvalSuggestionReviewVerdict(form.cleaned_data["verdict"])
    cleaned = form.cleaned_data
    reviewer_id = cast(User, request.user).pk
    if not label_card(
        cleaned["team"], cleaned["suggestion"], verdict=verdict, note=cleaned["note"], reviewer_id=reviewer_id
    ):
        messages.error(request, "This team has no suggestion with this ID.")
        return HttpResponse(status=404)
    # The console's operation log records the page's query, which names no card, so the label logs its target.
    logger.info(
        "eval_suggestion_labeled",
        team_id=cleaned["team"],
        suggestion_id=str(cleaned["suggestion"]),
        verdict=verdict.value,
        reviewer_id=reviewer_id,
    )
    messages.success(request, f"Labeled the card {verdict.label.lower()}.")
    return None


@frozen
class ReviewFilters:
    team: int | None
    days: int
    unlabeled: bool

    @classmethod
    def read(cls, request: HttpRequest, form: ReviewFilterForm) -> "ReviewFilters":
        cleaned = form.cleaned_data if form.is_valid() else {}
        # The first visit shows the cards that still need a label.
        unlabeled = bool(cleaned.get("unlabeled")) if request.GET else True
        return cls(team=cleaned.get("team"), days=cleaned.get("days") or 30, unlabeled=unlabeled)

    def query(self, **extra: object) -> str:
        params: dict[str, object] = {"days": self.days}
        if self.team is not None:
            params["team"] = self.team
        if self.unlabeled:
            params["unlabeled"] = "on"
        return urlencode({**params, **extra})


def _position(request: HttpRequest, cards: list[ReviewCard]) -> int:
    # A link from the labeled cards names the card, which keeps its place among every card.
    named = request.GET.get("suggestion")
    for index, card in enumerate(cards, start=1):
        if str(card.id) == named:
            return index
    try:
        wanted = int(request.GET.get("card", "1"))
    except ValueError:
        wanted = 1
    return min(max(wanted, 1), len(cards))


def _trace_url(team_id: int, trace_id: str) -> str:
    # Encoded twice like urls.aiObservabilityTrace, because the router decodes the path once and the trace page
    # decodes the ID again.
    return f"{settings.SITE_URL}/project/{team_id}/ai-observability/traces/{quote(quote(trace_id, safe=''), safe='')}"


def _card_stats(card: ReviewCard) -> Stats:
    items = []
    if card.measured_failure_rate is not None and card.sample_size is not None:
        items.append(
            Stat(label=f"Failure rate in {card.sample_size} traces", value=f"{card.measured_failure_rate:.1%}")
        )
    if card.estimated_weekly_runs is not None:
        items.append(
            Stat(label=f"Runs a week at {card.rollout_percentage:g}% rollout", value=f"{card.estimated_weekly_runs:,}")
        )
    if card.estimated_weekly_cost_usd is not None:
        items.append(Stat(label="Cost a week", value=f"${card.estimated_weekly_cost_usd:,.2f}"))
    return Stats(items=tuple(items))


def _verdict(verdict: str | None) -> Cell:
    if verdict is None:
        return Cell(text="-", muted=True)
    tone = Tone.SUCCESS if verdict == EvalSuggestionReviewVerdict.GOOD else Tone.DESTRUCTIVE
    return Cell(text=EvalSuggestionReviewVerdict(verdict).label, tone=tone)


def _labeled_table(filters: ReviewFilters) -> Table:
    cards = load_labeled_cards(since=timezone.now() - timedelta(days=filters.days), team_id=filters.team)
    # A row opens its card among every card, since the card has a label.
    every_card = replace(filters, unlabeled=False)
    return Table(
        title="Labeled cards",
        columns=("Labeled", "Card", "Label", "Note"),
        rows=tuple(
            Row(
                cells=(
                    Cell(
                        text=card.reviewed_at.strftime("%Y-%m-%d") if card.reviewed_at else "-",
                        detail=card.reviewer,
                    ),
                    Cell(
                        text=card.headline,
                        href=f"{REVIEW_TOOL_URL}?{every_card.query(suggestion=str(card.id))}",
                        detail=f"team {card.team_id}",
                    ),
                    _verdict(card.review_verdict),
                    Cell(text=card.review_note or "-", muted=not card.review_note),
                )
            )
            for card in cards
        ),
        empty_text="No labeled cards in these runs yet.",
        scrolls=True,
    )


def _decision(card: ReviewCard, position: int, count: int, filters: ReviewFilters) -> Decision:
    completed = card.run_completed_at.strftime("%Y-%m-%d") if card.run_completed_at else "not finished"
    label = f" · labeled {card.review_verdict}" if card.review_verdict else ""
    # A labeled card leaves a list of unlabeled cards, so the next one moves into its place.
    after_label = position if filters.unlabeled else position + 1
    return Decision(
        title=card.headline,
        # The words the customer card shows, in its order, so a label judges the copy as customers read it.
        text="\n\n".join(
            part
            for part in (
                card.outcome,
                " · ".join(part for part in (card.observation, card.observation_scope) if part),
                f"Rule: {card.rule}" if card.rule else "",
                f"Why it matters: {card.reason}" if card.reason else "",
            )
            if part
        ),
        detail=f"Card {position} of {count} · team {card.team_id} · {completed}, {card.trigger} · {card.status}{label}",
        operation_key="label",
        field="verdict",
        choices=(
            Choice(label="← Bad", value=EvalSuggestionReviewVerdict.BAD, tone=Tone.DESTRUCTIVE, key="ArrowLeft"),
            Choice(label="Good →", value=EvalSuggestionReviewVerdict.GOOD, tone=Tone.SUCCESS, key="ArrowRight"),
        ),
        values={"team": str(card.team_id), "suggestion": str(card.id)},
        note_field="note",
        note_label="What is right or wrong with it",
        note=card.review_note,
        query=filters.query(card=after_label),
        skip_href=f"{REVIEW_TOOL_URL}?{filters.query(card=position + 1)}" if position < count else None,
        skip_key="ArrowDown",
    )


def _label_form(request: HttpRequest) -> tuple[dict[str, object], LabelTarget | None]:
    """The form's initial values and the card the link points at. The card's current label fills the form, so
    submitting it unchanged keeps the label."""
    initial: dict[str, object] = {"team": request.GET.get("team", ""), "suggestion": request.GET.get("suggestion", "")}
    form = LabelSuggestionForm({**initial, "verdict": EvalSuggestionReviewVerdict.GOOD})
    if not form.is_valid():
        return initial, None
    target = label_target(form.cleaned_data["team"], form.cleaned_data["suggestion"])
    if target is not None and target.verdict is not None:
        initial.update(verdict=target.verdict, note=target.note)
    return initial, target


@console.register_tool
class EvalSuggestionReviewTool(ConsoleTool):
    key = "eval-suggestion-review"
    title = "Eval suggestion review"
    owner = AI_OBSERVABILITY
    group = "AI"
    description = "Labels the eval suggestion cards the pipeline publishes, to tune which ones it shows."

    def page(self, request: HttpRequest) -> Page:
        form = ReviewFilterForm(request.GET or None)
        filters = ReviewFilters.read(request, form)
        cards = load_review_cards(
            since=timezone.now() - timedelta(days=filters.days), team_id=filters.team, unlabeled_only=filters.unlabeled
        )
        blocks: list[Block] = [
            Notice(text=REVIEW_NOTICE),
            Filters(
                form=form,
                groups=(FieldGroup(title="Cards", field_names=("team", "days", "unlabeled")),),
                submit_label="Show cards",
                compact=True,
            ),
        ]
        if not cards:
            return Page(blocks=(*blocks, Notice(text="No cards match these filters."), _labeled_table(filters)))
        position = _position(request, cards)
        if request.GET.get("suggestion") and str(cards[position - 1].id) != request.GET["suggestion"]:
            # The labeled cards can name a card that the newest cards these filters load leave out.
            blocks.append(
                Notice(
                    text=f"That card is not among the {len(cards)} newest cards these filters show. Add its team ID "
                    "or pick fewer days to open it. This is the newest card instead.",
                    tone=Tone.WARNING,
                )
            )
        card = cards[position - 1]
        blocks += [_decision(card, position, len(cards), filters), _card_stats(card)]
        if card.examples:
            blocks.append(
                Table(
                    title="Examples",
                    columns=("Trace", "What went wrong"),
                    rows=tuple(
                        Row(
                            cells=(
                                Cell(text=example.trace_id, href=_trace_url(card.team_id, example.trace_id), mono=True),
                                Cell(text=example.reason),
                            )
                        )
                        for example in card.examples
                    ),
                )
            )
        blocks.append(_labeled_table(filters))
        return Page(blocks=tuple(blocks))

    def operations(self, request: HttpRequest) -> list[ToolOperation]:
        # Bookmarks to the old label page carry the card in the query, and its form opens with the current label.
        initial, target = _label_form(request)
        card = f"{target.headline}: {target.outcome} {target.reason} " if target is not None else ""
        return [
            ToolOperation(
                key="label",
                label="Label a card",
                handler=label_suggestion,
                form_class=LabelSuggestionForm,
                form_initial=initial,
                description=f"{card}Saves a staff label on one card. The customer sees nothing.",
                listed=False,
            ),
            ToolOperation(
                key="delete-unlabeled-cards",
                label="Delete unlabeled cards",
                handler=delete_unlabeled,
                danger=True,
                form_class=ReasonForm,
                preview=preview_unlabeled_deletion,
                description=(
                    "Deletes every card without a label that is still proposed or has expired, across all teams. "
                    "Customers stop seeing those cards until their team's next run. Labeled, accepted and dismissed "
                    "cards stay."
                ),
                undo_hint="This can't be undone. Each team's next run makes new cards.",
                pending_label="Deleting cards",
            ),
        ]
