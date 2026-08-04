from posthog.test.base import BaseTest

from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized

from products.cohorts.backend.backfill.readiness import (
    ensure_filters_shape_hash,
    stamp_events_readiness,
    stamp_person_properties_readiness,
)
from products.cohorts.backend.backfill.runs import create_backfill_run_for_cohort, create_person_backfill_run_for_cohort
from products.cohorts.backend.models.backfill import CohortBackfillRunCohort, CohortBackfillRunStatus
from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.cohorts.backend.models.leaf_shape import extract_leaf_shape_hash, extract_person_leaf_shape_hash

# (name, run factory, stamp fn, cohort hash column, cohort stamp column, same-kind edit,
# other-kind edit) — the stamp protocol is symmetric in these, so every step of it runs under both
# kinds. The two edits are the filters that move only this kind's hash, and only the other's.
KINDS = [
    (
        "events",
        create_backfill_run_for_cohort,
        stamp_events_readiness,
        "behavioral_filters_shape_hash",
        "last_backfill_events_at",
        (30, "person-a"),
        (7, "person-b"),
    ),
    (
        "person_properties",
        create_person_backfill_run_for_cohort,
        stamp_person_properties_readiness,
        "person_filters_shape_hash",
        "last_backfill_person_properties_at",
        (7, "person-b"),
        (30, "person-a"),
    ),
]


