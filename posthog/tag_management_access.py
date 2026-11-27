from typing import TYPE_CHECKING, Any

from django.conf import settings

import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.utils import flag_identity, get_instance_realm

if TYPE_CHECKING:
    from posthog.models import Team, User


def tag_management_enabled(user: "User", team: "Team", serializer_context: dict[str, Any]) -> bool:
    if "tag-management" in settings.PERSISTED_FEATURE_FLAGS:
        return True
    try:
        from posthog.api.organization import OrganizationSerializer

        organization = team.organization
        organization_serializer = OrganizationSerializer(context=serializer_context)
        identity = flag_identity(
            user,
            team,
            organization,
            member_count=organization_serializer.get_member_count(organization),
            project_count=len(organization_serializer.get_teams(organization)),
        )
        if identity is None:
            return False
        return (
            posthoganalytics.feature_enabled(
                "tag-management",
                identity.distinct_id,
                groups=identity.groups,
                person_properties={**identity.person_properties, "realm": get_instance_realm()},
                group_properties=identity.group_properties,
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
            is True
        )
    except Exception as error:
        capture_exception(error)
        return False
