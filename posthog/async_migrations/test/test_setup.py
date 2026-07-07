from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.db import OperationalError
from django.test import SimpleTestCase, override_settings

from posthog.async_migrations.setup import setup_async_migrations_with_retry


@override_settings(ASYNC_MIGRATIONS_SETUP_MAX_ATTEMPTS=3, ASYNC_MIGRATIONS_SETUP_RETRY_BASE_DELAY_SECONDS=0.01)
class TestSetupAsyncMigrationsWithRetry(SimpleTestCase):
    def test_returns_immediately_on_success_without_sleeping(self):
        with (
            patch("posthog.async_migrations.setup.setup_async_migrations") as mock_setup,
            patch("posthog.async_migrations.setup.time.sleep") as mock_sleep,
        ):
            result = setup_async_migrations_with_retry()

        assert result is True
        mock_setup.assert_called_once_with(ignore_posthog_version=False)
        mock_sleep.assert_not_called()

    def test_recovers_when_db_becomes_available_mid_retry(self):
        with (
            patch(
                "posthog.async_migrations.setup.setup_async_migrations",
                side_effect=[OperationalError("could not translate host name"), None],
            ) as mock_setup,
            patch("posthog.async_migrations.setup.time.sleep") as mock_sleep,
        ):
            result = setup_async_migrations_with_retry()

        assert result is True
        assert mock_setup.call_count == 2
        mock_sleep.assert_called_once()

    def test_logs_and_continues_when_db_stays_unavailable(self):
        # The core regression: a persistently unreachable DB at boot must not raise
        # (which would crash-loop the worker and flood error tracking).
        with (
            patch(
                "posthog.async_migrations.setup.setup_async_migrations",
                side_effect=OperationalError("the database system is in recovery mode"),
            ) as mock_setup,
            patch("posthog.async_migrations.setup.time.sleep") as mock_sleep,
        ):
            result = setup_async_migrations_with_retry()

        assert result is False
        assert mock_setup.call_count == 3
        # Sleeps between attempts, but not after the final failed attempt.
        assert mock_sleep.call_count == 2

    def test_does_not_swallow_non_connectivity_errors(self):
        # A genuinely missing required migration must still fail fast, not be retried away.
        with (
            patch(
                "posthog.async_migrations.setup.setup_async_migrations",
                side_effect=ImproperlyConfigured("required migration missing"),
            ) as mock_setup,
            patch("posthog.async_migrations.setup.time.sleep") as mock_sleep,
        ):
            with self.assertRaises(ImproperlyConfigured):
                setup_async_migrations_with_retry()

        mock_setup.assert_called_once()
        mock_sleep.assert_not_called()
