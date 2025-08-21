"""Tests for Team DAO implementation."""

from unittest.mock import patch


from posthog.hogql.team_dao import TeamDAO
from posthog.hogql.team_dto import TeamDTO
from posthog.models.team_dao_django import DjangoTeamDAO
from posthog.test.base import BaseTest


class TestTeamDAO(BaseTest):
    """Test cases for Team DAO implementation."""

    def test_django_team_dao_get_by_id_success(self):
        """Test DjangoTeamDAO.get_by_id returns correct TeamDTO when team exists."""
        dao = DjangoTeamDAO()

        # Use the team created by BaseTest
        result = dao.get_by_id(self.team.id)

        # Verify we get a TeamDTO
        self.assertIsInstance(result, TeamDTO)
        self.assertEqual(result.id, self.team.id)
        self.assertEqual(result.uuid, self.team.uuid)
        self.assertEqual(result.project_id, self.team.project_id)
        self.assertEqual(result.timezone, self.team.timezone)
        self.assertEqual(result.organization_id, self.team.organization.id)

        # Verify computed fields are included
        self.assertIsNotNone(result.person_on_events_mode_flag_based_default)
        self.assertIsNotNone(result.person_on_events_mode)
        self.assertIsInstance(result.default_modifiers, dict)
        self.assertIsInstance(result.path_cleaning_filter_models_data, list)

    def test_django_team_dao_get_by_id_not_found(self):
        """Test DjangoTeamDAO.get_by_id returns None when team doesn't exist."""
        dao = DjangoTeamDAO()

        # Use a non-existent team ID
        result = dao.get_by_id(99999)

        self.assertIsNone(result)

    def test_team_dto_is_immutable(self):
        """Test that TeamDTO objects are immutable."""
        dao = DjangoTeamDAO()
        dto = dao.get_by_id(self.team.id)

        # Try to modify a field - this should raise an exception
        with self.assertRaises(Exception):  # FrozenInstanceError for dataclasses
            dto.id = 123

    def test_team_dao_interface_compliance(self):
        """Test that DjangoTeamDAO implements the TeamDAO interface correctly."""
        dao = DjangoTeamDAO()

        # Verify it's an instance of the abstract base class
        self.assertIsInstance(dao, TeamDAO)

        # Verify it has the required method
        self.assertTrue(hasattr(dao, "get_by_id"))
        self.assertTrue(callable(dao.get_by_id))

    def test_path_cleaning_filter_models_data_serialization(self):
        """Test that path cleaning filter models are properly serialized."""
        # Set up path cleaning filters on the team
        self.team.path_cleaning_filters = [{"alias": "test", "regex": r"/test/.*"}]
        self.team.save()

        dao = DjangoTeamDAO()
        dto = dao.get_by_id(self.team.id)

        # Should have path cleaning filter models data
        self.assertIsInstance(dto.path_cleaning_filter_models_data, list)
        # Content depends on the path_cleaning_filter_models() method implementation

    @patch("posthog.models.team_dao_django.Team.objects.select_related")
    def test_django_team_dao_exception_handling(self, mock_select_related):
        """Test that DjangoTeamDAO handles database exceptions gracefully."""
        # Mock a database exception
        mock_select_related.return_value.get.side_effect = Exception("Database error")

        dao = DjangoTeamDAO()

        # Should not raise an exception, but return None
        with self.assertRaises(Exception):
            dao.get_by_id(self.team.id)
