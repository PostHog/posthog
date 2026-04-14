from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from posthog.models.feature_flag.cross_project_evaluations import get_evaluations_7d_by_team


class TestCrossProjectEvaluations(ClickhouseTestMixin, APIBaseTest):
    def test_returns_zero_when_no_events(self):
        counts, available = get_evaluations_7d_by_team("some_key", [self.team.id])
        assert available is True
        assert counts == {self.team.id: 0}

    def test_counts_events_by_team(self):
        other_team = self.organization.teams.create(name="Other")
        _create_event(
            team=self.team,
            distinct_id="u1",
            event="$feature_flag_called",
            properties={"$feature_flag": "my_flag", "$feature_flag_response": True},
        )
        _create_event(
            team=self.team,
            distinct_id="u2",
            event="$feature_flag_called",
            properties={"$feature_flag": "my_flag", "$feature_flag_response": False},
        )
        _create_event(
            team=other_team,
            distinct_id="u3",
            event="$feature_flag_called",
            properties={"$feature_flag": "my_flag", "$feature_flag_response": True},
        )
        _create_event(
            team=self.team,
            distinct_id="u4",
            event="$feature_flag_called",
            properties={"$feature_flag": "unrelated", "$feature_flag_response": True},
        )
        flush_persons_and_events()

        counts, available = get_evaluations_7d_by_team("my_flag", [self.team.id, other_team.id])

        assert available is True
        assert counts == {self.team.id: 2, other_team.id: 1}

    def test_returns_available_false_when_clickhouse_fails(self):
        with patch(
            "posthog.models.feature_flag.cross_project_evaluations.sync_execute",
            side_effect=RuntimeError("boom"),
        ):
            counts, available = get_evaluations_7d_by_team("my_flag", [self.team.id, 99])

        assert available is False
        assert counts == {self.team.id: 0, 99: 0}
