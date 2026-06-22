import datetime

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import PropertyMock, patch

from django.db import OperationalError

from products.dashboards.backend.models.dashboard import Dashboard


class TestDashboardModel(BaseTest):
    def test_touch_last_accessed_at_sets_timestamp_when_unset(self):
        dashboard = Dashboard.objects.create(team=self.team, name="example")
        assert dashboard.last_accessed_at is None

        with freeze_time("2022-01-01T12:00:00Z"):
            dashboard.touch_last_accessed_at()

        dashboard.refresh_from_db()
        assert dashboard.last_accessed_at == datetime.datetime(2022, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)

    def test_touch_last_accessed_at_is_debounced(self):
        with freeze_time("2022-01-01T12:00:00Z") as frozen:
            dashboard = Dashboard.objects.create(team=self.team, name="example")
            dashboard.touch_last_accessed_at()

            # A read shortly after does not issue another write.
            frozen.tick(datetime.timedelta(minutes=5))
            with patch.object(Dashboard, "save") as mock_save:
                dashboard.touch_last_accessed_at()
            mock_save.assert_not_called()

            # Once the debounce interval has passed, the write happens again.
            frozen.tick(datetime.timedelta(minutes=10))
            dashboard.touch_last_accessed_at()

        dashboard.refresh_from_db()
        assert dashboard.last_accessed_at == datetime.datetime(2022, 1, 1, 12, 15, 0, tzinfo=datetime.UTC)

    def test_touch_last_accessed_at_swallows_database_errors(self):
        dashboard = Dashboard.objects.create(team=self.team, name="example")

        with patch.object(Dashboard, "save", side_effect=OperationalError("query_wait_timeout")):
            # Must not raise — the read path that calls this should never fail because of it.
            dashboard.touch_last_accessed_at()

    def test_partial_update_does_not_dereference_team(self):
        dashboard = Dashboard.objects.create(team=self.team, name="example")

        # Saving only `last_accessed_at` must not dereference the `team` FK on the critical
        # path: that load can block on a saturated connection pool and fail the request.
        # We simulate the pool timeout by making `team` access raise, then assert the partial
        # save still succeeds (the only remaining team access lives in a best-effort signal).
        fresh = Dashboard.objects.get(pk=dashboard.pk)
        with patch.object(Dashboard, "team", new_callable=PropertyMock) as mock_team:
            mock_team.side_effect = OperationalError("query_wait_timeout")
            fresh.last_accessed_at = datetime.datetime(2022, 1, 1, tzinfo=datetime.UTC)
            fresh.save(update_fields=["last_accessed_at"])

        fresh.refresh_from_db()
        assert fresh.last_accessed_at == datetime.datetime(2022, 1, 1, tzinfo=datetime.UTC)
