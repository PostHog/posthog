"""Staff review of published cards, so the pipeline's rules can be tuned on labeled examples."""

from datetime import datetime
from typing import Any
from uuid import UUID

from django.utils import timezone

from posthog.dataclasses import frozen

from ...models.eval_suggestions import EvalSuggestion, EvalSuggestionReviewVerdict, EvalSuggestionRunStatus

MAX_REVIEW_CARDS = 200


@frozen
class ReviewExample:
    trace_id: str
    reason: str


@frozen
class ReviewCard:
    id: UUID
    team_id: int
    run_completed_at: datetime | None
    trigger: str
    kind: str
    dedupe_key: str
    headline: str
    outcome: str
    reason: str
    measured_failure_rate: float | None
    sample_size: int | None
    rollout_percentage: float
    estimated_weekly_runs: int | None
    estimated_weekly_cost_usd: float | None
    status: str
    examples: tuple[ReviewExample, ...]
    review_verdict: str | None
    review_note: str


def _examples(evidence: Any) -> tuple[ReviewExample, ...]:
    items = evidence if isinstance(evidence, list) else []
    return tuple(
        ReviewExample(trace_id=str(item.get("trace_id", "")), reason=str(item.get("reason", "")))
        for item in items
        if isinstance(item, dict) and item.get("trace_id")
    )


def load_review_cards(*, since: datetime, team_id: int | None, unlabeled_only: bool) -> list[ReviewCard]:
    """Cards from completed runs since `since`, newest run first."""
    # Cross-team by design: staff review every flagged team's cards on one page.
    cards = EvalSuggestion.objects.unscoped().filter(
        run__status=EvalSuggestionRunStatus.COMPLETED, run__completed_at__gte=since
    )
    if team_id is not None:
        cards = cards.filter(team_id=team_id)
    if unlabeled_only:
        cards = cards.filter(review_verdict__isnull=True)
    rows = cards.select_related("run").order_by("-run__completed_at", "-score")[:MAX_REVIEW_CARDS]
    return [
        ReviewCard(
            id=card.id,
            team_id=card.team_id,
            run_completed_at=card.run.completed_at,
            trigger=card.run.trigger,
            kind=card.kind,
            dedupe_key=card.dedupe_key,
            headline=card.headline,
            outcome=card.outcome,
            reason=card.reason,
            measured_failure_rate=card.measured_failure_rate,
            sample_size=card.sample_size,
            rollout_percentage=card.rollout_percentage,
            estimated_weekly_runs=card.estimated_weekly_runs,
            estimated_weekly_cost_usd=card.estimated_weekly_cost_usd,
            status=card.status,
            examples=_examples(card.evidence),
            review_verdict=card.review_verdict,
            review_note=card.review_note,
        )
        for card in rows
    ]


@frozen
class ReviewLabel:
    verdict: str | None
    note: str


def current_label(team_id: int, suggestion_id: UUID) -> ReviewLabel | None:
    card = EvalSuggestion.objects.for_team(team_id).filter(id=suggestion_id).first()
    return ReviewLabel(verdict=card.review_verdict, note=card.review_note) if card else None


def label_card(
    team_id: int, suggestion_id: UUID, *, verdict: EvalSuggestionReviewVerdict, note: str, reviewer_id: int
) -> bool:
    """False when the team has no card with this id. A second label replaces the first."""
    updated = (
        EvalSuggestion.objects.for_team(team_id)
        .filter(id=suggestion_id)
        .update(review_verdict=verdict, review_note=note, reviewed_at=timezone.now(), reviewed_by_id=reviewer_id)
    )
    return updated > 0