@override_settings(
    REALTIME_COHORT_TEAM_ALLOWLIST="all",
    BEHAVIORAL_BACKFILL_MERGE_GATE_ATTESTED=True,
    BEHAVIORAL_BACKFILL_DURABILITY_ATTESTED=True,
    BEHAVIORAL_BACKFILL_PERSON_TTL_ATTESTED=True,
    BEHAVIORAL_BACKFILL_PERSON_SIZING_ATTESTED=True,
    BEHAVIORAL_BACKFILL_PERSON_TOPIC_BYTES_BUDGET=1_000_000,
)
class TestBackfillReadiness(BaseTest):
    def _filters(self, window_days: int, *, person_hash: str | None = None) -> dict:
        values: list[dict] = [
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
        ]
        if person_hash is not None:
            values.append(
                {
                    "type": "person",
                    "key": "email",
                    "value": ["person@example.com"],
                    "operator": "exact",
                    "conditionHash": person_hash,
                }
            )
        return {"properties": {"type": "AND", "values": values}}

    def _cohort_and_run(self, make_run=create_backfill_run_for_cohort):
        cohort = Cohort.objects.create(
            team=self.team,
            cohort_type=CohortType.REALTIME,
            filters=self._filters(7, person_hash="person-a"),
        )
        run = make_run(self.team.id, cohort.id, "cohort_created")
        assert run is not None
        return cohort, run

    @parameterized.expand(KINDS)
    def test_stamp_uses_one_conditional_cohort_update(
        self, _name: str, make_run, stamp, hash_column: str, stamp_column: str, *_edits
    ) -> None:
        cohort, run = self._cohort_and_run(make_run)

        with CaptureQueriesContext(connection) as queries:
            self.assertTrue(stamp(run, cohort.id))

        cohort.refresh_from_db()
        participation = CohortBackfillRunCohort.objects.for_team(self.team.id).get(run=run)
        self.assertIsNotNone(getattr(cohort, stamp_column))
        self.assertIsNotNone(participation.stamped_at)
        cohort_updates = [query["sql"] for query in queries if query["sql"].startswith('UPDATE "posthog_cohort"')]
        self.assertEqual(len(cohort_updates), 1)
        self.assertIn(f'"{hash_column}"', cohort_updates[0])
        self.assertIn(f'"{stamp_column}" IS NULL', cohort_updates[0])

    @parameterized.expand(KINDS)
    def test_edit_of_the_stamped_kind_fails_cas(
        self, _name: str, make_run, stamp, _hash: str, stamp_column: str, same_kind_edit, _other
    ) -> None:
        cohort, run = self._cohort_and_run(make_run)
        # Shift the leaves of the kind under test, leaving the other kind's hash alone.
        cohort.filters = self._filters(same_kind_edit[0], person_hash=same_kind_edit[1])
        cohort.save(update_fields=["filters"])

        self.assertFalse(stamp(run, cohort.id))

        cohort.refresh_from_db()
        run.refresh_from_db()
        self.assertIsNone(getattr(cohort, stamp_column))
        self.assertEqual(run.status, CohortBackfillRunStatus.SUPERSEDED)

    @parameterized.expand(KINDS)
    def test_edit_of_the_other_kind_still_stamps_readiness(
        self, _name: str, make_run, stamp, _hash: str, stamp_column: str, _same, other_kind_edit
    ) -> None:
        # An edit shifts the full filters hash but only nulls the readiness of the kind it touched.
        # The other kind's backfill is still valid, so its stamp must succeed rather than supersede
        # the run (the sibling test above correctly supersedes on a same-kind edit).
        cohort, run = self._cohort_and_run(make_run)
        old_full_hash = cohort.filters_shape_hash
        cohort.filters = self._filters(other_kind_edit[0], person_hash=other_kind_edit[1])
        cohort.save(update_fields=["filters"])
        cohort.refresh_from_db()
        self.assertNotEqual(cohort.filters_shape_hash, old_full_hash)

        self.assertTrue(stamp(run, cohort.id))

        cohort.refresh_from_db()
        run.refresh_from_db()
        participation = CohortBackfillRunCohort.objects.for_team(self.team.id).get(run=run)
        self.assertIsNotNone(getattr(cohort, stamp_column))
        self.assertIsNotNone(participation.stamped_at)
        self.assertIsNone(participation.superseded_at)
        self.assertEqual(run.status, CohortBackfillRunStatus.AWAITING_BOUNDARY)

    @parameterized.expand(KINDS)
    def test_already_stamped_readiness_is_not_overwritten(
        self, _name: str, make_run, stamp, _hash: str, stamp_column: str, *_edits
    ) -> None:
        # The only path that reads the spec's columns back as a projection, so a transposed
        # `values_list` would surface here and nowhere else.
        cohort, run = self._cohort_and_run(make_run)
        first_stamp = timezone.now()
        Cohort.objects.filter(id=cohort.id).update(**{stamp_column: first_stamp})

        self.assertTrue(stamp(run, cohort.id))

        cohort.refresh_from_db()
        run.refresh_from_db()
        participation = CohortBackfillRunCohort.objects.for_team(self.team.id).get(run=run)
        self.assertEqual(getattr(cohort, stamp_column), first_stamp)
        self.assertIsNotNone(participation.stamped_at)
        self.assertEqual(run.status, CohortBackfillRunStatus.AWAITING_BOUNDARY)

    def test_superseded_participation_is_never_resurrected(self) -> None:
        cohort, run = self._cohort_and_run()
        participation = CohortBackfillRunCohort.objects.for_team(self.team.id).get(run=run)
        CohortBackfillRunCohort.objects.for_team(self.team.id).filter(id=participation.id).update(
            superseded_at=timezone.now()
        )

        # A -> B -> A: edit the behavioral window away and back so the cohort's current hash matches
        # the pinned one again. The up-front guard must still refuse the terminal participation.
        cohort.filters = self._filters(30, person_hash="person-a")
        cohort.save(update_fields=["filters"])
        cohort.filters = self._filters(7, person_hash="person-a")
        cohort.save(update_fields=["filters"])
        cohort.refresh_from_db()
        participation.refresh_from_db()
        self.assertEqual(cohort.behavioral_filters_shape_hash, participation.behavioral_filters_shape_hash)

        self.assertFalse(stamp_events_readiness(run, cohort.id))

        cohort.refresh_from_db()
        participation.refresh_from_db()
        self.assertIsNone(cohort.last_backfill_events_at)
        self.assertIsNone(participation.stamped_at)

    def test_person_edit_revert_is_fenced_by_the_receiver(self) -> None:
        # A -> B -> A restores the pinned person hash, so the stamp's CAS passes again. Only the
        # `superseded_at` that `cohort_person_shape_changed_supersede` set on the first edit keeps
        # readiness off a backfill whose seeded state went stale during the B window.
        cohort, run = self._cohort_and_run(create_person_backfill_run_for_cohort)

        with self.captureOnCommitCallbacks(execute=True):
            cohort.filters = self._filters(7, person_hash="person-b")
            cohort.save(update_fields=["filters"])
            cohort.filters = self._filters(7, person_hash="person-a")
            cohort.save(update_fields=["filters"])

        cohort.refresh_from_db()
        participation = CohortBackfillRunCohort.objects.for_team(self.team.id).get(run=run)
        self.assertEqual(cohort.person_filters_shape_hash, participation.person_filters_shape_hash)

        self.assertFalse(stamp_person_properties_readiness(run, cohort.id))

        cohort.refresh_from_db()
        self.assertIsNone(cohort.last_backfill_person_properties_at)

    @parameterized.expand(KINDS)
    def test_supersession_racing_the_stamp_rolls_the_cohort_back(
        self, _name: str, make_run, stamp, _hash: str, stamp_column: str, *_edits
    ) -> None:
        cohort, run = self._cohort_and_run(make_run)
        participation = CohortBackfillRunCohort.objects.for_team(self.team.id).get(run=run)
        superseded: list[bool] = []

        def supersede_after_the_cohort_stamp(execute, sql, params, many, context):
            result = execute(sql, params, many, context)
            if not superseded and sql.startswith('UPDATE "posthog_cohort" '):
                superseded.append(True)
                CohortBackfillRunCohort.objects.for_team(self.team.id).filter(id=participation.id).update(
                    superseded_at=timezone.now()
                )
            return result

        # A supersession commits after the cohort stamp but before the participation CAS ratifies
        # it. The stamp is this transaction's own write, so it has to be taken back.
        with connection.execute_wrapper(supersede_after_the_cohort_stamp):
            self.assertFalse(stamp(run, cohort.id))

        cohort.refresh_from_db()
        participation.refresh_from_db()
        self.assertIsNone(getattr(cohort, stamp_column))
        self.assertIsNone(participation.stamped_at)
        # The rollback must leave the participation terminal — the finalizer reads superseded_at to
        # decide the run's outcome, so clearing it here would make the run reconcile forever.
        self.assertIsNotNone(participation.superseded_at)

    def test_ensure_shape_hash_only_fills_null_column(self) -> None:
        cohort, _ = self._cohort_and_run()
        Cohort.objects.filter(id=cohort.id).update(
            filters_shape_hash=None,
            behavioral_filters_shape_hash=None,
            person_filters_shape_hash=None,
        )
        cohort.filters_shape_hash = None
        cohort.behavioral_filters_shape_hash = None
        cohort.person_filters_shape_hash = None

        self.assertEqual(ensure_filters_shape_hash(cohort), extract_leaf_shape_hash(cohort.filters))
        self.assertIsNotNone(cohort.behavioral_filters_shape_hash)
        self.assertEqual(
            cohort.person_filters_shape_hash,
            extract_person_leaf_shape_hash(cohort.filters),
        )

        Cohort.objects.filter(id=cohort.id).update(
            filters_shape_hash="persisted",
            person_filters_shape_hash="persisted-person",
        )
        cohort.filters_shape_hash = None
        cohort.person_filters_shape_hash = None
        self.assertEqual(ensure_filters_shape_hash(cohort), "persisted")
        self.assertEqual(cohort.person_filters_shape_hash, "persisted-person")
