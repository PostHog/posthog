from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest

from products.dashboards.backend.access import (
    DASHBOARD_CACHE_OUTCOME_COUNTER,
    DashboardAccessMethod,
    record_dashboard_access,
    record_dashboard_cache_outcome,
)
from products.dashboards.backend.models.dashboard import Dashboard


class TestDashboardAccess(BaseTest):
    def test_records_access_methods_without_overwriting_other_sources(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team)
        first_access = datetime(2026, 7, 16, 10, tzinfo=UTC)
        second_access = first_access + timedelta(minutes=5)

        record_dashboard_access(dashboard, DashboardAccessMethod.HUMAN, accessed_at=first_access)
        record_dashboard_access(dashboard, DashboardAccessMethod.HUMAN, accessed_at=second_access)
        record_dashboard_access(dashboard, DashboardAccessMethod.EMBEDDED, accessed_at=second_access)

        dashboard.refresh_from_db()
        assert dashboard.last_accessed_at == second_access
        assert dashboard.most_recent_access == {
            "human": {"timestamp": second_access.isoformat(), "count": 2},
            "embedded": {"timestamp": second_access.isoformat(), "count": 1},
        }

    def test_records_cache_misses_without_counting_them_as_accesses(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team)
        accessed_at = datetime(2026, 7, 16, 10, tzinfo=UTC)
        miss_counter = DASHBOARD_CACHE_OUTCOME_COUNTER.labels(access_method="api", result="miss")
        hit_counter = DASHBOARD_CACHE_OUTCOME_COUNTER.labels(access_method="api", result="hit")
        miss_count_before = miss_counter._value.get()
        hit_count_before = hit_counter._value.get()

        record_dashboard_access(dashboard, DashboardAccessMethod.API, accessed_at=accessed_at)
        record_dashboard_cache_outcome(
            dashboard,
            DashboardAccessMethod.API,
            is_cached=False,
            observed_at=accessed_at + timedelta(minutes=1),
        )
        record_dashboard_cache_outcome(
            dashboard,
            DashboardAccessMethod.API,
            is_cached=False,
            persist_miss=False,
            observed_at=accessed_at + timedelta(minutes=2),
        )
        record_dashboard_cache_outcome(
            dashboard,
            DashboardAccessMethod.API,
            is_cached=True,
            observed_at=accessed_at + timedelta(minutes=3),
        )

        dashboard.refresh_from_db()
        assert dashboard.most_recent_access == {
            "api": {
                "timestamp": accessed_at.isoformat(),
                "count": 1,
                "last_cache_miss_at": (accessed_at + timedelta(minutes=1)).isoformat(),
            }
        }
        assert miss_counter._value.get() == miss_count_before + 2
        assert hit_counter._value.get() == hit_count_before + 1

    def test_access_timestamps_do_not_move_backwards(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team)
        latest_access = datetime(2026, 7, 16, 10, tzinfo=UTC)

        record_dashboard_access(dashboard, DashboardAccessMethod.HUMAN, accessed_at=latest_access)
        record_dashboard_access(
            dashboard,
            DashboardAccessMethod.HUMAN,
            accessed_at=latest_access - timedelta(minutes=5),
        )

        dashboard.refresh_from_db()
        assert dashboard.last_accessed_at == latest_access
        assert dashboard.most_recent_access == {
            "human": {"timestamp": latest_access.isoformat(), "count": 2},
        }

    def test_cache_miss_timestamps_do_not_move_backwards(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team)
        latest_miss = datetime(2026, 7, 16, 10, tzinfo=UTC)

        record_dashboard_cache_outcome(
            dashboard,
            DashboardAccessMethod.API,
            is_cached=False,
            observed_at=latest_miss,
        )
        record_dashboard_cache_outcome(
            dashboard,
            DashboardAccessMethod.API,
            is_cached=False,
            observed_at=latest_miss - timedelta(minutes=5),
        )

        dashboard.refresh_from_db()
        assert dashboard.most_recent_access == {
            "api": {"last_cache_miss_at": latest_miss.isoformat()},
        }
