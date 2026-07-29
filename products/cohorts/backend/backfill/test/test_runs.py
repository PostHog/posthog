from posthog.test.base import BaseTest
from unittest import mock

from django.test import override_settings

from posthog.tasks.calculate_cohort import trigger_cohort_events_backfill_task

from products.cohorts.backend.backfill.runs import (
    create_backfill_run_for_cohort,
    create_team_backfill_run,
    supersede_active_runs,
)
from products.cohorts.backend.models.backfill import (
    CohortBackfillChunk,
    CohortBackfillRun,
    CohortBackfillRunCohort,
    CohortBackfillRunStatus,
    CohortBackfillScope,
)
from products.cohorts.backend.models.cohort import Cohort, CohortType


@override_settings(
    REALTIME_COHORT_TEAM_ALLOWLIST="all",
    BEHAVIORAL_BACKFILL_MERGE_GATE_ATTESTED=True,
    BEHAVIORAL_BACKFILL_DURABILITY_ATTESTED=True,
)
class TestBackfillRuns(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        feature_patch = mock.patch(
            "products.cohorts.backend.models.dependencies.posthoganalytics.feature_enabled", return_value=False
        )
        feature_patch.start()
        self.addCleanup(feature_patch.stop)

    def _filters(self, event: str = "$pageview", window_days: int = 7) -> dict:
        return {
            "properties": {
                "type": "AND",
                "values": [
                    {
                        "type": "behavioral",
                        "key": event,
                        "event_type": "events",
                        "value": "performed_event_multiple",
                        "conditionHash": f"hash-{event}",
                        "time_value": window_days,
                        "time_interval": "day",
                        "operator": "gte",
                        "operator_value": 2,
                    }
                ],
            }
        }

    def _cohort(self, event: str = "$pageview") -> Cohort:
        return Cohort.objects.create(
            team=self.team,
            name=event,
            cohort_type=CohortType.REALTIME,
            filters=self._filters(event),
        )

    def test_cohort_run_pins_definition_timezone_and_preconditions(self) -> None:
        cohort = self._cohort()

        run = create_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_created")

        assert run is not None
        participation = CohortBackfillRunCohort.objects.for_team(self.team.id).get(run=run)
        self.assertEqual(run.status, CohortBackfillRunStatus.AWAITING_BOUNDARY)
        self.assertEqual(run.scope, CohortBackfillScope.COHORT)
        self.assertEqual(run.timezone, self.team.timezone)
        self.assertEqual(run.pinned["event_names"], ["$pageview"])
        self.assertEqual(run.preconditions["catalog_consume_floor"], "not_implemented_b8")
        self.assertEqual(participation.filters_shape_hash, cohort.filters_shape_hash)
        self.assertEqual(participation.pinned_filters, cohort.filters)
        self.assertEqual(CohortBackfillChunk.objects.for_team(self.team.id).filter(run=run).count(), 0)

    @override_settings(BEHAVIORAL_BACKFILL_MERGE_GATE_ATTESTED=False)
    def test_signal_path_records_blocked_run_when_attestation_is_missing(self) -> None:
        cohort = self._cohort()

        run = create_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_created")

        assert run is not None
        self.assertEqual(run.status, CohortBackfillRunStatus.BLOCKED)
        self.assertIn("merge gate", run.blocked_reason)

    def test_task_revalidates_fresh_cohort_state(self) -> None:
        cohort = self._cohort()
        Cohort.objects.filter(id=cohort.id).update(deleted=True)

        self.assertIsNone(create_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_edited"))
        self.assertEqual(CohortBackfillRun.objects.for_team(self.team.id).count(), 0)

    def test_team_run_pins_sorted_union_and_join_rows(self) -> None:
        second = self._cohort("signup")
        first = self._cohort("$pageview")

        run = create_team_backfill_run(self.team.id, "team_enablement")

        self.assertEqual(run.scope, CohortBackfillScope.TEAM)
        self.assertEqual(run.pinned["event_names"], ["$pageview", "signup"])
        self.assertEqual(
            set(
                CohortBackfillRunCohort.objects.for_team(self.team.id)
                .filter(run=run)
                .values_list("cohort_id", flat=True)
            ),
            {first.id, second.id},
        )

    def test_supersession_marks_cohort_run_and_participation(self) -> None:
        cohort = self._cohort()
        run = create_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_created")
        assert run is not None

        self.assertEqual(supersede_active_runs(self.team.id, [cohort.id]), 1)

        run.refresh_from_db()
        participation = CohortBackfillRunCohort.objects.for_team(self.team.id).get(run=run)
        self.assertEqual(run.status, CohortBackfillRunStatus.SUPERSEDED)
        self.assertIsNotNone(participation.superseded_at)

    def test_second_active_cohort_run_is_a_benign_noop(self) -> None:
        cohort = self._cohort()
        self.assertIsNotNone(create_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_created"))

        self.assertIsNone(create_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_edited"))
        self.assertEqual(CohortBackfillRun.objects.for_team(self.team.id).count(), 1)

    def test_active_team_run_prevents_overlapping_cohort_run(self) -> None:
        cohort = self._cohort()
        create_team_backfill_run(self.team.id, "team_enablement")

        self.assertIsNone(create_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_edited"))
        self.assertEqual(CohortBackfillRun.objects.for_team(self.team.id).count(), 1)

    def test_active_cohort_run_prevents_overlapping_team_run(self) -> None:
        cohort = self._cohort()
        self.assertIsNotNone(create_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_created"))

        with self.assertRaisesMessage(ValueError, "Cohorts already have active backfill runs"):
            create_team_backfill_run(self.team.id, "team_enablement")

    def test_celery_task_uses_explicit_team_scope(self) -> None:
        cohort = self._cohort()

        trigger_cohort_events_backfill_task.run(self.team.id, cohort.id, "cohort_created")

        self.assertEqual(CohortBackfillRun.objects.for_team(self.team.id).filter(cohort=cohort).count(), 1)
