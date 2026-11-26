from collections.abc import Sequence

from django.db.models import Model, Prefetch, QuerySet

from posthog.models.team import Team
from posthog.models.user import User
from posthog.permissions import filter_visible_project_objects

from ...models.review_queues import ReviewQueue, ReviewQueueItem
from ...models.trace_reviews import TraceReview, TraceReviewScore
from .review import HumanReview, QueueAssignment, ReviewScore, TraceReviewState, reviewer_name, score_display_value


def _visible_to_reviewer[M: Model](queryset: QuerySet[M], team: Team, reviewer: User | None) -> QuerySet[M]:
    if reviewer is None:
        return queryset
    return filter_visible_project_objects(queryset, team_id=team.id, user_id=reviewer.pk, include_all_if_admin=True)


def load_trace_review_state(team: Team, user: User, trace_id: str) -> TraceReviewState:
    """The trace's active human review and review queue item that the user may see. A trace has at most one of each."""
    return load_trace_review_states(team, user, [trace_id])[trace_id]


def load_project_trace_review_state(team: Team, trace_id: str) -> TraceReviewState:
    return _load_states(team, None, [trace_id])[trace_id]


def load_trace_review_states(team: Team, user: User, trace_ids: Sequence[str]) -> dict[str, TraceReviewState]:
    """The state `load_trace_review_state` gives for each requested trace, from two reads however many traces there are."""
    return _load_states(team, user, trace_ids)


def _load_states(team: Team, user: User | None, trace_ids: Sequence[str]) -> dict[str, TraceReviewState]:
    unique_ids = list(dict.fromkeys(trace_ids))
    if not unique_ids:
        return {}
    reviews = _load_reviews(team, user, unique_ids)
    queues = _load_queue_assignments(team, user, unique_ids)
    return {
        trace_id: TraceReviewState(review=reviews.get(trace_id), queue=queues.get(trace_id)) for trace_id in unique_ids
    }


def _load_reviews(team: Team, user: User | None, trace_ids: Sequence[str]) -> dict[str, HumanReview]:
    scores = TraceReviewScore.objects.select_related("definition").order_by("definition__name", "id")
    reviews = TraceReview.objects.filter(team_id=team.id, trace_id__in=trace_ids, deleted=False)
    visible = (
        _visible_to_reviewer(reviews, team, user)
        .select_related("reviewed_by")
        .prefetch_related(Prefetch("scores", queryset=scores))
    )
    by_trace: dict[str, HumanReview] = {}
    for review in visible:
        if review.trace_id not in by_trace:
            by_trace[review.trace_id] = _human_review(review)
    return by_trace


def _human_review(review: TraceReview) -> HumanReview:
    reviewer = review.reviewed_by
    name = reviewer_name(reviewer.first_name, reviewer.email, reviewer.distinct_id) if reviewer else None
    if review.reviewed_by_project_key_id:
        name = f"Project key · {review.reviewed_by_project_key_id[-8:]}"
    return HumanReview(
        reviewed_by=name,
        reviewed_at=review.updated_at or review.created_at,
        comment=review.comment,
        scores=tuple(
            ReviewScore(
                name=score.definition.name,
                value=score_display_value(
                    score.definition.kind,
                    score.definition_config if isinstance(score.definition_config, dict) else None,
                    score.categorical_values,
                    score.numeric_value,
                    score.boolean_value,
                ),
            )
            for score in review.scores.all()
        ),
    )


def _load_queue_assignments(team: Team, user: User | None, trace_ids: Sequence[str]) -> dict[str, QueueAssignment]:
    queues = _visible_to_reviewer(ReviewQueue.objects.filter(team_id=team.id), team, user)
    items = ReviewQueueItem.objects.filter(
        team_id=team.id, trace_id__in=trace_ids, deleted=False, queue__deleted=False, queue__in=queues
    )
    visible = _visible_to_reviewer(items, team, user).select_related("queue")
    by_trace: dict[str, QueueAssignment] = {}
    for item in visible:
        by_trace.setdefault(
            item.trace_id,
            QueueAssignment(queue_id=str(item.queue_id), queue_name=item.queue.name, item_id=str(item.id)),
        )
    return by_trace
