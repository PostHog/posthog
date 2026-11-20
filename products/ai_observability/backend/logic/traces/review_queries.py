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
    access = UserAccessControl(user=user, team=team)
    return TraceReviewState(
        review=_load_review(team, access, trace_id), queue=_load_queue_assignment(team, access, trace_id)
    )


def _load_review(team: Team, access: UserAccessControl, trace_id: str) -> HumanReview | None:
    scores = TraceReviewScore.objects.select_related("definition").order_by("definition__name", "id")
    reviews = TraceReview.objects.filter(team_id=team.id, trace_id=trace_id, deleted=False)
    review = (
        access.filter_queryset_by_access_level(reviews, resource=RESOURCE, include_all_if_admin=True)
        .select_related("reviewed_by")
        .prefetch_related(Prefetch("scores", queryset=scores))
        .first()
    )
    if review is None:
        return None
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


def _load_queue_assignment(team: Team, access: UserAccessControl, trace_id: str) -> QueueAssignment | None:
    queues = access.filter_queryset_by_access_level(
        ReviewQueue.objects.filter(team_id=team.id), resource=RESOURCE, include_all_if_admin=True
    )
    items = ReviewQueueItem.objects.filter(
        team_id=team.id, trace_id=trace_id, deleted=False, queue__deleted=False, queue__in=queues
    )
    item = (
        access.filter_queryset_by_access_level(items, resource=RESOURCE, include_all_if_admin=True)
        .select_related("queue")
        .first()
    )
    if item is None:
        return None
    return QueueAssignment(queue_id=str(item.queue_id), queue_name=item.queue.name, item_id=str(item.id))
