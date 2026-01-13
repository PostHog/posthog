from unittest.mock import patch

from parameterized import parameterized

from posthog.clickhouse.query_weight import (
    HEAVY_DURATION_MS,
    HEAVY_EXCEPTION_CODES,
    HEAVY_READ_BYTES,
    QueryWeight,
    get_query_weight,
)


class TestGetQueryWeight:
    @parameterized.expand(
        [
            ("cohort_id", {"cohort_id": 123}, "lc_cohort_id = %(entity_id)s"),
            ("experiment_id", {"experiment_id": 456}, "lc_experiment_id = %(entity_id)s"),
            ("insight_id", {"insight_id": 789}, "lc_insight_id = %(entity_id)s"),
        ]
    )
    @patch("posthog.clickhouse.query_weight.sync_execute")
    def test_queries_correct_filter(self, _name, kwargs, expected_filter, mock_sync_execute):
        mock_sync_execute.return_value = [(10, 0)]

        get_query_weight(team_id=1, **kwargs)

        call_args = mock_sync_execute.call_args
        query = call_args[0][0]
        assert expected_filter in query

    def test_returns_unsupported_when_no_entity_id_provided(self):
        result = get_query_weight(team_id=1)
        assert result == QueryWeight.UNSUPPORTED

    @parameterized.expand(
        [
            ("empty_result", [], QueryWeight.UNDECISIVE),
            ("zero_queries", [(0, 0)], QueryWeight.UNDECISIVE),
            ("normal_queries", [(10, 0)], QueryWeight.NORMAL),
            ("some_heavy", [(10, 3)], QueryWeight.HEAVY),
            ("all_heavy", [(5, 5)], QueryWeight.HEAVY),
            ("single_heavy", [(1, 1)], QueryWeight.HEAVY),
        ]
    )
    @patch("posthog.clickhouse.query_weight.sync_execute")
    def test_return_values(self, _name, db_result, expected, mock_sync_execute):
        mock_sync_execute.return_value = db_result

        result = get_query_weight(team_id=1, cohort_id=123)

        assert result == expected

    @patch("posthog.clickhouse.query_weight.sync_execute")
    def test_passes_correct_thresholds(self, mock_sync_execute):
        mock_sync_execute.return_value = [(10, 0)]

        get_query_weight(team_id=1, cohort_id=123)

        call_args = mock_sync_execute.call_args
        params = call_args[0][1]
        assert params["heavy_exception_codes"] == HEAVY_EXCEPTION_CODES
        assert params["heavy_read_bytes"] == HEAVY_READ_BYTES
        assert params["heavy_duration_ms"] == HEAVY_DURATION_MS

    @patch("posthog.clickhouse.query_weight.sync_execute")
    def test_passes_team_id(self, mock_sync_execute):
        mock_sync_execute.return_value = [(10, 0)]

        get_query_weight(team_id=42, cohort_id=123)

        call_args = mock_sync_execute.call_args
        query = call_args[0][0]
        params = call_args[0][1]
        assert "team_id = %(team_id)s" in query
        assert params["team_id"] == 42

    @patch("posthog.clickhouse.query_weight.sync_execute")
    def test_uses_meta_user(self, mock_sync_execute):
        from posthog.clickhouse.client.connection import ClickHouseUser

        mock_sync_execute.return_value = [(10, 0)]

        get_query_weight(team_id=1, cohort_id=123)

        call_args = mock_sync_execute.call_args
        assert call_args.kwargs["ch_user"] == ClickHouseUser.META

    @patch("posthog.clickhouse.query_weight.sync_execute")
    def test_returns_undecisive_on_exception(self, mock_sync_execute):
        mock_sync_execute.side_effect = Exception("Database error")

        result = get_query_weight(team_id=1, cohort_id=123)

        assert result == QueryWeight.UNDECISIVE
