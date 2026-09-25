import io
import re
import json

from posthog.test.base import BaseTest

from django.core.management import CommandError, call_command
from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.tasks.calculate_cohort import finalize_cohort_backfill_runs  # noqa: F401  breaks an import cycle

from products.cohorts.backend.backfill.finalize import finalize_backfill_runs
from products.cohorts.backend.backfill.readiness import ensure_filters_shape_hash
from products.cohorts.backend.models.backfill import (
    CohortBackfillRun,
    CohortBackfillRunCohort,
    CohortBackfillRunStatus,
    CohortBackfillScope,
    CohortBackfillTrigger,
)
from products.cohorts.backend.models.cohort import Cohort, CohortType


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
