"""Read and write the team-level data quality configuration."""

from typing import TYPE_CHECKING

from posthog.models.team.extensions import get_or_create_team_extension

from ..models import TeamDataQualityConfig

if TYPE_CHECKING:
    from posthog.models.team import Team


def get_gate_config(team: "Team") -> TeamDataQualityConfig:
    return get_or_create_team_extension(team, TeamDataQualityConfig)


def set_gate_materialization_on_checks(team: "Team", enabled: bool) -> TeamDataQualityConfig:
    config = get_or_create_team_extension(team, TeamDataQualityConfig)
    config.gate_materialization_on_checks = enabled
    config.save(update_fields=["gate_materialization_on_checks"])
    return config
