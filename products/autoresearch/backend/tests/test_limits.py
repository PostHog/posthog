from typing import Any

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from structlog.testing import capture_logs

from products.autoresearch.backend.limits import (
    DEFAULT_MAX_ITERATIONS_PER_RUN,
    DEFAULT_MAX_LIVE_PIPELINES,
    DEFAULT_MAX_TRAINING_RUNS_PER_DAY,
    LimitSource,
    LimitSources,
    TeamLimits,
    limits_for_team,
)

TEAM_ID = 7

LIMITS_PAYLOAD = {"team_configs": {str(TEAM_ID): {"max_training_runs_per_day": 10}}}
ACCESS_PAYLOAD = {"team_configs": {str(TEAM_ID): {"max_training_runs_per_day": 5}}}


class TestLimitsForTeam(SimpleTestCase):
    def _limits(self, payloads: dict[str, Any], *, cloud: bool = False) -> TeamLimits:
        with (
            patch(
                "products.autoresearch.backend.limits.posthoganalytics.get_feature_flag_payload",
                side_effect=lambda flag_key, *_args, **_kwargs: payloads.get(flag_key),
            ),
            patch("products.autoresearch.backend.limits.is_cloud", return_value=cloud),
        ):
            return limits_for_team(TEAM_ID)

    @parameterized.expand(
        [
            ("limits_flag_wins", {"autoresearch-limits": LIMITS_PAYLOAD, "autoresearch": ACCESS_PAYLOAD}, 10),
            ("limits_flag_alone", {"autoresearch-limits": LIMITS_PAYLOAD}, 10),
            ("falls_back_to_the_access_flag", {"autoresearch": ACCESS_PAYLOAD}, 5),
            (
                "json_string_payload",
                {"autoresearch-limits": '{"default_team_config": {"max_training_runs_per_day": 4}}'},
                4,
            ),
        ]
    )
    def test_reads_the_payload_from_the_limits_flag_first(
        self, _name: str, payloads: dict[str, Any], expected: int
    ) -> None:
        assert self._limits(payloads).max_training_runs_per_day == expected

    @parameterized.expand([("cloud", True, 1), ("self_hosted", False, 0)])
    def test_no_payload_uses_the_code_defaults_and_warns_on_cloud_only(
        self, _name: str, cloud: bool, expected_warnings: int
    ) -> None:
        with capture_logs() as logs:
            limits = self._limits({}, cloud=cloud)

        assert limits == TeamLimits(
            max_training_runs_per_day=DEFAULT_MAX_TRAINING_RUNS_PER_DAY,
            max_iterations_per_run=DEFAULT_MAX_ITERATIONS_PER_RUN,
            max_live_pipelines=DEFAULT_MAX_LIVE_PIPELINES,
            sources=LimitSources(),
        )
        warnings = [log for log in logs if log["event"] == "autoresearch_limits_payload_missing"]
        assert len(warnings) == expected_warnings

    def test_a_served_payload_does_not_warn(self) -> None:
        with capture_logs() as logs:
            self._limits({"autoresearch-limits": LIMITS_PAYLOAD}, cloud=True)

        assert not [log for log in logs if log["event"] == "autoresearch_limits_payload_missing"]

    def test_each_limit_reports_the_layer_it_came_from(self) -> None:
        payload = {
            "default_team_config": {"max_iterations_per_run": 12, "max_live_pipelines": 4},
            # A value below the minimum falls through to the next layer.
            "team_configs": {str(TEAM_ID): {"max_training_runs_per_day": 9, "max_iterations_per_run": 0}},
        }

        limits = self._limits({"autoresearch-limits": payload})

        assert limits == TeamLimits(
            max_training_runs_per_day=9,
            max_iterations_per_run=12,
            max_live_pipelines=4,
            sources=LimitSources(
                max_training_runs_per_day=LimitSource.PROJECT,
                max_iterations_per_run=LimitSource.DEFAULT,
                max_live_pipelines=LimitSource.DEFAULT,
            ),
        )
