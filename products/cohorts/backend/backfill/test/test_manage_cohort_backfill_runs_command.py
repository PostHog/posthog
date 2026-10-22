import io
import re
import json
from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.tasks.calculate_cohort import finalize_cohort_backfill_runs  # noqa: F401  breaks an import cycle

from products.cohorts.backend.backfill.audit import RealtimeMembershipReader
from products.cohorts.backend.backfill.finalize import FLAGS_CACHE_TASK, finalize_backfill_runs
from products.cohorts.backend.backfill.readiness import ensure_filters_shape_hash
from products.cohorts.backend.backfill.sizing import PersonSeedEstimate
from products.cohorts.backend.models.backfill import (
    CohortBackfillKind,
    CohortBackfillRun,
    CohortBackfillRunCohort,
    CohortBackfillRunStatus,
    CohortBackfillScope,
    CohortBackfillTrigger,
)
from products.cohorts.backend.models.cohort import Cohort, CohortType

_BYTECODE = ["_H", 1, 32, "matched", 32, "event", 1, 1, 11]
_BEHAVIORAL_LEAF = {
    "type": "behavioral",
    "key": "$pageview",
    "event_type": "events",
    "value": "performed_event",
    "conditionHash": "behavior00000001",
    "time_value": 7,
    "time_interval": "day",
    "bytecode": _BYTECODE,
}
_PERSON_LEAF = {
    "type": "person",
    "key": "email",
    "value": ["person@example.com"],
    "operator": "exact",
    "conditionHash": "person0000000001",
    "bytecode": _BYTECODE,
}
_ALL_STAMPS = ("last_backfill_events_at", "last_backfill_person_properties_at", "last_realtime_cohort_calculation_at")


@override_settings(
    REALTIME_COHORT_TEAM_ALLOWLIST="all",
    BEHAVIORAL_BACKFILL_FINALIZER_ENABLED=True,
    BEHAVIORAL_BACKFILL_PERSON_READINESS_ENABLED=True,
    BEHAVIORAL_BACKFILL_FINALIZER_RUN_ALLOWLIST="all",
)
class TestManageCohortBackfillRuns(BaseTest):
    def _cohort(self, name: str) -> Cohort:
        cohort = Cohort.objects.create(
            team=self.team,
            name=name,
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "event_type": "events",
                            "value": "performed_event_multiple",
                            "conditionHash": f"hash-{name}",
                            "time_value": 7,
                            "time_interval": "day",
                            "operator": "gte",
                            "operator_value": 2,
                        }
                    ],
                }
            },
        )
        ensure_filters_shape_hash(cohort)
        cohort.refresh_from_db()
        return cohort

    def _run(self, name: str, *, status: str, observed: bool = False) -> CohortBackfillRun:
        cohort = self._cohort(name)
        run = CohortBackfillRun.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            trigger_kind=CohortBackfillTrigger.TEAM_ENABLEMENT,
            scope=CohortBackfillScope.COHORT,
            cohort=cohort,
            status=status,
            reconcile_observed_at=timezone.now() if observed else None,
            timezone="UTC",
        )
        CohortBackfillRunCohort.objects.for_team(self.team.id).create(
            run=run,
            team_id=self.team.id,
            cohort=cohort,
            filters_shape_hash=cohort.filters_shape_hash or "",
            behavioral_filters_shape_hash=cohort.behavioral_filters_shape_hash or "",
            person_filters_shape_hash=cohort.person_filters_shape_hash or "",
            pinned_filters=cohort.filters,
            reconcile_completed_at=timezone.now() if observed else None,
        )
        return run

    def _call(self, *args: str) -> str:
        out = io.StringIO()
        call_command("manage_cohort_backfill_runs", *args, stdout=out, stderr=out)
        return out.getvalue()

    def test_inventory_allowlist_line_round_trips_through_the_finalizer(self) -> None:
        stampable = self._run("stampable", status=CohortBackfillRunStatus.RECONCILING, observed=True)
        unobserved = self._run("unobserved", status=CohortBackfillRunStatus.RECONCILING, observed=False)

        output = self._call("inventory")
        [line] = re.findall(r"^BEHAVIORAL_BACKFILL_FINALIZER_RUN_ALLOWLIST=(.*)$", output, re.MULTILINE)

        # Feed the emitted value back through the parser rather than eyeballing it: a line with a
        # stray space, a trailing comma, or an empty value silently reads as "every run", which is
        # the worst possible outcome of a change whose stamps cannot be undone.
        with override_settings(BEHAVIORAL_BACKFILL_FINALIZER_RUN_ALLOWLIST=line):
            finalize_backfill_runs()

        stampable.refresh_from_db()
        unobserved.refresh_from_db()
        self.assertEqual(stampable.status, CohortBackfillRunStatus.COMPLETED)
        self.assertEqual(unobserved.status, CohortBackfillRunStatus.RECONCILING)

    def test_inventory_json_output_is_one_parseable_document(self) -> None:
        self._run("seeding", status=CohortBackfillRunStatus.SEEDING)

        payload = json.loads(self._call("inventory", "--format", "json"))

        # Heading text leaking into the stream would break the machine-readable path the runbook
        # depends on for recording the verified list.
        self.assertEqual(len(payload["runs"]), 1)
        self.assertEqual(payload["summary"]["seeding-healthy"], 1)

    def test_terminalize_dry_run_writes_nothing(self) -> None:
        run = self._run("orphan", status=CohortBackfillRunStatus.SEEDING)
        CohortBackfillRunCohort.objects.for_team(self.team.id).filter(run_id=run.id).update(
            superseded_at=timezone.now()
        )

        output = self._call("terminalize", "--classification", "orphaned")

        run.refresh_from_db()
        self.assertIn("Dry run", output)
        self.assertEqual(run.status, CohortBackfillRunStatus.SEEDING)

        self._call("terminalize", "--classification", "orphaned", "--live-run", "--yes")

        run.refresh_from_db()
        self.assertEqual(run.status, CohortBackfillRunStatus.CANCELLED)

    def test_terminalize_needs_a_target(self) -> None:
        # There is no cancel-everything-active mode, and a default that swept the whole active set
        # would be irreversible for every team at once.
        with self.assertRaisesMessage(CommandError, "--classification or --run-id"):
            self._call("terminalize", "--live-run", "--yes")

    def test_terminalize_aborts_over_the_max_runs_cap_without_writing(self) -> None:
        runs = [self._run(f"orphan-{index}", status=CohortBackfillRunStatus.SEEDING) for index in range(3)]
        CohortBackfillRunCohort.objects.for_team(self.team.id).filter(run_id__in=[run.id for run in runs]).update(
            superseded_at=timezone.now()
        )

        with self.assertRaisesMessage(CommandError, "over the --max-runs cap"):
            self._call("terminalize", "--classification", "orphaned", "--max-runs", "2", "--live-run", "--yes")

        for run in runs:
            run.refresh_from_db()
            self.assertEqual(run.status, CohortBackfillRunStatus.SEEDING)

    @parameterized.expand(
        [
            ("awaiting_observation", CohortBackfillRunStatus.RECONCILING),
            ("seeding_healthy", CohortBackfillRunStatus.SEEDING),
        ]
    )
    def test_terminalize_guards_seeder_owned_runs_named_by_run_id(self, _name: str, status: str) -> None:
        run = self._run("live", status=status)

        # Guarding only the --classification values would let a run id name a run the seeder is
        # still working and skip every rule, canceling it out from under a live worker.
        with self.assertRaisesMessage(CommandError, "still owned by the seeder"):
            self._call("terminalize", "--run-id", str(run.id), "--live-run", "--yes")
        run.refresh_from_db()
        self.assertEqual(run.status, status)

        self._call("terminalize", "--run-id", str(run.id), "--include-seeder-owned", "--live-run", "--yes")

        run.refresh_from_db()
        self.assertEqual(run.status, CohortBackfillRunStatus.CANCELLED)


