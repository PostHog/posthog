import uuid
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from posthog.models.temporal_scheduler import (
    TemporalSchedulerClaim,
    TemporalSchedulerPermitPool,
    TemporalSchedulerState,
)


class TestTemporalSchedulerPermitPool(TestCase):
    def test_empty_tenant_key_represents_global_pool(self) -> None:
        pool = TemporalSchedulerPermitPool.objects.create(scheduler="subscriptions", region="eu")

        self.assertEqual(pool.tenant_key, "")
        self.assertEqual(pool.in_flight, 0)

    def test_scope_is_unique(self) -> None:
        TemporalSchedulerPermitPool.objects.create(scheduler="subscriptions", region="eu", tenant_key="team:1")

        with self.assertRaises(IntegrityError), transaction.atomic():
            TemporalSchedulerPermitPool.objects.create(scheduler="subscriptions", region="eu", tenant_key="team:1")

        TemporalSchedulerPermitPool.objects.create(scheduler="subscriptions", region="us", tenant_key="team:1")

    def test_in_flight_cannot_be_negative(self) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            TemporalSchedulerPermitPool.objects.create(scheduler="subscriptions", region="eu", in_flight=-1)


class TestTemporalSchedulerState(TestCase):
    def test_scope_is_unique_and_cursor_defaults_empty(self) -> None:
        state = TemporalSchedulerState.objects.create(scheduler="subscriptions", region="eu")

        self.assertEqual(state.discovery_cursor, "")
        with self.assertRaises(IntegrityError), transaction.atomic():
            TemporalSchedulerState.objects.create(scheduler="subscriptions", region="eu")

        TemporalSchedulerState.objects.create(scheduler="subscriptions", region="us")


class TestTemporalSchedulerClaim(TestCase):
    def _claim(self, **overrides: object) -> TemporalSchedulerClaim:
        values: dict[str, object] = {
            "scheduler": "subscriptions",
            "region": "eu",
            "tenant_key": "team:1",
            "occurrence_hash": "a" * 64,
            "occurrence_key": "subscription:1:2026-09-10T10:00:00Z",
            "workflow_id": "process-subscription-1-2026-09-10T10:00:00Z",
            "source_due_at": timezone.now(),
            "claim_token": uuid.uuid4(),
            "status": TemporalSchedulerClaim.Status.RESERVED,
            "lease_expires_at": timezone.now() + timedelta(minutes=5),
        }
        values.update(overrides)
        return TemporalSchedulerClaim.objects.create(**values)

    def test_occurrence_is_unique_within_scheduler_and_region(self) -> None:
        self._claim()

        with self.assertRaises(IntegrityError), transaction.atomic():
            self._claim(occurrence_key="a different key with the same digest")

        self._claim(region="us")

    def test_active_claim_requires_lease(self) -> None:
        for status in [TemporalSchedulerClaim.Status.RESERVED, TemporalSchedulerClaim.Status.CONFIRMED]:
            with self.subTest(status=status), self.assertRaises(IntegrityError), transaction.atomic():
                self._claim(
                    occurrence_hash=("b" if status == TemporalSchedulerClaim.Status.RESERVED else "c") * 64,
                    status=status,
                    lease_expires_at=None,
                )

    def test_inactive_claim_cannot_retain_lease(self) -> None:
        for index, status in enumerate(
            [
                TemporalSchedulerClaim.Status.AVAILABLE,
                TemporalSchedulerClaim.Status.COMPLETED,
                TemporalSchedulerClaim.Status.QUARANTINED,
            ]
        ):
            with self.subTest(status=status), self.assertRaises(IntegrityError), transaction.atomic():
                self._claim(occurrence_hash=str(index) * 64, status=status)

    def test_completed_at_is_set_exactly_for_completed_claim(self) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._claim(
                occurrence_hash="d" * 64,
                status=TemporalSchedulerClaim.Status.COMPLETED,
                lease_expires_at=None,
            )

        with self.assertRaises(IntegrityError), transaction.atomic():
            self._claim(occurrence_hash="e" * 64, completed_at=timezone.now())

        completed = self._claim(
            occurrence_hash="f" * 64,
            status=TemporalSchedulerClaim.Status.COMPLETED,
            lease_expires_at=None,
            completed_at=timezone.now(),
        )
        self.assertIsNotNone(completed.completed_at)
