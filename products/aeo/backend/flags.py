"""Feature-flag evaluation for AEO's scheduled, person-less code paths."""

from __future__ import annotations

from typing import TYPE_CHECKING

from posthog.ph_client import feature_enabled_or_false

if TYPE_CHECKING:
    from posthog.models.team import Team


def aeo_flag_enabled(flag: str, team: Team) -> bool:
    """Fail-closed: the flag defaults off and an evaluation error reads as off.

    No person is behind a scheduled run, so the team UUID keeps the flag call
    well-formed. The organization group and its id property let a flag target
    teams through the organization.
    """
    organization_id = str(team.organization_id)
    return feature_enabled_or_false(
        flag,
        str(team.uuid),
        groups={"organization": organization_id},
        group_properties={"organization": {"id": organization_id}},
    )
