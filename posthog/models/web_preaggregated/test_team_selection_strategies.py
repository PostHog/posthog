"""
Unit tests for web analytics team selection strategies.
"""

from unittest.mock import Mock, patch

from posthog.models.web_preaggregated.team_selection_strategies import get_teams_with_missing_data


class TestGetTeamsWithMissingData:
    """Test the get_teams_with_missing_data function."""

    @patch("posthog.models.web_preaggregated.team_selection_strategies.sync_execute")
    @patch("posthog.models.web_preaggregated.team_selection_strategies.Team")
    def test_returns_empty_when_no_enabled_teams(self, mock_team, mock_sync_execute):
        """Test that empty set is returned when no teams have web analytics enabled."""
        # Mock no teams with web analytics enabled
        mock_team.objects.filter.return_value.values_list.return_value = []

        context = Mock()
        result = get_teams_with_missing_data(context)

        assert result == set()
        context.log.info.assert_called_with("No teams have web analytics pre-aggregated tables enabled")
        mock_sync_execute.assert_not_called()

    @patch("posthog.models.web_preaggregated.team_selection_strategies.sync_execute")
    @patch("posthog.models.web_preaggregated.team_selection_strategies.Team")
    def test_validates_team_ids_correctly(self, mock_team, mock_sync_execute):
        """Test that team IDs are properly validated to prevent SQL injection."""
        # Mock teams with mixed valid/invalid IDs
        mock_team.objects.filter.return_value.values_list.return_value = [1, 2, -1, "invalid", None, 0]
        mock_sync_execute.return_value = [(1,), (2,)]

        context = Mock()
        result = get_teams_with_missing_data(context)

        # Should only pass valid positive integers to SQL query
        call_args = mock_sync_execute.call_args[1]
        assert call_args["team_ids"] == (1, 2)
        assert result == {1, 2}

        # Should log warnings for invalid IDs
        context.log.warning.assert_any_call("Invalid team ID found: -1, skipping")
        context.log.warning.assert_any_call("Invalid team ID found: invalid, skipping")

    @patch("posthog.models.web_preaggregated.team_selection_strategies.sync_execute")
    @patch("posthog.models.web_preaggregated.team_selection_strategies.Team")
    def test_returns_teams_with_missing_data(self, mock_team, mock_sync_execute):
        """Test that teams with missing data are correctly identified."""
        mock_team.objects.filter.return_value.values_list.return_value = [1, 2, 3, 4]
        # Teams 1 and 3 have missing data
        mock_sync_execute.return_value = [(1,), (3,)]

        context = Mock()
        result = get_teams_with_missing_data(context, lookback_days=7)

        assert result == {1, 3}

        # Verify SQL query includes lookback_days parameter
        call_args = mock_sync_execute.call_args
        assert call_args[1]["lookback_days"] == 7
        assert call_args[1]["team_ids"] == (1, 2, 3, 4)

    @patch("posthog.models.web_preaggregated.team_selection_strategies.sync_execute")
    @patch("posthog.models.web_preaggregated.team_selection_strategies.Team")
    def test_handles_sql_query_exceptions(self, mock_team, mock_sync_execute):
        """Test that SQL query exceptions are handled gracefully."""
        mock_team.objects.filter.return_value.values_list.return_value = [1, 2]
        mock_sync_execute.side_effect = Exception("Database connection error")

        context = Mock()
        result = get_teams_with_missing_data(context)

        assert result == set()
        context.log.warning.assert_called_with("Failed to identify teams with missing data: Database connection error")

    @patch("posthog.models.web_preaggregated.team_selection_strategies.sync_execute")
    @patch("posthog.models.web_preaggregated.team_selection_strategies.Team")
    def test_filters_non_integer_results(self, mock_team, mock_sync_execute):
        """Test that non-integer results from SQL are filtered out."""
        mock_team.objects.filter.return_value.values_list.return_value = [1, 2, 3]
        # SQL returns mixed types (shouldn't happen in practice, but defensive)
        mock_sync_execute.return_value = [(1,), ("invalid",), (3,), (None,)]

        context = Mock()
        result = get_teams_with_missing_data(context)

        # Should only include valid integers
        assert result == {1, 3}

    @patch("posthog.models.web_preaggregated.team_selection_strategies.sync_execute")
    @patch("posthog.models.web_preaggregated.team_selection_strategies.Team")
    def test_custom_lookback_days_parameter(self, mock_team, mock_sync_execute):
        """Test that custom lookback_days parameter is used correctly."""
        mock_team.objects.filter.return_value.values_list.return_value = [1, 2]
        mock_sync_execute.return_value = [(1,)]

        context = Mock()
        get_teams_with_missing_data(context, lookback_days=14)

        # Verify custom lookback_days is passed to SQL
        call_args = mock_sync_execute.call_args[1]
        assert call_args["lookback_days"] == 14

        # Verify logging includes the lookback_days
        context.log.info.assert_called_with(
            "Found 1 teams with missing pre-aggregated data out of 2 enabled teams (looking back 14 days)"
        )

    @patch("posthog.models.web_preaggregated.team_selection_strategies.sync_execute")
    @patch("posthog.models.web_preaggregated.team_selection_strategies.Team")
    def test_handles_django_orm_exceptions(self, mock_team, mock_sync_execute):
        """Test that Django ORM exceptions are handled gracefully."""
        mock_team.objects.filter.side_effect = Exception("Django ORM error")

        context = Mock()
        result = get_teams_with_missing_data(context)

        assert result == set()
        context.log.warning.assert_called_with("Failed to identify teams with missing data: Django ORM error")

    @patch("posthog.models.web_preaggregated.team_selection_strategies.sync_execute")
    @patch("posthog.models.web_preaggregated.team_selection_strategies.Team")
    def test_no_valid_team_ids_after_validation(self, mock_team, mock_sync_execute):
        """Test handling when all team IDs are invalid after validation."""
        mock_team.objects.filter.return_value.values_list.return_value = [-1, "invalid", None, 0]

        context = Mock()
        result = get_teams_with_missing_data(context)

        assert result == set()
        context.log.warning.assert_called_with("No valid team IDs found after validation")
        mock_sync_execute.assert_not_called()
