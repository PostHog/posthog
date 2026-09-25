from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Team
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.live_gate import live_flag_key, partition_teams_by_posture
from posthog.temporal.health_checks.models import HealthCheckResult
from posthog.temporal.health_checks.processing import _process_batch_detection

KIND = "test_live_gate"


class TestLiveFlagKey(SimpleTestCase):
    @parameterized.expand(
        [
            ("stale_feature_flags", "health-check-stale-feature-flags-live"),
            ("external_data_failure", "health-check-external-data-failure-live"),
        ]
    )
    def test_key_spells_the_kind_with_hyphens(self, kind: str, expected: str) -> None:
        assert live_flag_key(kind) == expected


class TestPartitionTeamsByPosture(SimpleTestCase):
    @parameterized.expand(
        [
            ("flag_on_beats_a_dry_default", True, True, ([1], [])),
            ("flag_on_agrees_with_a_live_default", True, False, ([1], [])),
            ("flag_off_beats_a_live_default", False, False, ([], [1])),
            ("flag_off_agrees_with_a_dry_default", False, True, ([], [1])),
            ("no_flag_leaves_a_dry_check_dry", None, True, ([], [1])),
            ("no_flag_leaves_a_live_check_live", None, False, ([1], [])),
            ("a_variant_never_promotes_a_dry_check", "live", True, ([], [1])),
        ]
    )
    def test_posture(
        self,
        _name: str,
        flag_value: bool | str | None,
        default_dry_run: bool,
        expected: tuple[list[int], list[int]],
    ) -> None:
        with patch(
            "posthog.temporal.health_checks.live_gate.get_feature_flag_or_none",
            return_value=flag_value,
        ):
            assert partition_teams_by_posture(KIND, [1], default_dry_run=default_dry_run) == expected

    def test_a_failed_flag_read_leaves_every_team_on_its_default(self) -> None:
        with patch(
            "posthog.ph_client.posthoganalytics.get_feature_flag",
            side_effect=RuntimeError("flag service down"),
        ):
            assert partition_teams_by_posture(KIND, [1, 2], default_dry_run=True) == ([], [1, 2])


def _issue_for(team_id: int) -> dict[int, list[HealthCheckResult]]:
    return {
        team_id: [HealthCheckResult(severity=HealthIssue.Severity.WARNING, payload={}, hash_keys=[])],
    }


def _live_for(team_ids: set[int]) -> Any:
    live_distinct_ids = {f"team_{team_id}" for team_id in team_ids}

    def read(_key: str, distinct_id: str, **_kwargs: Any) -> bool | None:
        return True if distinct_id in live_distinct_ids else None

    return patch("posthog.temporal.health_checks.live_gate.get_feature_flag_or_none", side_effect=read)


class TestWritesAreScopedToLiveTeams(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dry_team = Team.objects.create(organization=self.organization, name="dry")

    def _active(self, team: Team) -> int:
        return HealthIssue.objects.filter(team=team, kind=KIND, status=HealthIssue.Status.ACTIVE).count()

    def test_only_a_flagged_team_gets_issues_and_alerts(self) -> None:
        def detect(team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
            return {**_issue_for(self.team.id), **_issue_for(self.dry_team.id)}

        with (
            _live_for({self.team.id}),
            patch("posthog.temporal.health_checks.processing.emit_health_check_alert") as alert,
        ):
            result = _process_batch_detection([self.team.id, self.dry_team.id], KIND, detect, dry_run=True)

        assert self._active(self.team) == 1
        assert self._active(self.dry_team) == 0
        assert result.issues_upserted == 1
        assert {call.args[0].team_id for call in alert.call_args_list} == {self.team.id}

    def test_a_dry_teams_issues_are_not_resolved_by_a_live_run(self) -> None:
        HealthIssue.objects.create(
            team=self.dry_team,
            kind=KIND,
            severity=HealthIssue.Severity.WARNING,
            payload={},
            unique_hash=HealthIssue.compute_unique_hash(KIND, {}, []),
            status=HealthIssue.Status.ACTIVE,
        )

        with (
            _live_for({self.team.id}),
            patch("posthog.temporal.health_checks.processing.emit_health_check_alert"),
        ):
            result = _process_batch_detection([self.team.id, self.dry_team.id], KIND, lambda _ids: {}, dry_run=True)

        assert self._active(self.dry_team) == 1
        assert result.issues_resolved == 0

    @parameterized.expand(
        [
            ("dry_check_writes_nothing", True, 0),
            ("live_check_writes_everything", False, 2),
        ]
    )
    def test_a_kind_with_no_flag_keeps_its_registered_posture(self, _name: str, dry_run: bool, expected: int) -> None:
        def detect(team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
            return {**_issue_for(self.team.id), **_issue_for(self.dry_team.id)}

        with (
            _live_for(set()),
            patch("posthog.temporal.health_checks.processing.emit_health_check_alert"),
        ):
            _process_batch_detection([self.team.id, self.dry_team.id], KIND, detect, dry_run=dry_run)

        assert self._active(self.team) + self._active(self.dry_team) == expected
