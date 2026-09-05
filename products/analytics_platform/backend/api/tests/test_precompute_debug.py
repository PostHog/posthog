from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from products.analytics_platform.backend.api.precompute_debug import _fetch_samples_from_query_log
from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob

_MODULE = "products.analytics_platform.backend.api.precompute_debug"


def _make_job(
    team,
    *,
    query_hash,
    days_ago_start,
    status=PreaggregationJob.Status.READY,
    ttl_hours=6,
    created_days_ago=None,
):
    now = timezone.now()
    start = now - timedelta(days=days_ago_start)
    job = PreaggregationJob.objects.create(
        team=team,
        time_range_start=start,
        time_range_end=start + timedelta(days=1),
        query_hash=query_hash,
        status=status,
        computed_at=now - timedelta(hours=1),
        expires_at=now + timedelta(hours=ttl_hours),
    )
    if created_days_ago is not None:
        # created_at is auto_now_add; backdate it directly for lookback tests.
        PreaggregationJob.objects.filter(id=job.id).update(created_at=now - timedelta(days=created_days_ago))
    return job


@patch(f"{_MODULE}.is_cloud", return_value=True)
class TestPrecomputeDebugAPI(APIBaseTest):
    def _state_url(self) -> str:
        return f"/api/projects/{self.team.pk}/precompute_debug/state/"

    def _invalidate_url(self) -> str:
        return f"/api/projects/{self.team.pk}/precompute_debug/invalidate/"

    @parameterized.expand(
        [
            # Cloud + non-staff must be refused on both actions: state exposes
            # internal precompute state, invalidate mutates it.
            ("state_non_staff_forbidden", "get", "state", False, 403),
            ("state_staff_allowed", "get", "state", True, 200),
            ("invalidate_non_staff_forbidden", "post", "invalidate", False, 403),
            ("invalidate_staff_allowed", "post", "invalidate", True, 200),
        ]
    )
    @patch(f"{_MODULE}._fetch_samples_from_query_log", return_value={})
    def test_staff_gate(self, _name, method, endpoint, is_staff, expected_status, _samples, _is_cloud):
        self.user.is_staff = is_staff
        self.user.save()
        url = self._state_url() if endpoint == "state" else self._invalidate_url()
        response = getattr(self.client, method)(url)
        assert response.status_code == expected_status

    @patch(f"{_MODULE}._fetch_samples_from_query_log", return_value={})
    def test_groups_buckets_by_hash_with_ttl(self, _samples, _is_cloud):
        self.user.is_staff = True
        self.user.save()
        _make_job(self.team, query_hash="a" * 64, days_ago_start=1)
        _make_job(self.team, query_hash="a" * 64, days_ago_start=2, status=PreaggregationJob.Status.PENDING)
        # Expired bucket: negative TTL remaining must be reported, not hidden.
        _make_job(self.team, query_hash="b" * 64, days_ago_start=1, ttl_hours=-2)

        response = self.client.get(self._state_url())
        assert response.status_code == 200
        data = response.json()
        assert data["total_hashes"] == 2
        groups = {g["query_hash"]: g for g in data["groups"]}
        assert groups["a" * 64]["job_count"] == 2
        assert groups["a" * 64]["status_counts"] == {"ready": 1, "pending": 1}
        assert groups["b" * 64]["buckets"][0]["ttl_seconds_remaining"] < 0

    @patch(f"{_MODULE}._fetch_samples_from_query_log", return_value={})
    def test_unexpired_old_jobs_still_shown(self, _samples, _is_cloud):
        # Long-TTL stores (e.g. 90-day dimensional buckets) must not silently
        # drop out of the view just because the job row is older than the
        # recent-history lookback.
        self.user.is_staff = True
        self.user.save()
        _make_job(self.team, query_hash="a" * 64, days_ago_start=60, ttl_hours=24 * 30, created_days_ago=60)
        # An expired job that old is legitimately dropped.
        _make_job(self.team, query_hash="b" * 64, days_ago_start=60, ttl_hours=-24, created_days_ago=60)

        response = self.client.get(self._state_url())
        assert response.status_code == 200
        assert [g["query_hash"] for g in response.json()["groups"]] == ["a" * 64]

    @patch(f"{_MODULE}._fetch_samples_from_query_log", return_value={})
    def test_scoped_to_team(self, _samples, _is_cloud):
        # Another team's jobs must never appear — this is per-team debug state.
        self.user.is_staff = True
        self.user.save()
        other_team = self.organization.teams.create(name="other")
        _make_job(other_team, query_hash="c" * 64, days_ago_start=1)

        response = self.client.get(self._state_url())
        assert response.status_code == 200
        assert response.json()["total_hashes"] == 0

    @parameterized.expand(
        [
            # All hashes: both READY jobs flip, PENDING and other-team stay.
            ("all_hashes", None, 2, {"a" * 64: "stale", "b" * 64: "stale"}),
            # Single hash: only that hash's READY job flips.
            ("single_hash", "a" * 64, 1, {"a" * 64: "stale", "b" * 64: "ready"}),
        ]
    )
    # With expand + a class-level patch and no method-level patch, parameterized
    # injects the class mock before the expand args.
    def test_invalidate_marks_ready_jobs_stale(self, _is_cloud, _name, query_hash, expected_count, expected_statuses):
        self.user.is_staff = True
        self.user.save()
        _make_job(self.team, query_hash="a" * 64, days_ago_start=1)
        _make_job(self.team, query_hash="b" * 64, days_ago_start=1)
        pending = _make_job(self.team, query_hash="a" * 64, days_ago_start=2, status=PreaggregationJob.Status.PENDING)
        other_team = self.organization.teams.create(name="other")
        other_job = _make_job(other_team, query_hash="a" * 64, days_ago_start=1)

        body = {"query_hash": query_hash} if query_hash else {}
        response = self.client.post(self._invalidate_url(), body)
        assert response.status_code == 200
        assert response.json()["updated_count"] == expected_count

        for expected_hash, expected_status in expected_statuses.items():
            job = PreaggregationJob.objects.get(team=self.team, query_hash=expected_hash, status__in=["ready", "stale"])
            assert job.status == expected_status, expected_hash
        # In-flight and cross-team jobs must never be touched.
        pending.refresh_from_db()
        assert pending.status == PreaggregationJob.Status.PENDING
        other_job.refresh_from_db()
        assert other_job.status == PreaggregationJob.Status.READY

    def test_sample_index_mapping(self, _is_cloud):
        # multiSearchFirstIndex is 1-based: row idx=2 must map to the SECOND hash,
        # and out-of-range indexes must be dropped, not crash or mislabel.
        now = timezone.now()
        with patch(
            f"{_MODULE}.sync_execute",
            return_value=[
                (2, "web_stats_lazy_insert", "webAnalyticsEagerBaselineWarming", '{"kind":"WebStatsTableQuery"}', now),
                (99, "bogus", "", "{}", now),
            ],
        ):
            samples = _fetch_samples_from_query_log(self.team.pk, {"hash_one": "id1", "hash_two": "id2"})
        assert set(samples.keys()) == {"hash_two"}
        assert samples["hash_two"]["query_type"] == "web_stats_lazy_insert"
