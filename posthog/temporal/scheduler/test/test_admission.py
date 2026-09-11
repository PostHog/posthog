import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier

from unittest.mock import MagicMock, patch

from django.db import close_old_connections
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.utils import timezone

from prometheus_client import CollectorRegistry

from posthog.models.temporal_scheduler import TemporalSchedulerClaim, TemporalSchedulerPermitPool
from posthog.temporal.scheduler.admission import (
    SchedulerAdmissionLimits,
    SchedulerClaimRequest,
    SchedulerOccurrenceHashCollision,
    complete_scheduler_claim,
    confirm_scheduler_claim,
    defer_scheduler_claim_recovery,
    list_expired_scheduler_claims,
    prune_inactive_scheduler_claims,
    quarantine_scheduler_claim,
    release_scheduler_claim,
    renew_scheduler_claim,
    reserve_scheduler_claims,
)
from posthog.temporal.scheduler.metrics import SchedulerMetrics

SCHEDULER = "subscriptions"
REGION = "eu"


def _request(tenant: str, occurrence: str) -> SchedulerClaimRequest:
    return SchedulerClaimRequest(
        tenant_key=tenant,
        occurrence_key=occurrence,
        workflow_id=f"workflow-{occurrence}",
    )


def _limits(global_limit: int = 3, tenant_limit: int = 2) -> SchedulerAdmissionLimits:
    return SchedulerAdmissionLimits(
        max_in_flight=global_limit,
        max_in_flight_per_tenant=tenant_limit,
        lease_duration=timedelta(minutes=5),
    )


