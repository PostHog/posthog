from typing import TYPE_CHECKING

from posthog.ph_client import feature_enabled_or_false

if TYPE_CHECKING:
    from posthog.models.team import Team

MANAGED_VIEWSETS_FEATURE_FLAG = "managed-viewsets"


def is_managed_viewset_enabled(team: "Team") -> bool:
    return feature_enabled_or_false(
        MANAGED_VIEWSETS_FEATURE_FLAG,
        str(team.uuid),
        groups={
            "organization": str(team.organization_id),
            "project": str(team.id),
        },
        group_properties={
            "organization": {
                "id": str(team.organization_id),
            },
            "project": {
                "id": str(team.id),
            },
        },
        send_feature_flag_events=False,
    )
