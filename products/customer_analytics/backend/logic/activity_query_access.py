from typing import TYPE_CHECKING

from products.access_control.backend.facade.property_access import restriction_fingerprint
from products.access_control.backend.facade.user_access_control import UserAccessControlError
from products.customer_analytics.backend.constants import ACTIVITY_QUERY_PROPERTY_ACCESS_LABEL_PREFIX

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User


def get_activity_query_property_access_label(team: "Team", user: "User | None") -> str:
    from products.access_control.backend.facade.api import (  # noqa: PLC0415 -- keeps property access models off the facade import path
        get_restricted_properties_with_group_type_index_for_team,
    )

    restrictions = get_restricted_properties_with_group_type_index_for_team(team_id=team.id, user=user)
    return f"{ACTIVITY_QUERY_PROPERTY_ACCESS_LABEL_PREFIX}{restriction_fingerprint(restrictions)}"


def validate_activity_query_property_access(team: "Team", user: "User | None", labels: list[str]) -> None:
    fingerprints = [label for label in labels if label.startswith(ACTIVITY_QUERY_PROPERTY_ACCESS_LABEL_PREFIX)]
    if user is None or fingerprints != [get_activity_query_property_access_label(team, user)]:
        raise UserAccessControlError("account", "viewer")
