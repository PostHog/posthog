from unittest.mock import patch

from django.db import InterfaceError, OperationalError
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.exceptions import DatabaseTemporarilyUnavailable
from posthog.models.team.team import Team


class TestTeamManagerTransientDbErrors(SimpleTestCase):
    databases: set = set()

    def setUp(self) -> None:
        super().setUp()
        cache_patcher = patch("posthog.models.team.team.get_team_in_cache", return_value=None)
        self.addCleanup(cache_patcher.stop)
        cache_patcher.start()
        set_cache_patcher = patch("posthog.models.team.team.set_team_in_cache")
        self.addCleanup(set_cache_patcher.stop)
        set_cache_patcher.start()

    @parameterized.expand(
        [
            ("query_wait_timeout", OperationalError("canceling statement due to query_wait_timeout")),
            (
                "shutdown_during_connect",
                OperationalError("connection failed: FATAL: the database system is shutting down"),
            ),
            ("connection_dropped", InterfaceError("connection already closed")),
        ]
    )
    def test_get_team_from_cache_or_token_raises_retryable_on_transient_error(
        self, _name: str, error: Exception
    ) -> None:
        with patch.object(Team.objects, "get", side_effect=error):
            with self.assertRaises(DatabaseTemporarilyUnavailable):
                Team.objects.get_team_from_cache_or_token("phc_some_token")

    def test_get_team_from_cache_or_token_does_not_mask_non_transient_error(self) -> None:
        error = OperationalError('column "nonexistent" does not exist')
        with patch.object(Team.objects, "get", side_effect=error):
            with self.assertRaises(OperationalError):
                Team.objects.get_team_from_cache_or_token("phc_some_token")

    def test_get_team_from_cache_or_secret_api_token_raises_retryable_on_transient_error(self) -> None:
        error = OperationalError("connection failed: FATAL: the database system is shutting down")
        with patch.object(Team.objects, "get", side_effect=error):
            with self.assertRaises(DatabaseTemporarilyUnavailable):
                Team.objects.get_team_from_cache_or_secret_api_token("phs_some_token")

    def test_get_team_from_cache_or_secret_api_token_does_not_mask_non_transient_error(self) -> None:
        error = OperationalError('column "nonexistent" does not exist')
        with patch.object(Team.objects, "get", side_effect=error):
            with self.assertRaises(OperationalError):
                Team.objects.get_team_from_cache_or_secret_api_token("phs_some_token")
