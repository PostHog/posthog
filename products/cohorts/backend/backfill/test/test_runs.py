from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest
from unittest import mock

from django.db import IntegrityError, transaction
from django.test import override_settings

from parameterized import parameterized

from products.cohorts.backend.backfill.pinning import PersonPinningCapExceeded
from products.cohorts.backend.backfill.runs import (
    BackfillRefusalReason,
    BackfillRunAttempt,
    attempt_backfill_run_for_cohort,
    attempt_person_backfill_run_for_cohort,
    cancel_runs,
    create_backfill_run_for_cohort,
    create_person_backfill_run_for_cohort,
    create_person_team_backfill_run,
    create_team_backfill_run,
    supersede_active_runs,
)
from products.cohorts.backend.backfill.sizing import PersonSeedEstimate, PersonSeedEstimateScanCapExceeded
from products.cohorts.backend.models.backfill import (
    CohortBackfillChunk,
    CohortBackfillKind,
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

        self.assertEqual(
            supersede_active_runs(self.team.id, [cohort.id], kind=CohortBackfillKind.BEHAVIORAL),
            1,
        )

        run.refresh_from_db()
        participation = CohortBackfillRunCohort.objects.for_team(self.team.id).get(run=run)
        self.assertEqual(run.status, CohortBackfillRunStatus.SUPERSEDED)
        self.assertIsNotNone(participation.superseded_at)

    def test_second_active_cohort_run_is_a_benign_noop(self) -> None:
        cohort = self._cohort()
        self.assertIsNotNone(create_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_created"))

        self.assertIsNone(create_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_edited"))
        self.assertEqual(CohortBackfillRun.objects.for_team(self.team.id).count(), 1)

    def test_attempt_names_active_participation_and_a_missing_cohort(self) -> None:
        cohort = self._cohort()
        created = attempt_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_created")
        self.assertIsNotNone(created.run)
        self.assertIsNone(created.reason)

        blocked = attempt_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_edited")
        self.assertIsNone(blocked.run)
        self.assertEqual(blocked.reason, BackfillRefusalReason.PARTICIPATION_ACTIVE)

        missing = attempt_backfill_run_for_cohort(self.team.id, cohort.id + 10_000, "cohort_edited")
        self.assertEqual(missing.reason, BackfillRefusalReason.COHORT_MISSING)

    @parameterized.expand(
        [
            ("behavioral", attempt_backfill_run_for_cohort),
            ("person_property", attempt_person_backfill_run_for_cohort),
        ]
    )
    def test_attempt_names_a_team_outside_the_realtime_allowlist(
        self, _name: str, attempt: Callable[[int, int, str], BackfillRunAttempt]
    ) -> None:
        # A team dropping out of the allowlist is the first gate either creator hits. Unlabelled it
        # lands in the flat `refused` bucket, which reads as an unclassified refusal.
        cohort = self._cohort()

        with override_settings(REALTIME_COHORT_TEAM_ALLOWLIST="none"):
            self.assertEqual(
                attempt(self.team.id, cohort.id, "cohort_created").reason,
                BackfillRefusalReason.TEAM_NOT_REALTIME,
            )

    def test_failed_run_frees_the_per_cohort_slot(self) -> None:
        # The seeder fails a run whose chunk exhausted its retry budget. That only unwedges the
        # cohort if `failed` stops counting as active here: otherwise the uniqueness slot stays
        # taken and no replacement run can ever be created for that cohort.
        cohort = self._cohort()
        first = create_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_created")
        assert first is not None
        self.assertIsNone(create_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_edited"))

        first.status = CohortBackfillRunStatus.FAILED
        first.save(update_fields=["status"])

        self.assertIsNotNone(create_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_edited"))
        self.assertEqual(CohortBackfillRun.objects.for_team(self.team.id).count(), 2)

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

    def test_editing_the_cohort_supersedes_its_active_run(self) -> None:
        # rust/cohort-seeder claims run rows and replays history from the filters the run pinned, so
        # if the post_save receiver stops superseding, an edit leaves the seeder on a stale definition.
        cohort = self._cohort()
        run = create_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_created")
        assert run is not None

        with self.captureOnCommitCallbacks(execute=True):
            cohort.filters = self._filters("signup")
            cohort.save()

        run.refresh_from_db()
        self.assertEqual(run.status, CohortBackfillRunStatus.SUPERSEDED)
        self.assertIsNotNone(create_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_edited"))


@override_settings(
    REALTIME_COHORT_TEAM_ALLOWLIST="all",
    BEHAVIORAL_BACKFILL_MERGE_GATE_ATTESTED=True,
    BEHAVIORAL_BACKFILL_DURABILITY_ATTESTED=True,
    BEHAVIORAL_BACKFILL_PERSON_SIZING_ATTESTED=True,
    BEHAVIORAL_BACKFILL_PERSON_TTL_ATTESTED=True,
    BEHAVIORAL_BACKFILL_PERSON_TOPIC_BYTES_BUDGET=1_000_000,
)
class TestPersonBackfillRuns(BaseTest):
    def _filters(
        self,
        *,
        person_hashes: tuple[str | None, ...] = ("person0000000001",),
        behavioral: bool = True,
        person_metadata: bool = False,
    ) -> dict:
        values: list[dict] = [
            {
                "type": "person",
                "key": "email",
                "value": ["person@example.com"],
                "operator": "exact",
                "conditionHash": condition_hash,
            }
            for condition_hash in person_hashes
        ]
        if behavioral:
            values.append(
                {
                    "type": "behavioral",
                    "key": "$pageview",
                    "event_type": "events",
                    "value": "performed_event",
                    "conditionHash": "behavior00000001",
                    "time_value": 7,
                    "time_interval": "day",
                }
            )
        if person_metadata:
            values.append(
                {
                    "type": "person_metadata",
                    "key": "created_at",
                    "value": "2026-01-01",
                    "operator": "is_date_after",
                }
            )
        return {"properties": {"type": "AND", "values": values}}

    def _cohort(self, **kwargs: object) -> Cohort:
        return Cohort.objects.create(
            team=self.team,
            name="person cohort",
            cohort_type=CohortType.REALTIME,
            filters=self._filters(),
            **kwargs,
        )

    def _estimate(self, *, estimated_topic_bytes: int = 2_940, budget_bytes: int = 1_000_000) -> PersonSeedEstimate:
        return PersonSeedEstimate(
            estimated_persons=10,
            pinned_condition_count=1,
            bytes_per_seed=294,
            estimated_topic_bytes=estimated_topic_bytes,
            budget_bytes=budget_bytes,
        )

    @parameterized.expand(
        [
            ("explicit_horizon", 30, 30),
            ("default_horizon", None, 45),
        ]
    )
    def test_cohort_run_pins_person_definition_and_scan_horizon(
        self,
        _name: str,
        person_horizon_days: int | None,
        expected_horizon_days: int,
    ) -> None:
        cohort = self._cohort()
        now = datetime(2026, 7, 29, 12, tzinfo=UTC)

        with (
            self.settings(BEHAVIORAL_BACKFILL_PERSON_DEFAULT_HORIZON_DAYS=45),
            mock.patch(
                "products.cohorts.backend.backfill.runs.django_timezone.now",
                return_value=now,
            ),
        ):
            run = create_person_backfill_run_for_cohort(
                self.team.id,
                cohort.id,
                "cohort_created",
                person_horizon_days=person_horizon_days,
            )

        assert run is not None
        participation = CohortBackfillRunCohort.objects.for_team(self.team.id).get(run=run)
        self.assertEqual(run.backfill_kind, CohortBackfillKind.PERSON_PROPERTY)
        self.assertEqual(run.person_scan_since, now - timedelta(days=expected_horizon_days))
        self.assertEqual(
            run.pinned,
            {
                "schema_version": 1,
                "conditions": [{"cohort_id": cohort.id, "condition_hash": "person0000000001"}],
                "person_horizon_days": expected_horizon_days,
            },
        )
        self.assertIn("person_seed_estimated_topic_bytes", run.preconditions)
        self.assertEqual(participation.filters_shape_hash, cohort.filters_shape_hash)
        self.assertEqual(participation.behavioral_filters_shape_hash, "")
        self.assertEqual(participation.person_filters_shape_hash, cohort.person_filters_shape_hash)
        self.assertEqual(participation.pinned_filters, cohort.filters)

    def test_behavioral_and_person_runs_coexist_but_duplicate_person_run_is_refused(self) -> None:
        cohort = self._cohort()

        behavioral = create_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_created")
        person = create_person_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_created")

        self.assertIsNotNone(behavioral)
        self.assertIsNotNone(person)
        self.assertIsNone(create_person_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_edited"))
        self.assertEqual(CohortBackfillRun.objects.for_team(self.team.id).count(), 2)

    def test_cohort_run_refuses_non_positive_horizon(self) -> None:
        cohort = self._cohort()

        with mock.patch("products.cohorts.backend.backfill.runs.logger") as logger:
            run = create_person_backfill_run_for_cohort(
                self.team.id,
                cohort.id,
                "cohort_created",
                person_horizon_days=0,
            )

        self.assertIsNone(run)
        self.assertEqual(CohortBackfillRun.objects.for_team(self.team.id).count(), 0)
        logger.warning.assert_called_once_with(
            "cohort_person_backfill_invalid_horizon",
            team_id=self.team.id,
            cohort_id=cohort.id,
            person_horizon_days=0,
        )

    @parameterized.expand([("over_budget",), ("scan_cap_hit",)])
    @mock.patch("products.cohorts.backend.backfill.runs.estimate_person_seed_topic_bytes")
    def test_signal_path_refuses_unsized_person_seed(self, _name: str, estimate: mock.Mock) -> None:
        # A user save replays cost here, so the automated path has to honor the same topic-bytes
        # budget as the operator creator. The scan's own read cap refuses quietly too: it is
        # deterministic for the team, so retrying would only repeat the capped scan.
        if _name == "over_budget":
            estimate.return_value = self._estimate(estimated_topic_bytes=2_000_000)
        else:
            estimate.side_effect = PersonSeedEstimateScanCapExceeded("read cap exceeded")
        cohort = self._cohort()

        self.assertIsNone(create_person_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_created"))
        self.assertEqual(CohortBackfillRun.objects.for_team(self.team.id).count(), 0)

    @mock.patch("products.cohorts.backend.backfill.runs.estimate_person_seed_topic_bytes")
    def test_transient_sizing_failure_reaches_the_retry_machinery(self, estimate: mock.Mock) -> None:
        # A timeout or transport blip is worth retrying; swallowing it would leave the cohort with
        # no run and nothing scheduled to try again until its next edit.
        estimate.side_effect = ConnectionError("clickhouse unavailable")
        cohort = self._cohort()

        with self.assertRaises(ConnectionError):
            create_person_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_created")

        self.assertEqual(CohortBackfillRun.objects.for_team(self.team.id).count(), 0)

    @mock.patch("products.cohorts.backend.backfill.runs.estimate_person_seed_topic_bytes")
    def test_budget_bounds_the_teams_active_person_runs_in_aggregate(self, estimate: mock.Mock) -> None:
        # The seeder's person scan is team-wide per run and the uniqueness constraint is per cohort,
        # so runs that each fit the budget stack cost; the gate has to count what is already in
        # flight for the team.
        estimate.return_value = self._estimate(estimated_topic_bytes=600_000)
        first = self._cohort()
        second = Cohort.objects.create(
            team=self.team,
            name="second person cohort",
            cohort_type=CohortType.REALTIME,
            filters=self._filters(),
        )

        self.assertIsNotNone(create_person_backfill_run_for_cohort(self.team.id, first.id, "cohort_created"))
        self.assertIsNone(create_person_backfill_run_for_cohort(self.team.id, second.id, "cohort_created"))
        self.assertEqual(CohortBackfillRun.objects.for_team(self.team.id).count(), 1)

    @mock.patch("products.cohorts.backend.backfill.runs.estimate_person_seed_topic_bytes")
    def test_consumed_budget_refuses_before_the_sizing_scan(self, estimate: mock.Mock) -> None:
        # Dispatch is debounced per cohort, so once in-flight runs consume the whole budget, every
        # further edited cohort has to refuse before the team-wide sizing scan, not after paying
        # for one each.
        estimate.return_value = self._estimate(estimated_topic_bytes=1_000_000)
        first = self._cohort()
        self.assertIsNotNone(create_person_backfill_run_for_cohort(self.team.id, first.id, "cohort_created"))
        second = Cohort.objects.create(
            team=self.team,
            name="second person cohort",
            cohort_type=CohortType.REALTIME,
            filters=self._filters(),
        )

        estimate.reset_mock()
        self.assertIsNone(create_person_backfill_run_for_cohort(self.team.id, second.id, "cohort_created"))

        estimate.assert_not_called()
        self.assertEqual(CohortBackfillRun.objects.for_team(self.team.id).count(), 1)

    @mock.patch("products.cohorts.backend.backfill.runs.estimate_person_seed_topic_bytes")
    def test_both_budget_gates_report_over_budget(self, estimate: mock.Mock) -> None:
        # The budget refuses in two places — before the sizing scan when in-flight runs already ate
        # it, and after when the estimate pushes the total over. Both have to name the budget, or
        # the alert only sees whichever one the team happens to hit.
        estimate.return_value = self._estimate(estimated_topic_bytes=1_000_001)
        first = self._cohort()
        second = Cohort.objects.create(
            team=self.team,
            name="second person cohort",
            cohort_type=CohortType.REALTIME,
            filters=self._filters(),
        )

        post_scan = attempt_person_backfill_run_for_cohort(self.team.id, first.id, "cohort_created")
        self.assertIsNone(post_scan.run)
        self.assertEqual(post_scan.reason, BackfillRefusalReason.OVER_BUDGET)

        estimate.return_value = self._estimate(estimated_topic_bytes=1_000_000)
        self.assertIsNotNone(create_person_backfill_run_for_cohort(self.team.id, first.id, "cohort_created"))
        estimate.reset_mock()
        pre_scan = attempt_person_backfill_run_for_cohort(self.team.id, second.id, "cohort_created")

        estimate.assert_not_called()
        self.assertIsNone(pre_scan.run)
        self.assertEqual(pre_scan.reason, BackfillRefusalReason.OVER_BUDGET)

    def test_attempt_reports_the_occupied_slot_and_success(self) -> None:
        cohort = self._cohort()

        with mock.patch(
            "products.cohorts.backend.backfill.runs.estimate_person_seed_topic_bytes",
            return_value=self._estimate(),
        ):
            created = attempt_person_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_created")
            self.assertIsNotNone(created.run)
            self.assertIsNone(created.reason)

            blocked = attempt_person_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_edited")

        self.assertIsNone(blocked.run)
        self.assertEqual(blocked.reason, BackfillRefusalReason.PARTICIPATION_ACTIVE)

    @override_settings(BEHAVIORAL_BACKFILL_PERSON_MAX_PINNED_CONDITIONS=0)
    def test_cohort_run_warns_and_refuses_pinning_cap(self) -> None:
        cohort = self._cohort()

        with mock.patch("products.cohorts.backend.backfill.runs.logger") as logger:
            run = create_person_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_created")

        self.assertIsNone(run)
        logger.warning.assert_called_once_with(
            "cohort_person_backfill_pinning_cap_exceeded",
            team_id=self.team.id,
            cohort_id=cohort.id,
            max_conditions=0,
        )

    @parameterized.expand(
        [
            ("behavioral", CohortBackfillKind.BEHAVIORAL),
            ("person_property", CohortBackfillKind.PERSON_PROPERTY),
        ]
    )
    def test_supersession_is_scoped_to_run_kind(self, _name: str, superseded_kind: CohortBackfillKind) -> None:
        cohort = self._cohort()
        behavioral = create_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_created")
        person = create_person_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_created")
        assert behavioral is not None
        assert person is not None

        self.assertEqual(
            supersede_active_runs(self.team.id, [cohort.id], kind=superseded_kind),
            1,
        )

        behavioral.refresh_from_db()
        person.refresh_from_db()
        expected = {
            CohortBackfillKind.BEHAVIORAL: behavioral,
            CohortBackfillKind.PERSON_PROPERTY: person,
        }
        other = {
            CohortBackfillKind.BEHAVIORAL: person,
            CohortBackfillKind.PERSON_PROPERTY: behavioral,
        }
        self.assertEqual(expected[superseded_kind].status, CohortBackfillRunStatus.SUPERSEDED)
        self.assertEqual(other[superseded_kind].status, CohortBackfillRunStatus.AWAITING_BOUNDARY)

    def test_editing_the_person_leaf_supersedes_only_the_person_run(self) -> None:
        # rust/cohort-seeder replays the person conditions a run pinned and the finalizer stamps
        # readiness from them, so a person-leaf edit has to supersede that run. The behavioral run
        # pins leaves this edit does not touch, so it has to survive.
        cohort = self._cohort()
        behavioral = create_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_created")
        person = create_person_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_created")
        assert behavioral is not None
        assert person is not None

        with self.captureOnCommitCallbacks(execute=True):
            cohort.filters = self._filters(person_hashes=("person0000000002",))
            cohort.save()

        behavioral.refresh_from_db()
        person.refresh_from_db()
        participation = CohortBackfillRunCohort.objects.for_team(self.team.id).get(run=person)
        self.assertEqual(person.status, CohortBackfillRunStatus.SUPERSEDED)
        self.assertIsNotNone(participation.superseded_at)
        self.assertEqual(behavioral.status, CohortBackfillRunStatus.AWAITING_BOUNDARY)

    @parameterized.expand(
        [
            ("behavioral", create_backfill_run_for_cohort, CohortBackfillKind.BEHAVIORAL),
            ("person_property", create_person_backfill_run_for_cohort, CohortBackfillKind.PERSON_PROPERTY),
        ]
    )
    def test_seeder_partial_outcome_does_not_wedge_the_cohort(
        self, _name: str, creator, kind: CohortBackfillKind
    ) -> None:
        # The seeder's record_participation_partial supersedes the participation but leaves the run
        # active, so the run still holds the cohort_bfr_active_cohort_kind_uq slot. The creator has
        # to refuse on the run, not only the participation, or it raises IntegrityError; and
        # supersession has to target the run directly, or nothing ever frees the slot while the
        # finalizer's person gate is closed.
        cohort = self._cohort()
        run = creator(self.team.id, cohort.id, "cohort_created")
        assert run is not None
        CohortBackfillRunCohort.objects.for_team(self.team.id).filter(run=run).update(
            superseded_at=datetime.now(UTC), error="stage 2 hash mismatch"
        )
        CohortBackfillRun.objects.for_team(self.team.id).filter(id=run.id).update(
            status=CohortBackfillRunStatus.RECONCILING
        )

        # The active-run refusal has to fire in the pre-pass, before the sizing scan: the sibling
        # IntegrityError catch also returns None, so without this the run-level guard is unpinned.
        with mock.patch("products.cohorts.backend.backfill.runs.estimate_person_seed_topic_bytes") as estimate:
            self.assertIsNone(creator(self.team.id, cohort.id, "cohort_edited"))
        estimate.assert_not_called()

        supersede_active_runs(self.team.id, [cohort.id], kind=kind)
        run.refresh_from_db()
        self.assertEqual(run.status, CohortBackfillRunStatus.SUPERSEDED)
        self.assertIsNotNone(creator(self.team.id, cohort.id, "cohort_edited"))

    @parameterized.expand(
        [
            ("behavioral_only", {"filters": None}),
            ("static", {"is_static": True}),
            ("deleted", {"deleted": True}),
            ("non_realtime", {"cohort_type": CohortType.BEHAVIORAL}),
            ("hashless", {"filters": "hashless"}),
            ("person_metadata", {"filters": "person_metadata"}),
        ]
    )
    def test_ineligible_cohort_is_refused(self, _name: str, overrides: dict[str, object]) -> None:
        filters = self._filters()
        if overrides.pop("filters", "") is None:
            filters = self._filters(person_hashes=(), behavioral=True)
        elif _name == "hashless":
            filters = self._filters(person_hashes=(None,), behavioral=False)
        elif _name == "person_metadata":
            filters = self._filters(person_metadata=True)
        cohort_type = overrides.pop("cohort_type", CohortType.REALTIME)
        cohort = Cohort.objects.create(
            team=self.team,
            cohort_type=cohort_type,
            filters=filters,
            **overrides,
        )

        self.assertIsNone(create_person_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_created"))

    @mock.patch("products.cohorts.backend.backfill.runs.estimate_person_seed_topic_bytes")
    def test_team_run_persists_estimate_and_uses_boundary_for_scan_horizon(self, estimate: mock.Mock) -> None:
        cohort = self._cohort()
        estimate.return_value = self._estimate()
        boundary = datetime(2026, 7, 20, 12, tzinfo=UTC)

        run = create_person_team_backfill_run(
            self.team.id,
            "disaster_recovery",
            30,
            [cohort.id],
            boundary_at=boundary,
        )

        self.assertEqual(run.person_scan_since, boundary - timedelta(days=30))
        self.assertEqual(run.preconditions["person_seed_estimated_persons"], 10)
        self.assertEqual(run.preconditions["person_seed_estimated_topic_bytes"], 2_940)
        participation = CohortBackfillRunCohort.objects.for_team(self.team.id).get(run=run)
        self.assertEqual(participation.behavioral_filters_shape_hash, "")
        self.assertNotEqual(participation.person_filters_shape_hash, "")

    @mock.patch("products.cohorts.backend.backfill.runs.estimate_person_seed_topic_bytes")
    def test_per_kind_team_uniqueness(self, estimate: mock.Mock) -> None:
        self._cohort()
        estimate.return_value = self._estimate()
        behavioral = create_team_backfill_run(self.team.id, "team_enablement")
        person = create_person_team_backfill_run(self.team.id, "team_enablement", 30)

        self.assertEqual(behavioral.backfill_kind, CohortBackfillKind.BEHAVIORAL)
        self.assertEqual(person.backfill_kind, CohortBackfillKind.PERSON_PROPERTY)
        with self.assertRaisesMessage(ValueError, "active person-property backfill runs"):
            create_person_team_backfill_run(self.team.id, "team_enablement", 30)

    @mock.patch("products.cohorts.backend.backfill.runs.estimate_person_seed_topic_bytes")
    def test_team_run_refuses_when_pinned_conditions_drift_during_sizing(self, estimate: mock.Mock) -> None:
        cohort = self._cohort()

        def edit_cohort_mid_sizing(*args: object, **kwargs: object) -> PersonSeedEstimate:
            # The estimate is the whole window the run is sized outside the lock, so drifting the
            # definition here is what the re-pin under `select_for_update` has to catch.
            Cohort.objects.filter(id=cohort.id).update(filters=self._filters(person_hashes=("person0000000002",)))
            return self._estimate()

        estimate.side_effect = edit_cohort_mid_sizing

        with self.assertRaisesMessage(ValueError, "changed during sizing"):
            create_person_team_backfill_run(self.team.id, "team_enablement", 30)

        self.assertEqual(CohortBackfillRun.objects.for_team(self.team.id).count(), 0)

    def test_active_team_run_uniqueness_index_is_per_kind(self) -> None:
        # Bypasses the creators' pre-check on purpose: this pins the partial unique index migration
        # 0009 swapped in, which is the only guard left if the pre-check is ever refactored away.
        def create_team_run(kind: CohortBackfillKind) -> None:
            CohortBackfillRun.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                backfill_kind=kind,
                trigger_kind="team_enablement",
                scope=CohortBackfillScope.TEAM,
                status=CohortBackfillRunStatus.AWAITING_BOUNDARY,
                timezone="UTC",
            )

        create_team_run(CohortBackfillKind.BEHAVIORAL)
        create_team_run(CohortBackfillKind.PERSON_PROPERTY)

        with self.assertRaises(IntegrityError), transaction.atomic():
            create_team_run(CohortBackfillKind.PERSON_PROPERTY)

    @mock.patch("products.cohorts.backend.backfill.runs.estimate_person_seed_topic_bytes")
    def test_team_run_refuses_over_budget_estimate(self, estimate: mock.Mock) -> None:
        self._cohort()
        estimate.return_value = self._estimate(
            estimated_topic_bytes=1_000_001,
            budget_bytes=1_000_000,
        )

        with self.assertRaisesMessage(ValueError, "exceed budget"):
            create_person_team_backfill_run(self.team.id, "team_enablement", 30)

        self.assertEqual(CohortBackfillRun.objects.for_team(self.team.id).count(), 0)

    @override_settings(BEHAVIORAL_BACKFILL_PERSON_MAX_PINNED_CONDITIONS=0)
    @mock.patch("products.cohorts.backend.backfill.runs.estimate_person_seed_topic_bytes")
    def test_team_run_refuses_pinning_cap_before_sizing(self, estimate: mock.Mock) -> None:
        self._cohort()

        with self.assertRaises(PersonPinningCapExceeded):
            create_person_team_backfill_run(self.team.id, "team_enablement", 30)

        estimate.assert_not_called()

    @parameterized.expand(
        [
            ("sizing", "BEHAVIORAL_BACKFILL_PERSON_SIZING_ATTESTED", "person seed sizing"),
            ("ttl", "BEHAVIORAL_BACKFILL_PERSON_TTL_ATTESTED", "person record TTL"),
        ]
    )
    def test_team_run_requires_person_attestations(
        self,
        _name: str,
        setting_name: str,
        expected_error: str,
    ) -> None:
        self._cohort()

        with self.settings(**{setting_name: False}), self.assertRaisesMessage(ValueError, expected_error):
            create_person_team_backfill_run(self.team.id, "team_enablement", 30)


@override_settings(
    REALTIME_COHORT_TEAM_ALLOWLIST="all",
    BEHAVIORAL_BACKFILL_MERGE_GATE_ATTESTED=True,
    BEHAVIORAL_BACKFILL_DURABILITY_ATTESTED=True,
)
class TestCancelRuns(BaseTest):
    def _cohort(self, event: str = "$pageview") -> Cohort:
        return Cohort.objects.create(
            team=self.team,
            name=event,
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": event,
                            "event_type": "events",
                            "value": "performed_event_multiple",
                            "conditionHash": f"hash-{event}",
                            "time_value": 7,
                            "time_interval": "day",
                            "operator": "gte",
                            "operator_value": 2,
                        }
                    ],
                }
            },
        )

    @parameterized.expand(
        [
            ("cohort_scoped", CohortBackfillScope.COHORT),
            ("team_scoped", CohortBackfillScope.TEAM),
        ]
    )
    def test_cancel_frees_the_active_uniqueness_slot(self, _name: str, scope: str) -> None:
        cohort = self._cohort()
        if scope == CohortBackfillScope.COHORT:
            run = create_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_created")
        else:
            run = create_team_backfill_run(self.team.id, "team_enablement")
        assert run is not None
        CohortBackfillRun.objects.for_team(self.team.id).filter(id=run.id).update(
            status=CohortBackfillRunStatus.SEEDING
        )
        self.assertIsNone(create_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_edited"))

        outcome = cancel_runs([(run.id, self.team.id)], reason="wedged in seeding")

        run.refresh_from_db()
        self.assertEqual(outcome.cancelled_run_ids, (run.id,))
        self.assertEqual(run.status, CohortBackfillRunStatus.CANCELLED)
        self.assertIsNotNone(run.finished_at)
        self.assertEqual(run.error, "wedged in seeding")
        # Releasing the partial unique constraint is the whole point: a run nobody can finish
        # otherwise blocks its cohort or team from ever backfilling again.
        self.assertIsNotNone(create_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_edited"))

    def test_cancel_refuses_a_run_whose_readiness_was_already_stamped(self) -> None:
        cohort = self._cohort()
        run = create_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_created")
        assert run is not None
        CohortBackfillRunCohort.objects.for_team(self.team.id).filter(run_id=run.id).update(
            stamped_at=datetime.now(UTC)
        )

        outcome = cancel_runs([(run.id, self.team.id)], reason="sweep")

        run.refresh_from_db()
        # A stamp is one way and the flags service already reads it, so a cancel behind one would
        # leave the cohort marked ready by a run claiming it was abandoned.
        self.assertEqual(outcome.refused, ((run.id, "stamped"),))
        self.assertEqual(run.status, CohortBackfillRunStatus.AWAITING_BOUNDARY)

    @parameterized.expand([("refused", False), ("allowed", True)])
    def test_cancel_only_touches_a_finalizable_run_on_request(self, _name: str, allow: bool) -> None:
        cohort = self._cohort()
        run = create_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_created")
        assert run is not None
        CohortBackfillRun.objects.for_team(self.team.id).filter(id=run.id).update(
            status=CohortBackfillRunStatus.RECONCILING, reconcile_observed_at=datetime.now(UTC)
        )

        outcome = cancel_runs([(run.id, self.team.id)], reason="sweep", allow_finalizable=allow)

        run.refresh_from_db()
        # The seeder may have observed the run since the operator listed it, and this one is a
        # finished backfill the finalizer would legitimately complete.
        if allow:
            self.assertEqual(outcome.cancelled_run_ids, (run.id,))
            self.assertEqual(run.status, CohortBackfillRunStatus.CANCELLED)
        else:
            self.assertEqual(outcome.refused, ((run.id, "finalizable"),))
            self.assertEqual(run.status, CohortBackfillRunStatus.RECONCILING)

    def test_cancel_keeps_an_earlier_supersession_message(self) -> None:
        cohort = self._cohort()
        run = create_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_created")
        assert run is not None
        supersede_active_runs(self.team.id, [cohort.id], kind=CohortBackfillKind.BEHAVIORAL)
        CohortBackfillRun.objects.for_team(self.team.id).filter(id=run.id).update(
            status=CohortBackfillRunStatus.SEEDING
        )
        participation = CohortBackfillRunCohort.objects.for_team(self.team.id).get(run_id=run.id)

        cancel_runs([(run.id, self.team.id)], reason="operator sweep")

        participation.refresh_from_db()
        # The edit-time supersession is why this backfill stopped mattering; operator text must not
        # overwrite that provenance.
        self.assertEqual(participation.error, "Cohort definition changed during backfill")

    def test_cancel_drains_an_observed_run_whose_participations_are_all_resolved(self) -> None:
        cohort = self._cohort()
        run = create_backfill_run_for_cohort(self.team.id, cohort.id, "cohort_created")
        assert run is not None
        CohortBackfillRunCohort.objects.for_team(self.team.id).filter(run_id=run.id).update(
            superseded_at=datetime.now(UTC)
        )
        CohortBackfillRun.objects.for_team(self.team.id).filter(id=run.id).update(
            status=CohortBackfillRunStatus.RECONCILING, reconcile_observed_at=datetime.now(UTC)
        )

        outcome = cancel_runs([(run.id, self.team.id)], reason="orphaned sweep")

        run.refresh_from_db()
        # The inventory classifies this `orphaned`, not `finalizable`, because the finalizer would
        # only terminalize it. Refusing it here would leave nothing able to release its slot.
        self.assertEqual(outcome.cancelled_run_ids, (run.id,))
        self.assertEqual(run.status, CohortBackfillRunStatus.CANCELLED)
