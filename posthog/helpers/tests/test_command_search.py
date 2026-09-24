from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized

from posthog.egress.typesafe.client import ChoiceAnswer, SystemOneResult, TypeSafeRequestFailed
from posthog.egress.typesafe.transport import TypeSafeEgressBudgetExhausted
from posthog.helpers.command_search import CommandSearch, SearchCandidate


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class TestCommandSearchRanking(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()
        self.candidates: list[SearchCandidate] = [
            {
                "id": "a",
                "name": "Checkout funnel",
                "description": "insight",
                "href": "/insights/a",
                "type": "insight",
                "command_id": "",
            },
            {
                "id": "b",
                "name": "Session replay",
                "description": "watch recordings",
                "href": "",
                "type": "command",
                "command_id": "replay",
            },
        ]
        self.lease = patch("posthog.helpers.command_search.get_client").start()
        self.addCleanup(patch.stopall)

    @patch("posthog.helpers.command_search.system_one")
    def test_rank_cache_is_scoped_to_user_team_query_and_candidates(self, infer: MagicMock) -> None:
        infer.return_value = SystemOneResult(
            model="jev-1.13.0",
            answers={
                "match": ChoiceAnswer(choice="1", confidence=0.8, probabilities={"0": 0.2, "1": 0.7, "none": 0.1})
            },
            input_tokens=100,
        )
        for _ in range(2):
            result = CommandSearch.rank("checkout", self.candidates, team_id=1, user_id=1)
            self.assertEqual([item["id"] for item in result], ["b", "a"])
        self.assertEqual(infer.call_count, 1)
        CommandSearch.rank("checkout", self.candidates, team_id=2, user_id=1)
        CommandSearch.rank("checkout", self.candidates, team_id=1, user_id=2)
        CommandSearch.rank("checkout", self.candidates[:1], team_id=1, user_id=1)
        self.assertEqual(infer.call_count, 4)
        self.lease.return_value.lock.return_value.release.assert_called()

    @parameterized.expand(
        [
            (requests.Timeout(),),
            (TypeSafeRequestFailed("rate limited", status_code=429),),
            (TypeSafeRequestFailed("overloaded", status_code=529),),
            (TypeSafeEgressBudgetExhausted("budget", scope="default"),),
        ]
    )
    @patch("posthog.helpers.command_search.system_one")
    def test_provider_failure_returns_text_matches_and_suppresses_more_calls(
        self, error: Exception, infer: MagicMock
    ) -> None:
        infer.side_effect = error
        result = CommandSearch.rank("checkout", self.candidates, team_id=1, user_id=1)
        self.assertEqual([item["id"] for item in result], ["a"])
        CommandSearch.rank("watch", self.candidates, team_id=1, user_id=2)
        infer.assert_called_once()

    @patch("posthog.helpers.command_search.system_one")
    def test_overlapping_requests_skip_inference(self, infer: MagicMock) -> None:
        self.lease.return_value.lock.return_value.acquire.return_value = False
        result = CommandSearch.rank("checkout", self.candidates, team_id=1, user_id=1)
        self.assertEqual([item["id"] for item in result], ["a"])
        infer.assert_not_called()

    @patch("posthog.helpers.command_search.system_one")
    @patch("posthog.helpers.command_search.cache.get", side_effect=ConnectionError)
    def test_cache_outage_does_not_bypass_budgets(self, cache_get: MagicMock, infer: MagicMock) -> None:
        self.assertEqual(CommandSearch.rank("checkout", self.candidates, team_id=1, user_id=1), self.candidates[:1])
        infer.assert_not_called()

    @patch("posthog.helpers.command_search.system_one")
    @patch("posthog.helpers.command_search.cache.incr", return_value=121)
    def test_per_user_budget_exhaustion_returns_text_matches(self, increment: MagicMock, infer: MagicMock) -> None:
        self.assertEqual(CommandSearch.rank("checkout", self.candidates, team_id=1, user_id=1), self.candidates[:1])
        infer.assert_not_called()
        self.lease.return_value.lock.return_value.release.assert_called_once()

    @patch("posthog.helpers.command_search.system_one")
    def test_oversized_state_uses_text_matches_without_consuming_provider_budget(self, infer: MagicMock) -> None:
        self.candidates = [{**self.candidates[0], "id": str(index), "description": "x" * 400} for index in range(254)]
        self.assertEqual(CommandSearch.rank("checkout", self.candidates, team_id=1, user_id=1), self.candidates[:30])
        infer.assert_not_called()
        self.lease.assert_not_called()