@override_settings(
    REALTIME_COHORT_TEAM_ALLOWLIST="all",
    BEHAVIORAL_COHORTS_READ_DATABASE_URL="postgres://reader@behavioral-cohorts.example.invalid/behavioral_cohorts",
    BEHAVIORAL_BACKFILL_MERGE_GATE_ATTESTED=True,
    BEHAVIORAL_BACKFILL_DURABILITY_ATTESTED=True,
    BEHAVIORAL_BACKFILL_PERSON_SIZING_ATTESTED=True,
    BEHAVIORAL_BACKFILL_PERSON_TTL_ATTESTED=True,
    BEHAVIORAL_BACKFILL_PERSON_TOPIC_BYTES_BUDGET=1_000_000,
)
class TestManageCohortBackfillRunsAudit(BaseTest):
    def _stamped_cohort(
        self, name: str, leaves: list[dict[str, Any]], *, batch: int, stamps: tuple[str, ...] = _ALL_STAMPS[:1]
    ) -> Cohort:
        cohort = Cohort.objects.create(
            team=self.team,
            name=name,
            cohort_type=CohortType.REALTIME,
            filters={"properties": {"type": "AND", "values": leaves}},
        )
        # A queryset update, like the finalizer's, so save()'s hash maintenance cannot clear the stamps.
        stamped_at = timezone.now() - timedelta(days=1)
        Cohort.objects.filter(id=cohort.id).update(
            count=batch, version=1, last_calculation=timezone.now(), **dict.fromkeys(stamps, stamped_at)
        )
        cohort.refresh_from_db()
        return cohort

    def _audit(self, realtime_members: dict[int, int], *args: str) -> str:
        counts = {(self.team.id, cohort_id): count for cohort_id, count in realtime_members.items()}
        out = io.StringIO()
        with mock.patch.object(
            RealtimeMembershipReader,
            "count_members",
            autospec=True,
            side_effect=lambda _reader, team_id, cohort_id: counts[(team_id, cohort_id)],
        ):
            call_command("manage_cohort_backfill_runs", "audit", "--team-id", str(self.team.id), *args, stdout=out)
        return out.getvalue()

    def _classification(self, output: str, cohort: Cohort) -> str | None:
        match = re.search(rf"^\s+{cohort.id}\s+(\S+)", output, re.MULTILINE)
        return match.group(1) if match else None

    def test_audit_classifies_only_stamped_cohorts_against_their_batch_population(self) -> None:
        empty = self._stamped_cohort("empty", [_BEHAVIORAL_LEAF, _PERSON_LEAF], batch=100)
        healthy = self._stamped_cohort("healthy", [_BEHAVIORAL_LEAF], batch=100)
        partial = self._stamped_cohort("partial", [_BEHAVIORAL_LEAF], batch=100)
        unstamped = self._stamped_cohort("unstamped", [_BEHAVIORAL_LEAF], batch=100, stamps=())

        output = self._audit({empty.id: 0, healthy.id: 90, partial.id: 30, unstamped.id: 0})

        self.assertEqual(self._classification(output, empty), "zero_members")
        self.assertEqual(self._classification(output, healthy), "ok")
        self.assertEqual(self._classification(output, partial), "divergent")
        # A cohort no backfill stamped is not routed to the table, so an empty table is expected.
        self.assertIsNone(self._classification(output, unstamped))
        self.assertIn("2 flagged", output)

    @mock.patch("products.cohorts.backend.backfill.runs.estimate_person_seed_topic_bytes")
    def test_audit_rerun_creates_one_team_run_per_needed_kind_and_refuses_an_occupied_slot(
        self, estimate: mock.Mock
    ) -> None:
        estimate.return_value = PersonSeedEstimate(
            estimated_persons=10,
            pinned_condition_count=1,
            bytes_per_seed=294,
            estimated_topic_bytes=1_000,
            budget_bytes=1_000_000,
        )
        behavioral_only = self._stamped_cohort("behavioral", [_BEHAVIORAL_LEAF], batch=100)
        mixed = self._stamped_cohort("mixed", [_BEHAVIORAL_LEAF, _PERSON_LEAF], batch=100)
        healthy = self._stamped_cohort("healthy", [_BEHAVIORAL_LEAF, _PERSON_LEAF], batch=100)
        realtime_members = {behavioral_only.id: 0, mixed.id: 0, healthy.id: 100}

        self._audit(realtime_members, "--rerun", "--yes")

        participants = {
            kind: set(
                CohortBackfillRunCohort.objects.for_team(self.team.id)
                .filter(run__backfill_kind=kind, run__scope=CohortBackfillScope.TEAM)
                .values_list("cohort_id", flat=True)
            )
            for kind in CohortBackfillKind.values
        }
        self.assertEqual(
            participants,
            {
                CohortBackfillKind.BEHAVIORAL: {behavioral_only.id, mixed.id},
                CohortBackfillKind.PERSON_PROPERTY: {mixed.id},
            },
        )

        output = self._audit(realtime_members, "--rerun", "--yes")

        self.assertIn("No behavioral run", output)
        self.assertIn("No person_property run", output)
        self.assertEqual(CohortBackfillRun.objects.for_team(self.team.id).count(), 2)

    @mock.patch("products.cohorts.backend.backfill.finalize.current_app")
    def test_audit_clear_stamps_nulls_only_flagged_cohorts_and_invalidates_the_flags_cache(
        self, celery_app: mock.Mock
    ) -> None:
        empty = self._stamped_cohort("empty", [_BEHAVIORAL_LEAF], batch=100, stamps=_ALL_STAMPS)
        healthy = self._stamped_cohort("healthy", [_BEHAVIORAL_LEAF], batch=100, stamps=_ALL_STAMPS)

        self._audit({empty.id: 0, healthy.id: 100}, "--clear-stamps", "--yes")

        empty.refresh_from_db()
        healthy.refresh_from_db()
        self.assertEqual([getattr(empty, stamp) for stamp in _ALL_STAMPS], [None, None, None])
        self.assertTrue(all(getattr(healthy, stamp) is not None for stamp in _ALL_STAMPS))
        self.assertFalse(empty.is_flag_compatible)
        # The write bypasses model signals, so a cached flags payload would keep routing the cohort.
        celery_app.send_task.assert_called_once_with(FLAGS_CACHE_TASK, args=(self.team.id,), queue="feature_flags")
        self.assertFalse(CohortBackfillRun.objects.for_team(self.team.id).exists())

    @override_settings(BEHAVIORAL_COHORTS_READ_DATABASE_URL="")
    def test_audit_without_a_membership_dsn_fails_with_a_clear_error(self) -> None:
        self._stamped_cohort("empty", [_BEHAVIORAL_LEAF], batch=100)

        with self.assertRaisesMessage(CommandError, "BEHAVIORAL_COHORTS_READ_DATABASE_URL is not set"):
            self._audit({})
