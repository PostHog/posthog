from typing import TYPE_CHECKING

import posthoganalytics

if TYPE_CHECKING:
    from posthog.models import Team


GITHUB_SYNC_FEATURE_FLAG = "data-modeling-github-sync"


def is_github_sync_enabled(team: "Team") -> bool:
    return posthoganalytics.feature_enabled(
        GITHUB_SYNC_FEATURE_FLAG,
        str(team.uuid),
        groups={
            "organization": str(team.organization_id),
            "project": str(team.id),
        },
        group_properties={
            "organization": {"id": str(team.organization_id)},
            "project": {"id": str(team.id)},
        },
    )
