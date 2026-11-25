from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.data_modeling.backend.facade import api as data_modeling_api

from .pending_review import PendingReviewCounts, pending_review_counts

NO_PENDING_REVIEW = PendingReviewCounts(metrics=0, relationships=0, certifications=0)


@frozen
class CatalogAttention:
    pending_review: PendingReviewCounts | None
    failing_models: int


def _readable_pending_review(
    team: Team, user: User, user_access_control: UserAccessControl
) -> PendingReviewCounts | None:
    if not user_access_control.check_access_level_for_resource("data_catalog", "viewer"):
        return NO_PENDING_REVIEW
    try:
        return pending_review_counts(team, user, user_access_control)
    except Exception as error:
        capture_exception(error, {"team_id": team.id})
        return None


def catalog_attention(team: Team, user: User, user_access_control: UserAccessControl) -> CatalogAttention:
    """The catalog badge's review and model counts: 0 for a part the caller may not read, None for review counts that failed."""
    return CatalogAttention(
        pending_review=_readable_pending_review(team, user, user_access_control),
        failing_models=data_modeling_api.failing_model_count(team, user_access_control) or 0,
    )
