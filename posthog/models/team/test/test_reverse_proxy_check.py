from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.team import Team
from posthog.models.team.reverse_proxy_check import (
    HAS_REVERSE_PROXY_CACHE_TTL_SECONDS,
    NO_REVERSE_PROXY_CACHE_TTL_SECONDS,
    get_has_reverse_proxy,
)

TEAM_ID = 4242


def _query_response(rows: list[list[str | None]]) -> MagicMock:
    return MagicMock(results=rows)


class TestGetHasReverseProxy(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()
        patcher = patch("posthog.models.team.reverse_proxy_check.execute_hogql_query")
        self.mock_query = patcher.start()
        self.addCleanup(patcher.stop)

    @parameterized.expand(
        [
            ("proxy_seen", [["https://proxy.example.com"], [None]], True, HAS_REVERSE_PROXY_CACHE_TTL_SECONDS),
            ("no_custom_host", [[None], [""]], False, NO_REVERSE_PROXY_CACHE_TTL_SECONDS),
            ("no_events", [], False, NO_REVERSE_PROXY_CACHE_TTL_SECONDS),
        ]
    )
    def test_cache_miss_queries_once_then_answers_from_cache(
        self, _name: str, rows: list[list[str | None]], expected: bool, expected_ttl: int
    ) -> None:
        self.mock_query.return_value = _query_response(rows)
        team = Team(id=TEAM_ID)

        with patch("posthog.models.team.reverse_proxy_check.safe_cache_set", wraps=cache.set) as cache_set:
            assert get_has_reverse_proxy(team) is expected
        assert get_has_reverse_proxy(team) is expected

        self.mock_query.assert_called_once()
        assert cache_set.call_args.kwargs["timeout"] == expected_ttl

    def test_cache_hit_does_not_query(self) -> None:
        cache.set(f"team_has_reverse_proxy:{TEAM_ID}", False)

        assert get_has_reverse_proxy(Team(id=TEAM_ID)) is False
        self.mock_query.assert_not_called()

    def test_completed_setup_task_still_checks_events(self) -> None:
        self.mock_query.return_value = _query_response([])
        team = Team(id=TEAM_ID, onboarding_tasks={"set_up_reverse_proxy": "completed"})

        assert get_has_reverse_proxy(team) is False
        self.mock_query.assert_called_once()

    def test_failed_query_is_not_cached(self) -> None:
        self.mock_query.side_effect = [
            Exception("clickhouse unavailable"),
            _query_response([["https://proxy.example.com"]]),
        ]
        team = Team(id=TEAM_ID)

        with self.assertRaises(Exception):
            get_has_reverse_proxy(team)
        assert get_has_reverse_proxy(team) is True
