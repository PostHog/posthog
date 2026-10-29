"""Per-team delivery flags, kept out of `evaluation` so readers at Django startup skip the delivery runtime."""

from __future__ import annotations

from typing import TYPE_CHECKING

import posthoganalytics

if TYPE_CHECKING:
    from posthog.models import Team


def team_flag_enabled(flag: str, team: Team) -> bool | None:
    """None when the flag could not be evaluated: the SDK logs and swallows a failed lookup, and it
    answers None for a flag that does not exist too."""
    return posthoganalytics.feature_enabled(
        flag,
        str(team.uuid),
        groups={"organization": str(team.organization_id), "project": str(team.id)},
        group_properties={
            "organization": {"id": str(team.organization_id)},
            # Both regions read flags from one PostHog project, and project ids repeat across
            # regions. A condition on the uuid names one team in one region.
            "project": {"id": str(team.id), "uuid": str(team.uuid)},
        },
        # This runs in a Temporal activity, where a captured event is silently dropped.
        send_feature_flag_events=False,
    )
