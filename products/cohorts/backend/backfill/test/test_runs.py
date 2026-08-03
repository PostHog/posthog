from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest
from unittest import mock

from django.db import IntegrityError, transaction
from django.test import override_settings

from parameterized import parameterized

from posthog.tasks.calculate_cohort import trigger_cohort_events_backfill_task

from products.cohorts.backend.backfill.pinning import PersonPinningCapExceeded
from products.cohorts.backend.backfill.runs import (
    create_backfill_run_for_cohort,
    create_person_backfill_run_for_cohort,
    create_person_team_backfill_run,
    create_team_backfill_run,
    supersede_active_runs,
)
from products.cohorts.backend.backfill.sizing import PersonSeedEstimate
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


@override_settings(
    REALTIME_COHORT_TEAM_ALLOWLIST="all",
    BEHAVIORAL_BACKFILL_MERGE_GATE_ATTESTED=True,
    BEHAVIORAL_BACKFILL_DURABILITY_ATTESTED=True,
    BEHAVIORAL_BACKFILL_PERSON_SIZING_ATTESTED=True,
    BEHAVIORAL_BACKFILL_PERSON_TTL_ATTESTED=True,
    BEHAVIORAL_BACKFILL_PERSON_TOPIC_BYTES_BUDGET=1_000_000,
)
class TestPersonBackfillRuns(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        feature_patch = mock.patch(
            "products.cohorts.backend.models.dependencies.posthoganalytics.feature_enabled",
            return_value=False,
        )
        feature_patch.start()
        self.addCleanup(feature_patch.stop)

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
