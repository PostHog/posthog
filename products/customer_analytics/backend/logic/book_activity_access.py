from posthog.models.team import Team
from posthog.models.user import User
from posthog.permissions import posthog_feature_flag_enabled

from products.access_control.backend.facade.user_access_control import UserAccessControl, UserAccessControlError
from products.customer_analytics.backend.constants import CUSTOMER_ANALYTICS_PRODUCT_USAGE_FLAG


def validate_book_activity_query_access(team: Team, user: User) -> None:
    UserAccessControl(user=user, team=team).assert_access_level_for_resource("account", "viewer")
    if not posthog_feature_flag_enabled(
        CUSTOMER_ANALYTICS_PRODUCT_USAGE_FLAG,
        user.distinct_id or str(user.uuid),
        organization_id=team.organization_id,
        team_id=team.id,
    ):
        raise UserAccessControlError("account", "viewer")
