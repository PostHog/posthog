"""Example usage of the Team DAO pattern for HogQL.

This module demonstrates how to use the TeamDAO interface
and its Django implementation to access team data in HogQL code.
"""

from typing import Optional

from posthog.hogql.team_dao import TeamDAO
from posthog.hogql.team_dto import TeamDTO
from posthog.models.team_dao_django import DjangoTeamDAO


def example_usage():
    """Example of how to use the Team DAO in HogQL code."""
    # Use the Django implementation of the DAO
    team_dao: TeamDAO = DjangoTeamDAO()

    # Get a team by ID
    team_id = 1
    team_dto: Optional[TeamDTO] = team_dao.get_by_id(team_id)

    if team_dto is None:
        return None

    # Access team fields needed by HogQL
    # team_dto.id, team_dto.uuid, team_dto.project_id
    # team_dto.timezone, team_dto.organization_id

    # Access computed fields
    # team_dto.person_on_events_mode, team_dto.default_modifiers

    # Access configuration
    # team_dto.test_account_filters, team_dto.path_cleaning_filters

    return team_dto


def example_dependency_injection():
    """Example of using dependency injection with the DAO interface."""

    def hogql_function_that_needs_team_data(team_dao: TeamDAO, team_id: int):
        """Example HogQL function that takes a DAO as dependency."""
        team = team_dao.get_by_id(team_id)
        if team is None:
            raise ValueError(f"Team {team_id} not found")

        # Use team data for HogQL operations
        return {
            "timezone": team.timezone,
            "project_id": team.project_id,
            "person_on_events_mode": team.person_on_events_mode,
        }

    # In production, use the Django implementation
    production_dao = DjangoTeamDAO()
    result = hogql_function_that_needs_team_data(production_dao, 1)

    # In tests, you could easily mock the DAO or use a test implementation
    # This demonstrates the benefit of the DAO pattern for testing

    return result


if __name__ == "__main__":
    example_usage()
    example_dependency_injection()