class TestReserveSchedulerClaims(TestCase):
    def test_preserves_order_while_enforcing_global_and_tenant_capacity(self) -> None:
        requests = [
            _request("team:1", "one"),
            _request("team:1", "two"),
            _request("team:1", "three"),
            _request("team:2", "four"),
        ]

        result = reserve_scheduler_claims(
            scheduler=SCHEDULER,
            region=REGION,
            requests=requests,
            limits=_limits(),
        )

        self.assertEqual([reservation.occurrence_key for reservation in result.reservations], ["one", "two", "four"])
        self.assertEqual(result.already_claimed, 0)
        self.assertEqual(result.deferred_for_capacity, 1)
        pools = {
            pool.tenant_key: pool.in_flight
            for pool in TemporalSchedulerPermitPool.objects.filter(scheduler=SCHEDULER, region=REGION)
        }
        self.assertEqual(pools, {"": 3, "team:1": 2, "team:2": 1})

    def test_existing_and_duplicate_occurrences_are_not_reserved_twice(self) -> None:
        request = _request("team:1", "one")
        first = reserve_scheduler_claims(
            scheduler=SCHEDULER,
            region=REGION,
            requests=[request],
            limits=_limits(),
        )

        second = reserve_scheduler_claims(
            scheduler=SCHEDULER,
            region=REGION,
            requests=[request, request],
            limits=_limits(),
        )

        self.assertEqual(len(first.reservations), 1)
        self.assertEqual(second.reservations, ())
        self.assertEqual(second.already_claimed, 2)
        self.assertEqual(TemporalSchedulerClaim.objects.count(), 1)
        self.assertEqual(
            TemporalSchedulerPermitPool.objects.get(scheduler=SCHEDULER, region=REGION, tenant_key="").in_flight,
            1,
        )

    def test_retry_with_same_reservation_token_returns_owned_claim_without_double_counting(self) -> None:
        claim_token = uuid.uuid4()
        request = SchedulerClaimRequest(
            tenant_key="team:1",
            occurrence_key="one",
            workflow_id="workflow-one",
            claim_token=claim_token,
        )

        first = reserve_scheduler_claims(
            scheduler=SCHEDULER,
            region=REGION,
            requests=[request],
            limits=_limits(),
        )
        retried = reserve_scheduler_claims(
            scheduler=SCHEDULER,
            region=REGION,
            requests=[request],
            limits=_limits(),
        )

        self.assertEqual(retried.reservations, first.reservations)
        self.assertEqual(retried.already_claimed, 0)
        self.assertEqual(TemporalSchedulerClaim.objects.count(), 1)
        self.assertEqual(
            TemporalSchedulerPermitPool.objects.get(scheduler=SCHEDULER, region=REGION, tenant_key="").in_flight,
            1,
        )

    def test_duplicate_deferred_requests_are_all_counted_as_deferred(self) -> None:
        reserve_scheduler_claims(
            scheduler=SCHEDULER,
            region=REGION,
            requests=[_request("team:1", "existing")],
            limits=_limits(global_limit=1, tenant_limit=1),
        )
        request = _request("team:2", "deferred")

        result = reserve_scheduler_claims(
            scheduler=SCHEDULER,
            region=REGION,
            requests=[request, request],
            limits=_limits(global_limit=1, tenant_limit=1),
        )

        self.assertEqual(result.reservations, ())
        self.assertEqual(result.already_claimed, 0)
        self.assertEqual(result.deferred_for_capacity, 2)

    def test_available_claim_is_reused_with_fresh_token(self) -> None:
        request = _request("team:1", "one")
        first = reserve_scheduler_claims(
            scheduler=SCHEDULER,
            region=REGION,
            requests=[request],
            limits=_limits(),
        ).reservations[0]
        self.assertTrue(release_scheduler_claim(first.claim_id, first.claim_token, error="start failed"))

        second = reserve_scheduler_claims(
            scheduler=SCHEDULER,
            region=REGION,
            requests=[request],
            limits=_limits(),
        ).reservations[0]

        self.assertEqual(second.claim_id, first.claim_id)
        self.assertNotEqual(second.claim_token, first.claim_token)
        claim = TemporalSchedulerClaim.objects.get(id=second.claim_id)
        self.assertEqual(claim.attempt_count, 2)
        self.assertEqual(claim.status, TemporalSchedulerClaim.Status.RESERVED)
        self.assertEqual(claim.last_error, "")

    def test_completed_claim_is_never_reused(self) -> None:
        request = _request("team:1", "one")
        reservation = reserve_scheduler_claims(
            scheduler=SCHEDULER,
            region=REGION,
            requests=[request],
            limits=_limits(),
        ).reservations[0]
        self.assertTrue(
            confirm_scheduler_claim(
                reservation.claim_id,
                reservation.claim_token,
                lease_duration=timedelta(minutes=5),
            )
        )
        self.assertTrue(complete_scheduler_claim(reservation.claim_id, reservation.claim_token))

        result = reserve_scheduler_claims(
            scheduler=SCHEDULER,
            region=REGION,
            requests=[request],
            limits=_limits(),
        )

        self.assertEqual(result.reservations, ())
        self.assertEqual(result.already_claimed, 1)

    @patch("posthog.temporal.scheduler.admission._occurrence_hash", return_value="a" * 64)
    def test_hash_collision_fails_closed(self, _hash: object) -> None:
        reserve_scheduler_claims(
            scheduler=SCHEDULER,
            region=REGION,
            requests=[_request("team:1", "one")],
            limits=_limits(),
        )

        with self.assertRaises(SchedulerOccurrenceHashCollision):
            reserve_scheduler_claims(
                scheduler=SCHEDULER,
                region=REGION,
                requests=[_request("team:1", "different")],
                limits=_limits(),
            )

    @patch("posthog.temporal.scheduler.admission.TemporalSchedulerClaim.objects.bulk_create")
    def test_claim_write_failure_rolls_back_permit_counters(self, bulk_create: MagicMock) -> None:
        TemporalSchedulerPermitPool.objects.create(scheduler=SCHEDULER, region=REGION)
        bulk_create.side_effect = RuntimeError("database write failed")

        with self.assertRaisesRegex(RuntimeError, "database write failed"):
            reserve_scheduler_claims(
                scheduler=SCHEDULER,
                region=REGION,
                requests=[_request("team:1", "one")],
                limits=_limits(),
            )

        self.assertEqual(
            TemporalSchedulerPermitPool.objects.get(scheduler=SCHEDULER, region=REGION, tenant_key="").in_flight,
            0,
        )
        self.assertFalse(TemporalSchedulerPermitPool.objects.filter(tenant_key="team:1").exists())

    @patch("posthog.temporal.scheduler.admission.TemporalSchedulerClaim.objects.bulk_update")
    def test_reused_claim_write_failure_rolls_back_claim_and_permit_counters(self, bulk_update: MagicMock) -> None:
        request = _request("team:1", "one")
        first = reserve_scheduler_claims(
            scheduler=SCHEDULER,
            region=REGION,
            requests=[request],
            limits=_limits(),
        ).reservations[0]
        self.assertTrue(release_scheduler_claim(first.claim_id, first.claim_token))
        bulk_update.side_effect = RuntimeError("database write failed")

        with self.assertRaisesRegex(RuntimeError, "database write failed"):
            reserve_scheduler_claims(
                scheduler=SCHEDULER,
                region=REGION,
                requests=[request],
                limits=_limits(),
            )

        claim = TemporalSchedulerClaim.objects.get(id=first.claim_id)
        self.assertEqual(claim.status, TemporalSchedulerClaim.Status.AVAILABLE)
        self.assertEqual(claim.claim_token, first.claim_token)
        self.assertEqual(claim.attempt_count, 1)
        self.assertEqual(
            TemporalSchedulerPermitPool.objects.get(scheduler=SCHEDULER, region=REGION, tenant_key="").in_flight,
            0,
        )

    def test_invalid_limits_and_identifiers_fail_before_writing(self) -> None:
        invalid_cases = [
            ("", REGION, [_request("team:1", "one")], _limits()),
            (SCHEDULER, "", [_request("team:1", "one")], _limits()),
            (SCHEDULER, REGION, [_request("", "one")], _limits()),
            (SCHEDULER, REGION, [_request("team:1", "")], _limits()),
            ("   ", REGION, [_request("team:1", "one")], _limits()),
            (SCHEDULER, "   ", [_request("team:1", "one")], _limits()),
            (SCHEDULER, REGION, [_request("   ", "one")], _limits()),
            (SCHEDULER, REGION, [_request("team:1", "   ")], _limits()),
            (SCHEDULER, REGION, [_request("team:1", "one")], _limits(global_limit=0)),
            (SCHEDULER, REGION, [_request("team:1", "one")], _limits(global_limit=1, tenant_limit=2)),
        ]

        for scheduler, region, requests, limits in invalid_cases:
            with self.subTest(scheduler=scheduler, region=region, requests=requests, limits=limits):
                with self.assertRaises(ValueError):
                    reserve_scheduler_claims(
                        scheduler=scheduler,
                        region=region,
                        requests=requests,
                        limits=limits,
                    )

        self.assertFalse(TemporalSchedulerPermitPool.objects.exists())
        self.assertFalse(TemporalSchedulerClaim.objects.exists())


