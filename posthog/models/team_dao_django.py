"""Django ORM implementation of TeamDAO for HogQL.

This module provides the concrete implementation of the TeamDAO interface
using Django ORM to fetch team data and convert it to TeamDTO objects.
"""

from typing import Optional

from posthog.hogql.team_dao import TeamDAO
from posthog.hogql.team_dto import TeamDTO
from posthog.models.team import Team


class DjangoTeamDAO(TeamDAO):
    """Django ORM implementation of TeamDAO.

    This implementation fetches team data using Django ORM and converts
    it to immutable TeamDTO objects for use within the HogQL subsystem.
    """

    def get_by_id(self, team_id: int) -> Optional[TeamDTO]:
        """Retrieve a team by its ID using Django ORM.

        Args:
            team_id: The unique identifier for the team

        Returns:
            TeamDTO if found, None otherwise
        """
        try:
            team = Team.objects.select_related("organization").get(id=team_id)
            return self._convert_to_dto(team)
        except Team.DoesNotExist:
            return None

    def _convert_to_dto(self, team: Team) -> TeamDTO:
        """Convert a Django Team model instance to a TeamDTO.

        Args:
            team: Django Team model instance

        Returns:
            Immutable TeamDTO object
        """
        # Get computed/derived values that HogQL needs
        person_on_events_mode_flag_based_default = team.person_on_events_mode_flag_based_default.value
        person_on_events_mode = team.person_on_events_mode.value
        default_modifiers = team.default_modifiers

        # Get timezone info as string representation
        timezone_info = str(team.timezone_info) if hasattr(team, "timezone_info") else team.timezone

        # Get path cleaning filter models as serialized data
        try:
            path_cleaning_filter_models_data = [
                {
                    "alias": filter_model.alias,
                    "regex": filter_model.regex,
                }
                for filter_model in team.path_cleaning_filter_models()
            ]
        except Exception:
            # Fallback if path_cleaning_filter_models method fails
            path_cleaning_filter_models_data = []

        return TeamDTO(
            id=team.id,
            uuid=team.uuid,
            project_id=team.project_id,
            timezone=team.timezone,
            week_start_day=team.week_start_day,
            modifiers=team.modifiers,
            test_account_filters=team.test_account_filters,
            path_cleaning_filters=team.path_cleaning_filters,
            organization_id=team.organization.id,
            person_on_events_mode_flag_based_default=person_on_events_mode_flag_based_default,
            person_on_events_mode=person_on_events_mode,
            default_modifiers=default_modifiers,
            timezone_info=timezone_info,
            path_cleaning_filter_models_data=path_cleaning_filter_models_data,
        )
