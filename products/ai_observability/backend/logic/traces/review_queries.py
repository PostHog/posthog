from collections.abc import Sequence
from typing import Final

from django.db.models import Prefetch

from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl

from ...models.review_queues import ReviewQueue, ReviewQueueItem
from ...models.trace_reviews import TraceReview, TraceReviewScore
from .review import HumanReview, QueueAssignment, ReviewScore, TraceReviewState, reviewer_name, score_display_value

# Reviews, queues and queue items are llm_analytics objects with their own access controls, apart from the
# llm_analytics access that opens the trace, so a viewer blocked from one must not see it here either. Organization
# admins keep seeing them, as they can still open each one directly.
RESOURCE: Final = "llm_analytics"


def load_trace_review_state(team: Team, user: User, trace_id: str) -> TraceReviewState:
    """The trace's active human review and review queue item that the user may see. A trace has at most one of each."""
    return load_trace_review_states(team, user, [trace_id])[trace_id]


def load_trace_review_states(team: Team, user: User, trace_ids: Sequence[str]) -> dict[str, TraceReviewState]:
    """The state `load_trace_review_state` gives for each requested trace, from two reads however many traces there are."""
    unique_ids = list(dict.fromkeys(trace_ids))
    if not unique_ids:
        return {}
    access = UserAccessControl(user=user, team=team)
    reviews = _load_reviews(team, access, unique_ids)
    queues = _load_queue_assignments(team, access, unique_ids)
    return {
        trace_id: TraceReviewState(review=reviews.get(trace_id), queue=queues.get(trace_id)) for trace_id in unique_ids
    }


def _load_reviews(team: Team, access: UserAccessControl, trace_ids: Sequence[str]) -> dict[str, HumanReview]:
    scores = TraceReviewScore.objects.select_related("definition").order_by("definition__name", "id")
    reviews = TraceReview.objects.filter(team_id=team.id, trace_id__in=trace_ids, deleted=False)
    visible = (
        access.filter_queryset_by_access_level(reviews, resource=RESOURCE, include_all_if_admin=True)
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
    return HumanReview(
        reviewed_by=reviewer_name(reviewer.first_name, reviewer.email, reviewer.distinct_id) if reviewer else None,
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


def _load_queue_assignments(
    team: Team, access: UserAccessControl, trace_ids: Sequence[str]
) -> dict[str, QueueAssignment]:
    queues = access.filter_queryset_by_access_level(
        ReviewQueue.objects.filter(team_id=team.id), resource=RESOURCE, include_all_if_admin=True
    )
    items = ReviewQueueItem.objects.filter(
        team_id=team.id, trace_id__in=trace_ids, deleted=False, queue__deleted=False, queue__in=queues
    )
    visible = access.filter_queryset_by_access_level(
        items, resource=RESOURCE, include_all_if_admin=True
    ).select_related("queue")
    by_trace: dict[str, QueueAssignment] = {}
    for item in visible:
        by_trace.setdefault(
            item.trace_id,
            QueueAssignment(queue_id=str(item.queue_id), queue_name=item.queue.name, item_id=str(item.id)),
        )
    return by_trace
