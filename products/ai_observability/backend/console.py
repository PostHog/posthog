from datetime import timedelta
from typing import cast
from urllib.parse import quote, urlencode

from django import forms
from django.conf import settings
from django.contrib import messages
from django.db.models import Model
from django.http import HttpRequest, HttpResponse
from django.utils import timezone

from posthog.admin.console.panels import Fact, Operation, Owner, Panel, ReasonForm, Tone
from posthog.admin.console.registry import console
from posthog.admin.console.tools import (
    Cell,
    ConsoleTool,
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
from posthog.models.team import Team
from posthog.models.user import User

from products.ai_observability.backend.facade.admin import (
    EvalSuggestionReviewVerdict,
    LabelTarget,
    MigrationAction,
    ReviewCard,
    TaggerMigrationStep,
    UsageReportRefused,
    count_taggers,
    dataset_retention_enabled,
    label_card,
    label_target,
    load_review_cards,
    migrate_taggers,
    plan_tagger_migration,
    queue_usage_report,
    set_dataset_retention_enabled,
    usage_report_skips_existing_reports,
)

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
    group = "Data"
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
    "Cards the eval suggestions pipeline published, newest run first. Label each one good when you would want it on "
    "your own evals page, and bad otherwise, with a note on what is wrong. Customers never see the labels. The "
    "examples link to traces in the customer's project."
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
    unlabeled = forms.BooleanField(label="Only cards without a label", required=False)


class LabelSuggestionForm(forms.Form):
    team = forms.IntegerField(label="Team ID", min_value=1)
    suggestion = forms.UUIDField(label="Suggestion ID")
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
    messages.success(request, f"Labeled the suggestion {verdict.label.lower()}.")
    return None


def _short(text: str, limit: int = 28) -> str:
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _measured(card: ReviewCard) -> Cell:
    if card.measured_failure_rate is None or card.sample_size is None:
        return Cell(text="Not measured", muted=True)
    return Cell(text=f"{card.measured_failure_rate:.1%}", detail=f"of {card.sample_size} sampled traces")


def _runs(card: ReviewCard) -> Cell:
    if card.estimated_weekly_runs is None:
        return Cell(text="-", muted=True)
    cost = f", about ${card.estimated_weekly_cost_usd:,.2f}" if card.estimated_weekly_cost_usd is not None else ""
    return Cell(text=f"{card.estimated_weekly_runs:,}", detail=f"at {card.rollout_percentage:g}% rollout{cost}")


def _examples(card: ReviewCard) -> Cell:
    if not card.examples:
        return Cell(text="None", muted=True)
    first = card.examples[0]
    count = len(card.examples)
    # Encoded twice like urls.aiObservabilityTrace, because the router decodes the path once and the trace page
    # decodes the ID again.
    trace = quote(quote(first.trace_id, safe=""), safe="")
    return Cell(
        text=f"{count} trace{'s' if count != 1 else ''}",
        href=f"{settings.SITE_URL}/project/{card.team_id}/ai-observability/traces/{trace}",
        detail=_short(first.reason),
    )


def _label(card: ReviewCard) -> Cell:
    href = f"{REVIEW_TOOL_URL}label/?{urlencode({'team': card.team_id, 'suggestion': str(card.id)})}"
    if card.review_verdict is None:
        return Cell(text="Label", href=href)
    tone = Tone.SUCCESS if card.review_verdict == EvalSuggestionReviewVerdict.GOOD else Tone.DESTRUCTIVE
    return Cell(
        text=EvalSuggestionReviewVerdict(card.review_verdict).label,
        href=href,
        tone=tone,
        detail=_short(card.review_note),
    )


def _review_row(card: ReviewCard) -> Row:
    completed = card.run_completed_at.strftime("%Y-%m-%d") if card.run_completed_at else "-"
    return Row(
        cells=(
            Cell(text=str(card.team_id), mono=True, detail=f"{completed}, {card.trigger}"),
            Cell(text=card.headline, detail=f"{card.dedupe_key} · {card.status}"),
            Cell(text=f"{card.outcome}\n{card.reason}"),
            _measured(card),
            _runs(card),
            _examples(card),
            _label(card),
        )
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
    group = "Data"
    description = "Labels the eval suggestion cards the pipeline publishes, to tune which ones it shows."

    def page(self, request: HttpRequest) -> Page:
        form = ReviewFilterForm(request.GET or None)
        filters = form.cleaned_data if form.is_valid() else {}
        days = filters.get("days") or 30
        cards = load_review_cards(
            since=timezone.now() - timedelta(days=days),
            team_id=filters.get("team"),
            unlabeled_only=bool(filters.get("unlabeled")),
        )
        good = sum(card.review_verdict == EvalSuggestionReviewVerdict.GOOD for card in cards)
        bad = sum(card.review_verdict == EvalSuggestionReviewVerdict.BAD for card in cards)
        return Page(
            blocks=(
                Notice(text=REVIEW_NOTICE),
                Filters(
                    form=form,
                    groups=(FieldGroup(title="Cards", field_names=("team", "days", "unlabeled")),),
                    submit_label="Show cards",
                ),
                Stats(
                    items=(
                        Stat(label="Cards", value=str(len(cards))),
                        Stat(label="Good", value=str(good)),
                        Stat(label="Bad", value=str(bad)),
                        Stat(label="Not labeled", value=str(len(cards) - good - bad)),
                    )
                ),
                Table(
                    columns=(
                        "Team",
                        "Card",
                        "What it checks, and why",
                        "Failure rate",
                        "Runs a week",
                        "Examples",
                        "Label",
                    ),
                    rows=tuple(_review_row(card) for card in cards),
                    empty_text="No cards match these filters.",
                    scrolls=True,
                ),
            )
        )

    def operations(self, request: HttpRequest) -> list[ToolOperation]:
        initial, target = _label_form(request)
        card = f"{target.headline}: {target.outcome} {target.reason} " if target is not None else ""
        return [
            ToolOperation(
                key="label",
                label="Label a suggestion",
                handler=label_suggestion,
                form_class=LabelSuggestionForm,
                form_initial=initial,
                description=f"{card}Saves a staff label on one card. The customer sees nothing.",
            )
        ]


TAGGER_TYPE_LABELS = {"llm": "LLM tagger", "hog": "Hog tagger"}
ACTION_LABELS = {
    MigrationAction.MIGRATE: ("Becomes an evaluation", Tone.SUCCESS),
    MigrationAction.SWITCH_OFF: ("Switched off", Tone.WARNING),
    MigrationAction.SKIP: ("Stays as it is", Tone.DESTRUCTIVE),
}


def _step_row(step: TaggerMigrationStep) -> Row:
    label, tone = ACTION_LABELS[step.action]
    return Row(
        cells=(
            Cell(text=step.tagger_name, detail=TAGGER_TYPE_LABELS.get(step.tagger_type, step.tagger_type)),
            Cell(text=f"{step.recent_tags:,}"),
            Cell(text=label, tone=tone, detail=step.reason),
            Cell(
                text=", ".join(step.category_keys) or "-", mono=bool(step.category_keys), muted=not step.category_keys
            ),
        )
    )


def _steps_table(steps: list[TaggerMigrationStep]) -> Table:
    return Table(
        columns=("Tagger", "Tags in 30 days", "What happens", "Category keys"),
        rows=tuple(_step_row(step) for step in steps),
        numeric_columns=(1,),
        empty_text="This team has no switched-on taggers left to migrate.",
        scrolls=True,
    )


def preview_tagger_migration(request: HttpRequest, obj: Model, form: forms.Form) -> Page:
    return Page(
        blocks=(
            Notice(
                text="Each tagger that sent tags in the last 30 days becomes an enabled categorical evaluation with "
                "the same name, filters, sampling and model, and the tagger is switched off. Taggers that sent no "
                "tags are only switched off. Old tag data stays. Results arrive as evaluation events from now on, so "
                "insights built on tags stop updating."
            ),
            _steps_table(plan_tagger_migration(cast(Team, obj))),
        )
    )


def run_tagger_migration(request: HttpRequest, obj: Model, form: forms.Form | None) -> Page:
    steps = migrate_taggers(cast(Team, obj), acting_user=cast(User, request.user))
    moved = sum(step.action == MigrationAction.MIGRATE for step in steps)
    switched_off = sum(step.action == MigrationAction.SWITCH_OFF for step in steps)
    skipped = len(steps) - moved - switched_off
    messages.success(
        request, f"Moved {moved} taggers to evaluations, switched off {switched_off}, and left {skipped} as they are."
    )
    return Page(blocks=(_steps_table(steps),))


@console.register_panel
class TaggersPanel(Panel):
    record = "team"
    key = "ai-observability-taggers"
    title = "Taggers"
    owner = AI_OBSERVABILITY
    operation_keys = frozenset({"migrate-taggers"})

    def facts(self, obj: Model) -> list[Fact]:
        counts = count_taggers(cast(Team, obj))
        return [
            Fact(label="Switched on", value=str(counts.switched_on)),
            Fact(label="Moved to evaluations", value=str(counts.migrated)),
        ]

    def operations(self, obj: Model) -> list[Operation]:
        if count_taggers(cast(Team, obj)).switched_on == 0:
            return []
        return [
            Operation(
                key="migrate-taggers",
                label="Migrate taggers to evaluations",
                handler=run_tagger_migration,
                preview=preview_tagger_migration,
                danger=True,
                form_class=ReasonForm,
                description="Replaces the team's switched-on taggers with categorical evaluations and switches the "
                "taggers off. The evaluations run on the team's own provider key.",
                undo_hint="Switch the new evaluations off in the project's evaluations list. Taggers cannot be "
                "switched back on.",
                pending_label="Migrating taggers",
            )
        ]
