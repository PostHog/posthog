from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from prometheus_client import CollectorRegistry

from posthog.tasks.tasks import export_lazy_computation_job_stats

from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob


def _gauge(registry: CollectorRegistry, name: str, labels: dict | None = None) -> float | None:
    """Pull a single sample value out of a prometheus CollectorRegistry."""
    return registry.get_sample_value(name, labels or {})


class TestExportLazyComputationJobStats(APIBaseTest):
    """The exporter task samples `PreaggregationJob.status` counts and the
    head-of-queue age into a Prometheus pushed registry every 30s in prod.
    Tests cover correctness of the counts, zero-init behavior, and the
    head-of-queue age formula — they're the load-bearing signals on the
    queue-health dashboard's backlog panel."""

    def _make_job(self, status: str, created_at=None) -> PreaggregationJob:
        job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="x" * 64,
            time_range_start=timezone.now() - timedelta(days=1),
            time_range_end=timezone.now(),
            status=status,
        )
        if created_at is not None:
            # `created_at` is auto_now_add; override via update() to bypass.
            PreaggregationJob.objects.filter(id=job.id).update(created_at=created_at)
            job.refresh_from_db()
        return job

    def _run_with_registry(self) -> CollectorRegistry:
        registry = CollectorRegistry()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=registry)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        with patch("posthog.tasks.tasks.pushed_metrics_registry", return_value=mock_ctx):
            export_lazy_computation_job_stats()
        return registry

    def test_all_statuses_published_even_when_empty(self) -> None:
        """A status with zero rows still publishes a 0 — alerting on `== 0`
        needs the series to exist, not vanish."""
        registry = self._run_with_registry()

        for status_value in PreaggregationJob.Status.values:
            assert _gauge(registry, "lazy_computation_jobs", {"status": status_value}) == 0.0

    def test_counts_per_status(self) -> None:
        self._make_job(PreaggregationJob.Status.PENDING)
        self._make_job(PreaggregationJob.Status.PENDING)
        self._make_job(PreaggregationJob.Status.READY)
        self._make_job(PreaggregationJob.Status.FAILED)

        registry = self._run_with_registry()

        assert _gauge(registry, "lazy_computation_jobs", {"status": "pending"}) == 2.0
        assert _gauge(registry, "lazy_computation_jobs", {"status": "ready"}) == 1.0
        assert _gauge(registry, "lazy_computation_jobs", {"status": "failed"}) == 1.0
        assert _gauge(registry, "lazy_computation_jobs", {"status": "stale"}) == 0.0

    def test_oldest_pending_age_reflects_min_created_at(self) -> None:
        now = timezone.now()
        self._make_job(PreaggregationJob.Status.PENDING, created_at=now - timedelta(seconds=120))
        self._make_job(PreaggregationJob.Status.PENDING, created_at=now - timedelta(seconds=30))
        # READY rows must not influence the PENDING head-of-queue age.
        self._make_job(PreaggregationJob.Status.READY, created_at=now - timedelta(seconds=600))

        registry = self._run_with_registry()
        age = _gauge(registry, "lazy_computation_oldest_pending_age_seconds")
        assert age is not None
        # Wall-clock jitter is fine; assert within a 30 s envelope around the seeded value.
        assert 110 <= age <= 150

    def test_oldest_pending_age_zero_when_no_pending(self) -> None:
        self._make_job(PreaggregationJob.Status.READY)

        registry = self._run_with_registry()

        assert _gauge(registry, "lazy_computation_oldest_pending_age_seconds") == 0.0

    def test_failure_does_not_raise(self) -> None:
        """Best-effort: a DB error inside the task body must not propagate —
        the worker should keep serving other jobs."""
        with patch(
            "posthog.tasks.tasks.pushed_metrics_registry",
            side_effect=RuntimeError("metric backend down"),
        ):
            # Should swallow the exception.
            export_lazy_computation_job_stats()
