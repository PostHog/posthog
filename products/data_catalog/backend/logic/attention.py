from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.data_modeling.backend.facade import api as data_modeling_api

from .pending_review import PendingReviewCounts, pending_review_counts

NO_PENDING_REVIEW = PendingReviewCounts(metrics=0, relationships=0, certifications=0)


@frozen
class CatalogAttention:
    pending_review: PendingReviewCounts
    failing_models: int


def _readable_pending_review(team: Team, user: User, user_access_control: UserAccessControl) -> PendingReviewCounts:
    if not user_access_control.check_access_level_for_resource("data_catalog", "viewer"):
        return NO_PENDING_REVIEW
    return pending_review_counts(team, user, user_access_control)


def catalog_attention(team: Team, user: User, user_access_control: UserAccessControl) -> CatalogAttention:
    """The catalog badge's review and model counts, with 0 for each part the caller may not read."""
    return CatalogAttention(
        pending_review=_readable_pending_review(team, user, user_access_control),
        failing_models=data_modeling_api.failing_model_count(team, user_access_control) or 0,
    )