class TestSchedulerClaimLifecycle(TestCase):
    def setUp(self) -> None:
        self.now = timezone.now()
        self.reservation = reserve_scheduler_claims(
            scheduler=SCHEDULER,
            region=REGION,
            requests=[_request("team:1", "one")],
            limits=_limits(),
            now=self.now,
        ).reservations[0]

    def _global_in_flight(self) -> int:
        return TemporalSchedulerPermitPool.objects.get(scheduler=SCHEDULER, region=REGION, tenant_key="").in_flight

    def test_confirm_and_renew_are_token_fenced(self) -> None:
        wrong_token = uuid.uuid4()
        self.assertFalse(
            confirm_scheduler_claim(
                self.reservation.claim_id,
                wrong_token,
                lease_duration=timedelta(minutes=10),
                now=self.now,
            )
        )
        self.assertTrue(
            confirm_scheduler_claim(
                self.reservation.claim_id,
                self.reservation.claim_token,
                lease_duration=timedelta(minutes=10),
                now=self.now,
            )
        )
        self.assertTrue(
            confirm_scheduler_claim(
                self.reservation.claim_id,
                self.reservation.claim_token,
                lease_duration=timedelta(minutes=10),
                now=self.now,
            )
        )
        self.assertFalse(
            confirm_scheduler_claim(
                self.reservation.claim_id,
                wrong_token,
                lease_duration=timedelta(minutes=10),
                now=self.now,
            )
        )
        self.assertTrue(
            renew_scheduler_claim(
                self.reservation.claim_id,
                self.reservation.claim_token,
                lease_duration=timedelta(minutes=15),
                now=self.now,
            )
        )

        claim = TemporalSchedulerClaim.objects.get(id=self.reservation.claim_id)
        self.assertEqual(claim.status, TemporalSchedulerClaim.Status.CONFIRMED)
        self.assertEqual(claim.lease_expires_at, self.now + timedelta(minutes=15))
        self.assertEqual(self._global_in_flight(), 1)

    def test_older_renewal_does_not_shorten_the_current_lease(self) -> None:
        self.assertTrue(
            confirm_scheduler_claim(
                self.reservation.claim_id,
                self.reservation.claim_token,
                lease_duration=timedelta(minutes=20),
                now=self.now,
            )
        )
        self.assertTrue(
            renew_scheduler_claim(
                self.reservation.claim_id,
                self.reservation.claim_token,
                lease_duration=timedelta(minutes=5),
                now=self.now,
            )
        )

        claim = TemporalSchedulerClaim.objects.get(id=self.reservation.claim_id)
        self.assertEqual(claim.lease_expires_at, self.now + timedelta(minutes=20))

    def test_repeated_confirmation_does_not_shorten_a_renewed_lease(self) -> None:
        self.assertTrue(
            confirm_scheduler_claim(
                self.reservation.claim_id,
                self.reservation.claim_token,
                lease_duration=timedelta(minutes=10),
                now=self.now,
            )
        )
        self.assertTrue(
            renew_scheduler_claim(
                self.reservation.claim_id,
                self.reservation.claim_token,
                lease_duration=timedelta(minutes=60),
                now=self.now,
            )
        )
        self.assertTrue(
            confirm_scheduler_claim(
                self.reservation.claim_id,
                self.reservation.claim_token,
                lease_duration=timedelta(minutes=10),
                now=self.now,
            )
        )

        claim = TemporalSchedulerClaim.objects.get(id=self.reservation.claim_id)
        self.assertEqual(claim.lease_expires_at, self.now + timedelta(minutes=60))

    def test_unconfirmed_claim_cannot_be_completed(self) -> None:
        self.assertFalse(
            complete_scheduler_claim(self.reservation.claim_id, self.reservation.claim_token, now=self.now)
        )
        self.assertEqual(self._global_in_flight(), 1)
        self.assertEqual(
            TemporalSchedulerClaim.objects.get(id=self.reservation.claim_id).status,
            TemporalSchedulerClaim.Status.RESERVED,
        )

    def test_metric_lookup_failure_does_not_turn_successful_transition_into_failure(self) -> None:
        with patch(
            "posthog.temporal.scheduler.admission.TemporalSchedulerClaim.objects.only",
            side_effect=RuntimeError("metrics read failed"),
        ):
            self.assertTrue(
                confirm_scheduler_claim(
                    self.reservation.claim_id,
                    self.reservation.claim_token,
                    lease_duration=timedelta(minutes=10),
                    now=self.now,
                )
            )

        claim = TemporalSchedulerClaim.objects.get(id=self.reservation.claim_id)
        self.assertEqual(claim.status, TemporalSchedulerClaim.Status.CONFIRMED)

    def test_terminal_transition_releases_each_permit_exactly_once(self) -> None:
        self.assertTrue(
            confirm_scheduler_claim(
                self.reservation.claim_id,
                self.reservation.claim_token,
                lease_duration=timedelta(minutes=10),
                now=self.now,
            )
        )
        self.assertTrue(complete_scheduler_claim(self.reservation.claim_id, self.reservation.claim_token, now=self.now))
        self.assertTrue(complete_scheduler_claim(self.reservation.claim_id, self.reservation.claim_token, now=self.now))

        claim = TemporalSchedulerClaim.objects.get(id=self.reservation.claim_id)
        self.assertEqual(claim.status, TemporalSchedulerClaim.Status.COMPLETED)
        self.assertEqual(claim.completed_at, self.now)
        self.assertIsNone(claim.lease_expires_at)
        self.assertEqual(self._global_in_flight(), 0)
        self.assertEqual(
            TemporalSchedulerPermitPool.objects.get(scheduler=SCHEDULER, region=REGION, tenant_key="team:1").in_flight,
            0,
        )

    def test_old_token_cannot_release_reused_claim(self) -> None:
        self.assertTrue(release_scheduler_claim(self.reservation.claim_id, self.reservation.claim_token))
        replacement = reserve_scheduler_claims(
            scheduler=SCHEDULER,
            region=REGION,
            requests=[_request("team:1", "one")],
            limits=_limits(),
        ).reservations[0]

        self.assertFalse(release_scheduler_claim(replacement.claim_id, self.reservation.claim_token))
        self.assertEqual(self._global_in_flight(), 1)

    def test_release_bounds_error_and_makes_claim_available(self) -> None:
        self.assertTrue(
            release_scheduler_claim(
                self.reservation.claim_id,
                self.reservation.claim_token,
                error="x" * 10_000,
            )
        )

        claim = TemporalSchedulerClaim.objects.get(id=self.reservation.claim_id)
        self.assertEqual(claim.status, TemporalSchedulerClaim.Status.AVAILABLE)
        self.assertEqual(len(claim.last_error), 2_000)
        self.assertEqual(self._global_in_flight(), 0)

    def test_quarantine_releases_capacity_and_blocks_automatic_reuse(self) -> None:
        self.assertTrue(
            quarantine_scheduler_claim(
                self.reservation.claim_id,
                self.reservation.claim_token,
                error="poison input",
            )
        )

        result = reserve_scheduler_claims(
            scheduler=SCHEDULER,
            region=REGION,
            requests=[_request("team:1", "one")],
            limits=_limits(),
        )
        self.assertEqual(result.reservations, ())
        self.assertEqual(result.already_claimed, 1)
        self.assertEqual(self._global_in_flight(), 0)

    def test_expired_claims_are_listed_but_not_reclaimed(self) -> None:
        later = self.now + timedelta(minutes=6)

        expired = list_expired_scheduler_claims(
            scheduler=SCHEDULER,
            region=REGION,
            limit=10,
            now=later,
        )
        second_attempt = reserve_scheduler_claims(
            scheduler=SCHEDULER,
            region=REGION,
            requests=[_request("team:1", "one")],
            limits=_limits(),
            now=later,
        )

        self.assertEqual([claim.id for claim in expired], [self.reservation.claim_id])
        self.assertEqual(second_attempt.reservations, ())
        self.assertEqual(second_attempt.already_claimed, 1)
        self.assertEqual(self._global_in_flight(), 1)

    def test_recovery_does_not_release_a_claim_renewed_after_expiry_was_observed(self) -> None:
        self.assertTrue(
            confirm_scheduler_claim(
                self.reservation.claim_id,
                self.reservation.claim_token,
                lease_duration=timedelta(minutes=5),
                now=self.now,
            )
        )
        recovery_time = self.now + timedelta(minutes=6)
        expired_claim = list_expired_scheduler_claims(
            scheduler=SCHEDULER,
            region=REGION,
            limit=1,
            now=recovery_time,
        )[0]

        self.assertTrue(
            renew_scheduler_claim(
                self.reservation.claim_id,
                self.reservation.claim_token,
                lease_duration=timedelta(minutes=15),
                now=recovery_time,
            )
        )
        self.assertFalse(
            release_scheduler_claim(
                self.reservation.claim_id,
                self.reservation.claim_token,
                now=recovery_time,
                expected_lease_expires_at=expired_claim.lease_expires_at,
            )
        )
        self.assertEqual(self._global_in_flight(), 1)

    def test_recovery_deferral_sets_a_transaction_local_lock_timeout(self) -> None:
        expected_lease = TemporalSchedulerClaim.objects.get(id=self.reservation.claim_id).lease_expires_at
        assert expected_lease is not None

        with patch("posthog.temporal.scheduler.admission._set_scheduler_lock_timeout") as set_lock_timeout:
            self.assertTrue(
                defer_scheduler_claim_recovery(
                    self.reservation.claim_id,
                    self.reservation.claim_token,
                    lease_duration=timedelta(minutes=5),
                    error="Temporal status unavailable",
                    expected_lease_expires_at=expected_lease,
                    now=self.now,
                )
            )

        set_lock_timeout.assert_called_once_with()

    def test_recovery_deferral_is_not_counted_as_a_lease_renewal(self) -> None:
        expected_lease = TemporalSchedulerClaim.objects.get(id=self.reservation.claim_id).lease_expires_at
        assert expected_lease is not None
        metrics = SchedulerMetrics(registry=(registry := CollectorRegistry()))

        self.assertTrue(
            defer_scheduler_claim_recovery(
                self.reservation.claim_id,
                self.reservation.claim_token,
                lease_duration=timedelta(minutes=5),
                error="Temporal status unavailable",
                expected_lease_expires_at=expected_lease,
                now=self.now,
                metrics=metrics,
            )
        )

        labels = {"scheduler": SCHEDULER, "region": REGION}
        transition_total = "posthog_temporal_scheduler_claim_transition_total"
        self.assertEqual(registry.get_sample_value(transition_total, {**labels, "transition": "recovery_deferred"}), 1)
        self.assertIsNone(registry.get_sample_value(transition_total, {**labels, "transition": "renewed"}))

    def test_recovery_can_confirm_an_expired_reserved_claim(self) -> None:
        recovery_time = self.now + timedelta(minutes=6)

        expired = list_expired_scheduler_claims(
            scheduler=SCHEDULER,
            region=REGION,
            limit=1,
            now=recovery_time,
        )

        self.assertEqual([claim.status for claim in expired], [TemporalSchedulerClaim.Status.RESERVED])
        self.assertTrue(
            confirm_scheduler_claim(
                self.reservation.claim_id,
                self.reservation.claim_token,
                lease_duration=timedelta(minutes=15),
                now=recovery_time,
            )
        )

        claim = TemporalSchedulerClaim.objects.get(id=self.reservation.claim_id)
        self.assertEqual(claim.claim_token, self.reservation.claim_token)
        self.assertEqual(claim.status, TemporalSchedulerClaim.Status.CONFIRMED)
        self.assertEqual(self._global_in_flight(), 1)

    def test_prune_removes_only_old_inactive_claims(self) -> None:
        self.assertTrue(
            confirm_scheduler_claim(
                self.reservation.claim_id,
                self.reservation.claim_token,
                lease_duration=timedelta(minutes=5),
                now=self.now,
            )
        )
        self.assertTrue(complete_scheduler_claim(self.reservation.claim_id, self.reservation.claim_token, now=self.now))
        available = reserve_scheduler_claims(
            scheduler=SCHEDULER,
            region=REGION,
            requests=[_request("team:1", "available")],
            limits=_limits(),
            now=self.now,
        ).reservations[0]
        self.assertTrue(release_scheduler_claim(available.claim_id, available.claim_token, now=self.now))
        quarantined = reserve_scheduler_claims(
            scheduler=SCHEDULER,
            region=REGION,
            requests=[_request("team:1", "quarantined")],
            limits=_limits(),
            now=self.now,
        ).reservations[0]
        self.assertTrue(
            quarantine_scheduler_claim(quarantined.claim_id, quarantined.claim_token, error="poison", now=self.now)
        )
        recent = reserve_scheduler_claims(
            scheduler=SCHEDULER,
            region=REGION,
            requests=[_request("team:1", "recent")],
            limits=_limits(),
            now=self.now,
        ).reservations[0]
        self.assertTrue(
            confirm_scheduler_claim(
                recent.claim_id,
                recent.claim_token,
                lease_duration=timedelta(minutes=5),
                now=self.now,
            )
        )
        self.assertTrue(complete_scheduler_claim(recent.claim_id, recent.claim_token, now=self.now))
        old = self.now - timedelta(days=30)
        TemporalSchedulerClaim.objects.filter(
            id__in=[self.reservation.claim_id, available.claim_id, quarantined.claim_id]
        ).update(updated_at=old)

        deleted = prune_inactive_scheduler_claims(
            scheduler=SCHEDULER,
            region=REGION,
            completed_before=self.now - timedelta(days=7),
            available_before=self.now - timedelta(days=7),
            limit=10,
        )

        self.assertEqual(deleted, 2)
        self.assertEqual(
            set(TemporalSchedulerClaim.objects.values_list("id", flat=True)),
            {quarantined.claim_id, recent.claim_id},
        )


