from datetime import UTC, datetime
from io import StringIO

from posthog.test.base import BaseTest
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from parameterized import parameterized

from products.cohorts.backend.backfill.sizing import PersonSeedEstimate
from products.cohorts.backend.models.backfill import (
    CohortBackfillKind,
    CohortBackfillRun,
    CohortBackfillRunCohort,
    CohortBackfillRunStatus,
)
from products.cohorts.backend.models.cohort import Cohort, CohortType


@override_settings(
    REALTIME_COHORT_TEAM_ALLOWLIST="all",
    BEHAVIORAL_BACKFILL_MERGE_GATE_ATTESTED=True,
    BEHAVIORAL_BACKFILL_DURABILITY_ATTESTED=True,
    BEHAVIORAL_BACKFILL_PERSON_SIZING_ATTESTED=True,
    BEHAVIORAL_BACKFILL_PERSON_TTL_ATTESTED=True,
    BEHAVIORAL_BACKFILL_PERSON_TOPIC_BYTES_BUDGET=1_000_000,
)
class TestCreateCohortBackfillRunCommand(BaseTest):
    def _cohort(self, event: str) -> Cohort:
        return Cohort.objects.create(
            team=self.team,
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": event,
                            "event_type": "events",
                            "value": "performed_event",
                            "conditionHash": f"hash-{event}",
                            "time_value": 7,
                            "time_interval": "day",
                        }
                    ],
                }
            },
        )

    def _person_cohort(self, *, person_metadata: bool = False) -> Cohort:
        values = [
            {
                "type": "person",
                "key": "email",
                "value": ["person@example.com"],
                "operator": "exact",
                "conditionHash": "person0000000001",
            }
        ]
        if person_metadata:
            values.append(
                {
                    "type": "person_metadata",
                    "key": "created_at",
                    "value": "2026-01-01",
                    "operator": "is_date_after",
                }
            )
        return Cohort.objects.create(
            team=self.team,
            cohort_type=CohortType.REALTIME,
            filters={"properties": {"type": "AND", "values": values}},
        )

    def _estimate(
        self,
        *,
        estimated_topic_bytes: int = 2_940,
        budget_bytes: int = 1_000_000,
    ) -> PersonSeedEstimate:
        return PersonSeedEstimate(
            estimated_persons=10,
            pinned_condition_count=1,
            bytes_per_seed=294,
            estimated_topic_bytes=estimated_topic_bytes,
            budget_bytes=budget_bytes,
        )

    @override_settings(BEHAVIORAL_BACKFILL_DURABILITY_ATTESTED=False)
    def test_missing_attestation_errors_without_writing(self) -> None:
        self._cohort("$pageview")

        with self.assertRaisesMessage(CommandError, "processor durability"):
            call_command("create_cohort_backfill_run", team_id=self.team.id, trigger="team_enablement")

        self.assertEqual(CohortBackfillRun.objects.for_team(self.team.id).count(), 0)

    def test_success_creates_team_run_for_every_behavioral_cohort(self) -> None:
        first = self._cohort("$pageview")
        second = self._cohort("signup")
        stdout = StringIO()

        call_command("create_cohort_backfill_run", team_id=self.team.id, trigger="team_enablement", stdout=stdout)

        run = CohortBackfillRun.objects.for_team(self.team.id).get()
        self.assertIn(str(run.id), stdout.getvalue())
        self.assertEqual(
            set(
                CohortBackfillRunCohort.objects.for_team(self.team.id)
                .filter(run=run)
                .values_list("cohort_id", flat=True)
            ),
            {first.id, second.id},
        )

    def test_cohort_ids_limit_the_run(self) -> None:
        selected = self._cohort("$pageview")
        self._cohort("signup")

        call_command(
            "create_cohort_backfill_run",
            team_id=self.team.id,
            trigger="disaster_recovery",
            cohort_ids=[selected.id],
        )

        run = CohortBackfillRun.objects.for_team(self.team.id).get()
        self.assertEqual(
            list(
                CohortBackfillRunCohort.objects.for_team(self.team.id)
                .filter(run=run)
                .values_list("cohort_id", flat=True)
            ),
            [selected.id],
        )

    def test_disaster_recovery_boundary_is_persisted_without_promoting_the_run(self) -> None:
        self._cohort("$pageview")

        call_command(
            "create_cohort_backfill_run",
            team_id=self.team.id,
            trigger="disaster_recovery",
            boundary_at="2026-07-14T09:45:12-03:00",
        )

        run = CohortBackfillRun.objects.for_team(self.team.id).get()
        self.assertEqual(run.boundary_at, datetime(2026, 7, 14, 12, 45, 12, tzinfo=UTC))
        self.assertIsNone(run.boundary_established_at)
        self.assertEqual(run.status, CohortBackfillRunStatus.AWAITING_BOUNDARY)

    @parameterized.expand(
        [
            ("missing_offset", "disaster_recovery", "2026-07-14T09:45:12", "must include a UTC offset"),
            ("invalid", "disaster_recovery", "not-a-timestamp", "must be a valid ISO 8601 timestamp"),
            (
                "utc_overflow",
                "disaster_recovery",
                "0001-01-01T00:00:00+23:59",
                "falls outside the supported UTC range",
            ),
            (
                "wrong_trigger",
                "team_enablement",
                "2026-07-14T09:45:12Z",
                "only valid with --trigger disaster_recovery",
            ),
        ]
    )
    def test_invalid_boundary_returns_clean_command_error(
        self, _name: str, trigger: str, boundary_at: str, error_message: str
    ) -> None:
        self._cohort("$pageview")

        with self.assertRaisesMessage(CommandError, error_message):
            call_command(
                "create_cohort_backfill_run",
                team_id=self.team.id,
                trigger=trigger,
                boundary_at=boundary_at,
            )

        self.assertEqual(CohortBackfillRun.objects.for_team(self.team.id).count(), 0)

    def test_active_team_run_returns_clean_command_error(self) -> None:
        first = self._cohort("$pageview")
        call_command(
            "create_cohort_backfill_run",
            team_id=self.team.id,
            trigger="team_enablement",
            cohort_ids=[first.id],
        )
        second = self._cohort("signup")

        with self.assertRaisesMessage(CommandError, "already has an active team backfill run"):
            call_command(
                "create_cohort_backfill_run",
                team_id=self.team.id,
                trigger="team_enablement",
                cohort_ids=[second.id],
            )

        self.assertEqual(CohortBackfillRun.objects.for_team(self.team.id).count(), 1)

    def test_dry_run_writes_nothing(self) -> None:
        self._cohort("$pageview")
        stdout = StringIO()

        call_command(
            "create_cohort_backfill_run",
            team_id=self.team.id,
            trigger="team_enablement",
            dry_run=True,
            stdout=stdout,
        )

        self.assertIn("Dry run", stdout.getvalue())
        self.assertEqual(CohortBackfillRun.objects.for_team(self.team.id).count(), 0)

    @override_settings(REALTIME_COHORT_TEAM_ALLOWLIST="none")
    def test_non_allowlisted_team_errors(self) -> None:
        with self.assertRaisesMessage(CommandError, "realtime cohort allowlist"):
            call_command("create_cohort_backfill_run", team_id=self.team.id, trigger="team_enablement")

    @mock.patch("products.cohorts.backend.backfill.runs.estimate_person_seed_topic_bytes")
    def test_person_kind_creates_sized_team_run(self, estimate: mock.Mock) -> None:
        cohort = self._person_cohort()
        estimate.return_value = self._estimate()
        stdout = StringIO()

        call_command(
            "create_cohort_backfill_run",
            team_id=self.team.id,
            trigger="team_enablement",
            kind="person_property",
            person_horizon_days=30,
            stdout=stdout,
        )

        run = CohortBackfillRun.objects.for_team(self.team.id).get()
        participation = CohortBackfillRunCohort.objects.for_team(self.team.id).get(run=run)
        self.assertEqual(run.backfill_kind, CohortBackfillKind.PERSON_PROPERTY)
        self.assertEqual(run.pinned["person_horizon_days"], 30)
        self.assertEqual(participation.cohort_id, cohort.id)
        self.assertIn("Created person-property run", stdout.getvalue())
        self.assertIn("10 estimated persons", stdout.getvalue())

    @parameterized.expand(
        [
            (
                "person_missing",
                {"kind": "person_property"},
                "--person-horizon-days is required",
            ),
            (
                "behavioral_present",
                {"kind": "behavioral", "person_horizon_days": 30},
                "--person-horizon-days is only valid",
            ),
        ]
    )
    def test_person_horizon_kind_validation(
        self,
        _name: str,
        options: dict[str, object],
        expected_error: str,
    ) -> None:
        with self.assertRaisesMessage(CommandError, expected_error):
            call_command(
                "create_cohort_backfill_run",
                team_id=self.team.id,
                trigger="team_enablement",
                **options,
            )

    @mock.patch(
        "products.cohorts.backend.management.commands.create_cohort_backfill_run.estimate_person_seed_topic_bytes"
    )
    def test_person_dry_run_prints_estimate_without_writing(self, estimate: mock.Mock) -> None:
        self._person_cohort()
        estimate.return_value = self._estimate()
        stdout = StringIO()

        call_command(
            "create_cohort_backfill_run",
            team_id=self.team.id,
            trigger="team_enablement",
            kind="person_property",
            person_horizon_days=30,
            dry_run=True,
            stdout=stdout,
        )

        self.assertIn("10 estimated persons", stdout.getvalue())
        self.assertIn("would refuse: no", stdout.getvalue())
        self.assertEqual(CohortBackfillRun.objects.for_team(self.team.id).count(), 0)

    @mock.patch("products.cohorts.backend.backfill.runs.estimate_person_seed_topic_bytes")
    def test_person_over_budget_returns_clean_command_error(self, estimate: mock.Mock) -> None:
        self._person_cohort()
        estimate.return_value = self._estimate(
            estimated_topic_bytes=1_000_001,
            budget_bytes=1_000_000,
        )

        with self.assertRaisesMessage(CommandError, "exceed budget"):
            call_command(
                "create_cohort_backfill_run",
                team_id=self.team.id,
                trigger="team_enablement",
                kind="person_property",
                person_horizon_days=30,
            )

        self.assertEqual(CohortBackfillRun.objects.for_team(self.team.id).count(), 0)

    @mock.patch(
        "products.cohorts.backend.management.commands.create_cohort_backfill_run.estimate_person_seed_topic_bytes"
    )
    def test_person_metadata_refusal_is_reported_in_dry_run(self, estimate: mock.Mock) -> None:
        eligible = self._person_cohort()
        refused = self._person_cohort(person_metadata=True)
        estimate.return_value = self._estimate()
        stdout = StringIO()

        call_command(
            "create_cohort_backfill_run",
            team_id=self.team.id,
            trigger="team_enablement",
            kind="person_property",
            person_horizon_days=30,
            dry_run=True,
            stdout=stdout,
        )

        self.assertIn(f"{refused.id} (contains person_metadata filters)", stdout.getvalue())
        self.assertIn("1 cohorts", stdout.getvalue())
        self.assertNotIn(f"{eligible.id} (", stdout.getvalue())
