from datetime import UTC, datetime

from posthog.test.base import BaseTest
from unittest import mock

from django.test import override_settings

from parameterized import parameterized

from products.cohorts.backend.cohort_enablement import (
    RealtimeLimitReached,
    RealtimeTurnOnRefused,
    turn_realtime_off,
    turn_realtime_on,
)
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

    def _cohort(self, *leaves: dict, **kwargs) -> Cohort:
        return Cohort.objects.create(
            team=self.team,
            filters={"properties": {"type": "AND", "values": list(leaves)}},
            **{"cohort_type": CohortType.REALTIME, **kwargs},
        )

    def _plan(self, features: list[dict] | None) -> None:
        self.organization.available_product_features = [
            {"name": feature["key"], **feature} for feature in features or []
        ]
        self.organization.save()

    def _turn_on(self, cohort: Cohort) -> list[int]:
        with mock.patch("posthog.tasks.calculate_cohort.trigger_cohort_backfill_run_task.apply_async"):
            return turn_realtime_on(self.team.id, cohort.id, can_edit=lambda _: True)

    def test_turning_on_a_cohort_turns_on_what_it_nests_and_queues_both_builds(self) -> None:
        nested = self._cohort(PAGEVIEW_LEAF)
        already_on = self._cohort(PAGEVIEW_LEAF)
        cohort = self._cohort(
            PERSON_LEAF,
            PAGEVIEW_LEAF,
            {"type": "cohort", "key": "id", "value": nested.id},
            {"type": "cohort", "key": "id", "value": already_on.id},
        )
        Cohort.objects.filter(id=cohort.id).update(last_backfill_events_at=STAMPED_AT)
        Cohort.objects.filter(id=already_on.id).update(
            realtime_enabled_at=STAMPED_AT, last_backfill_events_at=STAMPED_AT
        )

        with (
            mock.patch("posthog.tasks.calculate_cohort.trigger_cohort_backfill_run_task.apply_async"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            turned_on = turn_realtime_on(self.team.id, cohort.id, can_edit=lambda _: True)

        cohorts = list(Cohort.objects.filter(id__in=[nested.id, cohort.id]).order_by("id"))
        already_on.refresh_from_db()
        assert sorted(turned_on) == [nested.id, cohort.id]
        assert all(each.realtime_enabled for each in cohorts)
        assert cohorts[1].last_backfill_events_at is None
        assert (already_on.realtime_enabled_at, already_on.last_backfill_events_at) == (STAMPED_AT, STAMPED_AT)
        readiness = resolve_realtime_readiness(cohorts)
        assert [readiness[each.id].state for each in cohorts] == [CohortRealtimeState.BUILDING] * 2

    @parameterized.expand(
        [
            ("daily", {"cohort_type": None}, None),
            ("nested_leaf_the_catalog_drops", {}, {**PAGEVIEW_LEAF, "conditionHash": None}),
            ("team_not_processed", {}, None),
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

        with self.assertRaises(RealtimeTurnOnRefused):
            turn_realtime_on(self.team.id, cohort.id, can_edit=lambda _: True)

        assert not Cohort.objects.filter(team=self.team, realtime_enabled_at__isnull=False).exists()

    @parameterized.expand(
        [
            ("free_plan_at_its_limit", None, 10, 0, ("cohorts", 10, 10)),
            ("free_plan_below_its_limit", None, 9, 0, 1),
            (
                "an_included_cohort_needs_a_slot_too",
                [{"key": "realtime_cohorts", "limit": 12}],
                10,
                2,
                ("cohorts", 12, 10),
            ),
            ("room_for_it_and_what_it_includes", [{"key": "realtime_cohorts", "limit": 13}], 10, 2, 3),
            ("no_limit", [{"key": "realtime_cohorts", "limit": None}], 10, 2, 3),
        ]
    )
    def test_a_turn_on_needs_a_slot_for_each_cohort_it_turns_on(
        self, _name: str, features: list[dict] | None, already_on: int, included_off: int, expected: tuple | int
    ) -> None:
        self._plan(features)
        for _ in range(already_on):
            self._cohort(PAGEVIEW_LEAF, realtime_enabled_at=STAMPED_AT)
        included = [
            {"type": "cohort", "key": "id", "value": self._cohort(PAGEVIEW_LEAF).id} for _ in range(included_off)
        ]
        cohort = self._cohort(PAGEVIEW_LEAF, *included)

        try:
            outcome: tuple | int = len(self._turn_on(cohort))
        except RealtimeLimitReached as error:
            outcome = (error.limit, error.allowed, error.used)

        assert outcome == expected
        if isinstance(expected, tuple):
            assert Cohort.objects.filter(team=self.team, realtime_enabled_at__isnull=False).count() == already_on

    @parameterized.expand(
        [("deleted", {"deleted": True}), ("static", {"is_static": True}), ("daily", {"cohort_type": None})]
    )
    def test_a_cohort_the_pipeline_does_not_load_holds_no_slot(self, _name: str, kwargs: dict) -> None:
        for _ in range(9):
            self._cohort(PAGEVIEW_LEAF, realtime_enabled_at=STAMPED_AT)
        self._cohort(PAGEVIEW_LEAF, realtime_enabled_at=STAMPED_AT, **kwargs)

        assert len(self._turn_on(self._cohort(PAGEVIEW_LEAF))) == 1

    @parameterized.expand(
        [
            ("free_plan", None, 31, ("history_days", 30)),
            ("free_plan_at_its_limit", None, 30, None),
            ("paid_plan", [{"key": "realtime_cohorts_history", "limit": 365}], 365, None),
            ("past_the_paid_plan", [{"key": "realtime_cohorts_history", "limit": 365}], 366, ("history_days", 365)),
            ("no_limit_up_to_the_pipeline_cap", [{"key": "realtime_cohorts_history", "limit": None}], 400, None),
            (
                "plan_above_the_pipeline_cap",
                [{"key": "realtime_cohorts_history", "limit": 500}],
                401,
                ("history_days", 400),
            ),
            (
                "no_limit_past_the_pipeline_cap",
                [{"key": "realtime_cohorts_history", "limit": None}],
                401,
                ("history_days", 400),
            ),
        ]
    )
    def test_a_turn_on_is_refused_when_the_criteria_look_back_further_than_the_plan_allows(
        self, _name: str, features: list[dict] | None, days: int, refusal: tuple[str, int] | None
    ) -> None:
        self._plan(features)
        nested = self._cohort({**PAGEVIEW_LEAF, "time_value": days})
        cohort = self._cohort(PERSON_LEAF, {"type": "cohort", "key": "id", "value": nested.id})

        try:
            self._turn_on(cohort)
            outcome = None
        except RealtimeLimitReached as error:
            outcome = (error.limit, error.allowed)

        assert outcome == refusal
        assert Cohort.objects.filter(team=self.team, realtime_enabled_at__isnull=False).count() == (0 if refusal else 2)

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
