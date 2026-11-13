from datetime import UTC, datetime

from posthog.test.base import BaseTest
from unittest import mock

from django.test import override_settings

from parameterized import parameterized

from products.cohorts.backend.cohort_enablement import RealtimeTurnOnRefused, turn_realtime_off, turn_realtime_on
from products.cohorts.backend.models.backfill import (
    CohortBackfillKind,
    CohortBackfillRun,
    CohortBackfillRunCohort,
    CohortBackfillRunStatus,
    CohortBackfillScope,
    CohortBackfillTrigger,
)
from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.cohorts.backend.models.team_access import (
    RealtimeCohortAccessPurpose,
    RealtimeCohortLevel,
    RealtimeCohortTeamAccess,
)
from products.cohorts.backend.realtime_state import CohortRealtimeState, resolve_realtime_readiness
from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig

_BYTECODE = ["_H", 1, 32, "matched", 32, "event", 1, 1, 11]
PAGEVIEW_LEAF = {
    "type": "behavioral",
    "key": "$pageview",
    "event_type": "events",
    "value": "performed_event",
    "time_value": 7,
    "time_interval": "day",
    "conditionHash": "pageview00000000",
    "bytecode": _BYTECODE,
}
PERSON_LEAF = {
    "type": "person",
    "key": "email",
    "value": ["person@example.com"],
    "operator": "exact",
    "conditionHash": "email00000000000",
    "bytecode": _BYTECODE,
}
FLAG_CALL_LEAF = {
    "type": "behavioral",
    "key": "$feature_flag_called",
    "event_type": "events",
    "value": "performed_event",
    "time_value": 30,
    "time_interval": "day",
    "event_filters": [{"key": "$feature_flag", "type": "event", "value": "beta-feature", "operator": "exact"}],
    "conditionHash": "flagcall00000001",
    "bytecode": _BYTECODE,
}
STAMPED_AT = datetime(2026, 1, 1, tzinfo=UTC)


@override_settings(REALTIME_COHORT_TEAM_ALLOWLIST="none", COHORT_BACKFILL_TRIGGER_TEAM_ALLOWLIST="none")
class TestCohortEnablement(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        RealtimeCohortTeamAccess.objects.create(
            team=self.team,
            level=RealtimeCohortLevel.SERVING,
            purpose=RealtimeCohortAccessPurpose.BETA,
            save_triggers_backfill=True,
        )

    def _set_flag_evaluations_mode(self, mode: FlagEvaluationsMode) -> None:
        OrganizationFeatureFlagsConfig.objects.update_or_create(
            organization=self.organization, defaults={"flag_evaluations_mode": mode}
        )

    def _cohort(self, *leaves: dict, **kwargs) -> Cohort:
        return Cohort.objects.create(
            team=self.team,
            filters={"properties": {"type": "AND", "values": list(leaves)}},
            **{"cohort_type": CohortType.REALTIME, **kwargs},
        )

    def test_turning_on_a_flag_call_cohort_in_flag_evaluations_only_mode(self) -> None:
        self._set_flag_evaluations_mode(FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY)
        cohort = self._cohort(FLAG_CALL_LEAF)

        with mock.patch("posthog.tasks.calculate_cohort.trigger_cohort_backfill_run_task.apply_async"):
            turned_on = turn_realtime_on(self.team.id, cohort.id, can_edit=lambda _: True)

        assert turned_on == [cohort.id]

    def test_turning_on_a_cohort_turns_on_what_it_nests_and_queues_both_builds(self) -> None:
        nested = self._cohort(PAGEVIEW_LEAF)
        cohort = self._cohort(PERSON_LEAF, PAGEVIEW_LEAF, {"type": "cohort", "key": "id", "value": nested.id})
        Cohort.objects.filter(id=cohort.id).update(last_backfill_events_at=STAMPED_AT)

        with (
            mock.patch("posthog.tasks.calculate_cohort.trigger_cohort_backfill_run_task.apply_async"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            turned_on = turn_realtime_on(self.team.id, cohort.id, can_edit=lambda _: True)

        cohorts = list(Cohort.objects.filter(id__in=[nested.id, cohort.id]).order_by("id"))
        assert sorted(turned_on) == [nested.id, cohort.id]
        assert all(each.realtime_enabled for each in cohorts)
        assert cohorts[1].last_backfill_events_at is None
        readiness = resolve_realtime_readiness(cohorts)
        assert [readiness[each.id].state for each in cohorts] == [CohortRealtimeState.BUILDING] * 2

    @parameterized.expand(
        [
            ("daily", {"cohort_type": None}, None),
            ("nested_leaf_the_catalog_drops", {}, {**PAGEVIEW_LEAF, "conditionHash": None}),
            ("team_not_processed", {}, None),
            # cohort-seeder reads these flag calls only from flag_evaluations, which keeps no 120-day-old calls.
            ("nested_flag_calls_past_the_ttl", {}, {**FLAG_CALL_LEAF, "time_value": 120}),
        ]
    )
    def test_turn_on_is_refused_before_anything_is_written(
        self, name: str, cohort_kwargs: dict, nested_leaf: dict | None
    ) -> None:
        leaves: list[dict] = [PERSON_LEAF]
        if nested_leaf is not None:
            leaves.append({"type": "cohort", "key": "id", "value": self._cohort(nested_leaf).id})
        cohort = self._cohort(*leaves, **cohort_kwargs)
        if name == "team_not_processed":
            RealtimeCohortTeamAccess.objects.filter(team=self.team).update(level=RealtimeCohortLevel.OFF)
        if name == "nested_flag_calls_past_the_ttl":
            self._set_flag_evaluations_mode(FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY)

        with self.assertRaises(RealtimeTurnOnRefused):
            turn_realtime_on(self.team.id, cohort.id, can_edit=lambda _: True)

        assert not Cohort.objects.filter(team=self.team, realtime_enabled_at__isnull=False).exists()

    @override_settings(FLAGS_REDIS_URL="redis://localhost:6379/0")
    def test_turning_off_clears_the_stamps_supersedes_the_build_and_rebuilds_the_flags_cache(self) -> None:
        cohort = self._cohort(PAGEVIEW_LEAF, realtime_enabled_at=STAMPED_AT, last_backfill_events_at=STAMPED_AT)
        run = CohortBackfillRun.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            cohort=cohort,
            backfill_kind=CohortBackfillKind.BEHAVIORAL,
            trigger_kind=CohortBackfillTrigger.COHORT_EDITED,
            scope=CohortBackfillScope.COHORT,
            status=CohortBackfillRunStatus.SEEDING,
            timezone="UTC",
        )
        participation = CohortBackfillRunCohort.objects.for_team(self.team.id).create(
            run=run, team_id=self.team.id, cohort=cohort, filters_shape_hash="shape", pinned_filters=cohort.filters
        )

        with (
            mock.patch("products.feature_flags.backend.tasks.update_team_service_flags_cache.delay") as rebuild,
            self.captureOnCommitCallbacks(execute=True),
        ):
            assert turn_realtime_off(self.team.id, cohort.id)

        cohort.refresh_from_db()
        participation.refresh_from_db()
        assert (cohort.realtime_enabled_at, cohort.last_backfill_events_at) == (None, None)
        assert participation.superseded_at is not None
        rebuild.assert_called_once_with(self.team.id)
