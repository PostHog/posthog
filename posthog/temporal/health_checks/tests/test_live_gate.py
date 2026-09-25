from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Team
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.live_gate import live_flag_key, live_team_ids
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


class TestLiveTeamIds(SimpleTestCase):
    @parameterized.expand(
        [
            ("flag_on_beats_a_dry_default", True, True, True),
            ("flag_on_agrees_with_a_live_default", True, False, True),
            ("flag_off_beats_a_live_default", False, False, False),
            ("flag_off_agrees_with_a_dry_default", False, True, False),
            ("no_flag_leaves_a_dry_check_dry", None, True, False),
            ("no_flag_leaves_a_live_check_live", None, False, True),
            ("a_variant_never_promotes_a_dry_check", "live", True, False),
        ]
    )
    def test_posture(self, _name: str, flag_value: bool | str | None, default_dry_run: bool, is_live: bool) -> None:
        with patch(
            "posthog.temporal.health_checks.live_gate.get_feature_flag_or_none",
            return_value=flag_value,
        ):
            live = live_team_ids(KIND, [1], default_dry_run=default_dry_run)

        assert live == ({1} if is_live else set())

    def test_the_flag_read_targets_the_team_by_distinct_id_and_project_group(self) -> None:
        with patch(
            "posthog.temporal.health_checks.live_gate.get_feature_flag_or_none",
            return_value=None,
        ) as read:
            live_team_ids(KIND, [7], default_dry_run=True)

        assert read.call_args.args == ("health-check-test-live-gate-live", "team_7")
        assert read.call_args.kwargs["groups"] == {"project": "7"}
        assert read.call_args.kwargs["group_properties"] == {"project": {"id": "7"}}

    def test_a_failed_flag_read_leaves_every_team_on_its_default(self) -> None:
        # Patched inside ph_client because get_feature_flag_or_none swallows the exception
        # itself, so patching at the live_gate import site would test a path that cannot happen.
        with patch(
            "posthog.ph_client.posthoganalytics.get_feature_flag",
            side_effect=RuntimeError("flag service down"),
        ):
            assert live_team_ids(KIND, [1, 2], default_dry_run=True) == set()


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

    def _detect_both(self, _team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        return {
            team.id: [HealthCheckResult(severity=HealthIssue.Severity.WARNING, payload={}, hash_keys=[])]
            for team in (self.team, self.dry_team)
        }

    def _seed_active_issue(self, team: Team) -> None:
        HealthIssue.objects.create(
            team=team,
            kind=KIND,
            severity=HealthIssue.Severity.WARNING,
            payload={},
            unique_hash=HealthIssue.compute_unique_hash(KIND, {}, []),
            status=HealthIssue.Status.ACTIVE,
        )

    def test_only_a_flagged_team_gets_issues_and_alerts(self) -> None:
        with (
            _live_for({self.team.id}),
            patch("posthog.temporal.health_checks.processing.emit_health_check_alert") as alert,
        ):
            result = _process_batch_detection([self.team.id, self.dry_team.id], KIND, self._detect_both, dry_run=True)

        assert self._active(self.team) == 1
        assert self._active(self.dry_team) == 0
        assert result.issues_upserted == 1
        assert {call.args[0].team_id for call in alert.call_args_list} == {self.team.id}

    def test_a_live_run_resolves_only_the_live_teams_issues(self) -> None:
        self._seed_active_issue(self.team)
        self._seed_active_issue(self.dry_team)

        with (
            _live_for({self.team.id}),
            patch("posthog.temporal.health_checks.processing.emit_health_check_alert"),
        ):
            result = _process_batch_detection([self.team.id, self.dry_team.id], KIND, lambda _ids: {}, dry_run=True)

        assert self._active(self.team) == 0
        assert self._active(self.dry_team) == 1
        assert result.issues_resolved == 1

    def test_a_kind_with_no_flag_and_a_dry_default_writes_nothing(self) -> None:
        with (
            _live_for(set()),
            patch("posthog.temporal.health_checks.processing.emit_health_check_alert"),
        ):
            _process_batch_detection([self.team.id, self.dry_team.id], KIND, self._detect_both, dry_run=True)

        assert self._active(self.team) == 0
        assert self._active(self.dry_team) == 0

    def test_a_kind_with_no_flag_and_a_live_default_writes_for_every_team(self) -> None:
        with (
            _live_for(set()),
            patch("posthog.temporal.health_checks.processing.emit_health_check_alert"),
        ):
            _process_batch_detection([self.team.id, self.dry_team.id], KIND, self._detect_both, dry_run=False)

        assert self._active(self.team) == 1
        assert self._active(self.dry_team) == 1
