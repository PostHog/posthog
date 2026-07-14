from posthog.test.base import BaseTest
from unittest import mock

from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from products.cohorts.backend.backfill.readiness import ensure_filters_shape_hash, stamp_events_readiness
from products.cohorts.backend.backfill.runs import create_backfill_run_for_cohort
from products.cohorts.backend.models.backfill import CohortBackfillRunCohort, CohortBackfillRunStatus
from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.cohorts.backend.models.leaf_shape import extract_leaf_shape_hash


@override_settings(
    REALTIME_COHORT_TEAM_ALLOWLIST="all",
    BEHAVIORAL_BACKFILL_MERGE_GATE_ATTESTED=True,
    BEHAVIORAL_BACKFILL_DURABILITY_ATTESTED=True,
)
class TestBackfillReadiness(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        feature_patch = mock.patch(
            "products.cohorts.backend.models.dependencies.posthoganalytics.feature_enabled", return_value=False
        )
        feature_patch.start()
        self.addCleanup(feature_patch.stop)

    def _filters(self, window_days: int) -> dict:
        return {
            "properties": {
                "type": "AND",
                "values": [
                    {
                        "type": "behavioral",
                        "key": "$pageview",
                        "event_type": "events",
                        "value": "performed_event_multiple",
                        "conditionHash": "same-condition-hash",
                        "time_value": window_days,
                        "time_interval": "day",
                        "operator": "gte",
                        "operator_value": 2,
                    }
                ],
            }
        }

    def _cohort_and_run(self):
        cohort = Cohort.objects.create(
            team=self.team,
            cohort_type=CohortType.REALTIME,
            filters=self._filters(7),
        )
        run = create_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_created")
        assert run is not None
        return cohort, run

    def test_stamp_uses_one_conditional_cohort_update(self) -> None:
        cohort, run = self._cohort_and_run()

        with CaptureQueriesContext(connection) as queries:
            self.assertTrue(stamp_events_readiness(run, cohort.id))

        cohort.refresh_from_db()
        participation = CohortBackfillRunCohort.objects.for_team(self.team.id).get(run=run)
        self.assertIsNotNone(cohort.last_backfill_events_at)
        self.assertIsNotNone(participation.stamped_at)
        cohort_updates = [query["sql"] for query in queries if query["sql"].startswith('UPDATE "posthog_cohort"')]
        self.assertEqual(len(cohort_updates), 1)
        self.assertIn('"filters_shape_hash"', cohort_updates[0])
        self.assertIn('"last_backfill_events_at" IS NULL', cohort_updates[0])

    def test_edit_between_completion_and_stamp_fails_cas(self) -> None:
        cohort, run = self._cohort_and_run()
        cohort.filters = self._filters(30)
        cohort.save(update_fields=["filters"])

        self.assertFalse(stamp_events_readiness(run, cohort.id))

        cohort.refresh_from_db()
        run.refresh_from_db()
        self.assertIsNone(cohort.last_backfill_events_at)
        self.assertEqual(run.status, CohortBackfillRunStatus.SUPERSEDED)

    def test_already_stamped_readiness_is_not_overwritten(self) -> None:
        cohort, run = self._cohort_and_run()
        first_stamp = timezone.now()
        Cohort.objects.filter(id=cohort.id).update(last_backfill_events_at=first_stamp)

        self.assertFalse(stamp_events_readiness(run, cohort.id))

        cohort.refresh_from_db()
        self.assertEqual(cohort.last_backfill_events_at, first_stamp)

    def test_ensure_shape_hash_only_fills_null_column(self) -> None:
        cohort, _ = self._cohort_and_run()
        Cohort.objects.filter(id=cohort.id).update(filters_shape_hash=None)
        cohort.filters_shape_hash = None

        self.assertEqual(ensure_filters_shape_hash(cohort), extract_leaf_shape_hash(cohort.filters))

        Cohort.objects.filter(id=cohort.id).update(filters_shape_hash="persisted")
        cohort.filters_shape_hash = None
        self.assertEqual(ensure_filters_shape_hash(cohort), "persisted")
