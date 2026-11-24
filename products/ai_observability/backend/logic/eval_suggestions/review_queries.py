"""Staff review of published cards, so the pipeline's rules can be tuned on labeled examples."""

from datetime import datetime
from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from django.utils import timezone

from posthog.dataclasses import frozen

from ...models.eval_suggestions import (
    EvalSuggestion,
    EvalSuggestionReviewVerdict,
    EvalSuggestionRunStatus,
    EvalSuggestionStatus,
)

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
    observation: str
    observation_scope: str
    # The rule the evaluation applies, from the draft's description.
    rule: str
    measured_failure_rate: float | None
    sample_size: int | None
    rollout_percentage: float
    estimated_weekly_runs: int | None
    estimated_weekly_cost_usd: float | None
    status: str
    examples: tuple[ReviewExample, ...]
    review_verdict: str | None
    review_note: str
    reviewed_at: datetime | None
    # The email of the staff member who labeled the card, or "" when nobody did.
    reviewer: str


def _examples(evidence: Any) -> tuple[ReviewExample, ...]:
    items = evidence if isinstance(evidence, list) else []
    return tuple(
        ReviewExample(trace_id=str(item.get("trace_id", "")), reason=str(item.get("reason", "")))
        for item in items
        if isinstance(item, dict) and item.get("trace_id")
    )


def _published(since: datetime, team_id: int | None) -> QuerySet[EvalSuggestion]:
    # Cross-team by design: staff review every flagged team's cards on one page.
    cards = EvalSuggestion.objects.unscoped().filter(
        run__status=EvalSuggestionRunStatus.COMPLETED, run__completed_at__gte=since
    )
    return cards.filter(team_id=team_id) if team_id is not None else cards


def load_review_cards(*, since: datetime, team_id: int | None, unlabeled_only: bool) -> list[ReviewCard]:
    """Cards from completed runs since `since`, newest run first."""
    cards = _published(since, team_id)
    if unlabeled_only:
        cards = cards.filter(review_verdict__isnull=True)
    return _review_cards(cards.order_by("-run__completed_at", "-score"))


def load_labeled_cards(*, since: datetime, team_id: int | None) -> list[ReviewCard]:
    """Labeled cards from completed runs since `since`, latest label first."""
    return _review_cards(_published(since, team_id).filter(review_verdict__isnull=False).order_by("-reviewed_at"))


def _review_cards(cards: QuerySet[EvalSuggestion]) -> list[ReviewCard]:
    rows = cards.select_related("run", "reviewed_by")[:MAX_REVIEW_CARDS]
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
            observation=str(card.draft.get("observation", "")) if isinstance(card.draft, dict) else "",
            observation_scope=str(card.draft.get("observation_scope", "")) if isinstance(card.draft, dict) else "",
            rule=str(card.draft.get("description", "")) if isinstance(card.draft, dict) else "",
            measured_failure_rate=card.measured_failure_rate,
            sample_size=card.sample_size,
            rollout_percentage=card.rollout_percentage,
            estimated_weekly_runs=card.estimated_weekly_runs,
            estimated_weekly_cost_usd=card.estimated_weekly_cost_usd,
            status=card.status,
            examples=_examples(card.evidence),
            review_verdict=card.review_verdict,
            review_note=card.review_note,
            reviewed_at=card.reviewed_at,
            reviewer=card.reviewed_by.email if card.reviewed_by else "",
        )
        for card in rows
    ]


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


@frozen
class UnlabeledCards:
    proposed: int
    expired: int
    teams: int


def _unlabeled() -> QuerySet[EvalSuggestion]:
    # Cross-team by design. Labeled cards hold staff notes, accepted ones link to the evaluations they made, and
    # dismissed ones stop a run from proposing the same card again, so all of those stay.
    return EvalSuggestion.objects.unscoped().filter(
        review_verdict__isnull=True, status__in=(EvalSuggestionStatus.PROPOSED, EvalSuggestionStatus.EXPIRED)
    )


def count_unlabeled_cards() -> UnlabeledCards:
    cards = _unlabeled()
    return UnlabeledCards(
        proposed=cards.filter(status=EvalSuggestionStatus.PROPOSED).count(),
        expired=cards.filter(status=EvalSuggestionStatus.EXPIRED).count(),
        teams=cards.values("team_id").distinct().count(),
    )


def delete_unlabeled_cards() -> int:
    """Deletes every unlabeled card that is still proposed or expired, across teams, and returns how many."""
    deleted, _ = _unlabeled().delete()
    return deleted


@frozen
class LabelTarget:
    """What the label form shows about one card: its text, and its current label."""

    headline: str
    outcome: str
    reason: str
    verdict: str | None
    note: str


def label_target(team_id: int, suggestion_id: UUID) -> LabelTarget | None:
    card = EvalSuggestion.objects.for_team(team_id).filter(id=suggestion_id).first()
    if card is None:
        return None
    return LabelTarget(
        headline=card.headline,
        outcome=card.outcome,
        reason=card.reason,
        verdict=card.review_verdict,
        note=card.review_note,
    )
