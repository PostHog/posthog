from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from posthog import views
from posthog.redis import get_client


class TestHealthMigrationsAlert(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        get_client().delete(views.MIGRATIONS_PENDING_SINCE_KEY, views.MIGRATIONS_PENDING_ALERTED_KEY)

    def _call_health(self, *, has_pending: bool):
        executor = MagicMock()
        executor.migration_plan.return_value = ["pending"] if has_pending else []
        with patch("posthog.views.MigrationExecutor", return_value=executor):
            return views.health(MagicMock())

    def test_transient_pending_migrations_does_not_capture(self) -> None:
        with (
            patch("posthog.views.time.time", return_value=1000),
            patch("posthog.views.capture_exception") as capture,
        ):
            response = self._call_health(has_pending=True)

        assert response.status_code == 503
        capture.assert_not_called()

    def test_sustained_pending_migrations_captures_once_per_window(self) -> None:
        window = int(views.MIGRATIONS_PENDING_ALERT_AFTER.total_seconds())

        with patch("posthog.views.capture_exception") as capture:
            with patch("posthog.views.time.time", return_value=1000):
                self._call_health(has_pending=True)
            capture.assert_not_called()

            # Once the condition has persisted past the alert window, we escalate exactly once.
            with patch("posthog.views.time.time", return_value=1000 + window + 1):
                self._call_health(has_pending=True)
            assert capture.call_count == 1

            # Further probes inside the same window stay quiet.
            with patch("posthog.views.time.time", return_value=1000 + window + 2):
                self._call_health(has_pending=True)
            assert capture.call_count == 1

    def test_resolved_migrations_clears_marker_and_resets_timer(self) -> None:
        window = int(views.MIGRATIONS_PENDING_ALERT_AFTER.total_seconds())

        with patch("posthog.views.capture_exception") as capture:
            with patch("posthog.views.time.time", return_value=1000):
                self._call_health(has_pending=True)

            # Migrations catch up: the 200 path clears the pending marker.
            with patch("posthog.views.time.time", return_value=1000 + 60):
                response = self._call_health(has_pending=False)
            assert response.status_code == 200

            # A later pending state starts a fresh timer, so it stays quiet again.
            with patch("posthog.views.time.time", return_value=1000 + window + 120):
                self._call_health(has_pending=True)
            capture.assert_not_called()