class TestSchedulerAdmissionValidation(SimpleTestCase):
    def test_rejects_naive_datetimes_before_accessing_the_database(self) -> None:
        naive_now = datetime(2026, 9, 10, 12, 0)

        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            reserve_scheduler_claims(
                scheduler=SCHEDULER,
                region=REGION,
                requests=[_request("team:1", "one")],
                limits=_limits(),
                now=naive_now,
            )


class TestSchedulerAdmissionConcurrency(TransactionTestCase):
    reset_sequences = True

    def test_two_reservers_cannot_claim_same_occurrence(self) -> None:
        barrier = Barrier(2)

        def reserve() -> tuple[int, int]:
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                result = reserve_scheduler_claims(
                    scheduler=SCHEDULER,
                    region=REGION,
                    requests=[_request("team:1", "one")],
                    limits=_limits(global_limit=1, tenant_limit=1),
                )
                return len(result.reservations), result.already_claimed
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: reserve(), range(2)))

        self.assertEqual(sorted(results), [(0, 1), (1, 0)])
        self.assertEqual(TemporalSchedulerClaim.objects.count(), 1)
        self.assertEqual(
            TemporalSchedulerPermitPool.objects.get(scheduler=SCHEDULER, region=REGION, tenant_key="").in_flight,
            1,
        )

    def test_racing_terminal_transitions_release_permits_once(self) -> None:
        reservation = reserve_scheduler_claims(
            scheduler=SCHEDULER,
            region=REGION,
            requests=[_request("team:1", "one")],
            limits=_limits(global_limit=1, tenant_limit=1),
        ).reservations[0]
        self.assertTrue(
            confirm_scheduler_claim(
                reservation.claim_id,
                reservation.claim_token,
                lease_duration=timedelta(minutes=5),
            )
        )
        barrier = Barrier(2)

        def finish(transition: str) -> bool:
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                if transition == "complete":
                    return complete_scheduler_claim(reservation.claim_id, reservation.claim_token)
                return release_scheduler_claim(reservation.claim_id, reservation.claim_token)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(finish, ["complete", "release"]))

        self.assertEqual(sorted(results), [False, True])
        claim = TemporalSchedulerClaim.objects.get(id=reservation.claim_id)
        self.assertIn(claim.status, [TemporalSchedulerClaim.Status.COMPLETED, TemporalSchedulerClaim.Status.AVAILABLE])
        self.assertEqual(
            TemporalSchedulerPermitPool.objects.get(scheduler=SCHEDULER, region=REGION, tenant_key="").in_flight,
            0,
        )
        self.assertEqual(
            TemporalSchedulerPermitPool.objects.get(scheduler=SCHEDULER, region=REGION, tenant_key="team:1").in_flight,
            0,
        )
