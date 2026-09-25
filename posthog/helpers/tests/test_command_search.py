from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

import httpx
from parameterized import parameterized

from posthog.helpers.command_search import COMMAND_SEARCH_MODEL, CommandSearch, SearchCandidate, _transport


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    AI_GATEWAY_URL="https://gateway.example.com/v1/",
    AI_GATEWAY_API_KEY="test-only-gateway-key",
)
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

    @parameterized.expand([(True,), (False,)])
    @patch("posthog.helpers.command_search._transport.session.post")
    def test_rank_cache_is_scoped_to_user_team_query_and_candidates(self, typed: bool, infer: MagicMock) -> None:
        infer.return_value.status_code = 200
        infer.return_value.json.return_value = {
            "model": "jevk5-fp8-0.2",
            "answers": {
                "match": {
                    **({"type": "choice"} if typed else {}),
                    "choice": "1",
                    "confidence": 0.7,
                    "probabilities": {"0": 0.2, "1": 0.7, "none": 0.1},
                }
            },
        }
        for _ in range(2):
            result = CommandSearch.rank("checkout", self.candidates, team_id=1, user_id=1)
            self.assertEqual([item["id"] for item in result], ["b", "a"])
        self.assertEqual(infer.call_count, 1)
        args, kwargs = infer.call_args
        self.assertEqual(args, ("https://gateway.example.com/v1/systemone",))
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-only-gateway-key")
        self.assertEqual(kwargs["headers"]["X-PostHog-Product"], "command_search")
        self.assertEqual(kwargs["headers"]["X-PostHog-Distinct-Id"], "team-1")
        self.assertEqual(_transport.session.timeout, httpx.Timeout(0.8, connect=0.3))
        self.assertFalse(_transport.session.trust_env)
        self.assertFalse(_transport.session.is_closed)
        self.assertFalse(kwargs["follow_redirects"])
        self.assertEqual(kwargs["json"]["model"], COMMAND_SEARCH_MODEL)
        self.assertEqual(kwargs["json"]["state"]["query"], "checkout")
        self.assertEqual(
            kwargs["json"]["state"]["candidates"],
            {
                str(index): {"name": item["name"], "description": item["description"]}
                for index, item in enumerate(self.candidates)
            },
        )
        self.assertEqual(
            kwargs["json"]["questions"]["match"]["criteria"], {"0": None, "1": None, "none": "No relevant result"}
        )
        CommandSearch.rank("checkout", self.candidates, team_id=2, user_id=1)
        CommandSearch.rank("checkout", self.candidates, team_id=1, user_id=2)
        CommandSearch.rank("checkout", self.candidates[:1], team_id=1, user_id=1)
        self.assertEqual(infer.call_count, 4)
        self.lease.return_value.lock.return_value.release.assert_called()

    @parameterized.expand(
        [
            (httpx.ReadTimeout("test timeout"),),
            (httpx.ConnectError("test connection error"),),
            (ValueError("Invalid JSON"),),
        ]
    )
    @patch("posthog.helpers.command_search._transport.session.post")
    def test_provider_failure_returns_text_matches_and_suppresses_more_calls(
        self, error: Exception, infer: MagicMock
    ) -> None:
        infer.side_effect = error
        result = CommandSearch.rank("checkout", self.candidates, team_id=1, user_id=1)
        self.assertEqual([item["id"] for item in result], ["a"])
        CommandSearch.rank("watch", self.candidates, team_id=1, user_id=2)
        infer.assert_called_once()

    @parameterized.expand(
        [
            (429, {}),
            (503, {}),
            (302, {}),
            (200, {}),
            *[
                (
                    200,
                    {
                        "model": COMMAND_SEARCH_MODEL,
                        "answers": {"match": {"choice": "0", "confidence": 0.7, "probabilities": probabilities}},
                    },
                )
                for probabilities in [
                    {"0": 0.9},
                    *[{"0": score, "1": 0.2, "none": 0.1} for score in [True, "0.7", -0.1, float("nan"), float("inf")]],
                ]
            ],
        ]
    )
    @patch("posthog.helpers.command_search._transport.session.post")
    def test_unusable_response_falls_back_and_opens_cooldown(
        self, status: int, payload: object, infer: MagicMock
    ) -> None:
        infer.return_value.status_code = status
        infer.return_value.json.return_value = payload
        self.assertEqual(CommandSearch.rank("checkout", self.candidates, team_id=1, user_id=1), self.candidates[:1])
        CommandSearch.rank("watch", self.candidates, team_id=1, user_id=2)
        infer.assert_called_once()

    @parameterized.expand([("http://gateway.example.com/v1",), ("",)])
    @patch("posthog.llm.system_one_client.system_one")
    @patch("posthog.helpers.command_search._transport.session.post")
    @patch("posthog.helpers.command_search.posthoganalytics.feature_enabled", return_value=True)
    def test_unusable_gateway_never_sends_credentials_or_uses_typesafe(
        self, url: str, evaluate_flag: MagicMock, infer: MagicMock, typesafe: MagicMock
    ) -> None:
        with self.settings(AI_GATEWAY_URL=url, TYPESAFE_API_KEY="test-only-typesafe-key"):
            self.assertFalse(CommandSearch.enabled(MagicMock(), MagicMock()))
            self.assertEqual(CommandSearch.rank("checkout", self.candidates, team_id=1, user_id=1), self.candidates[:1])
        evaluate_flag.assert_not_called()
        infer.assert_not_called()
        typesafe.assert_not_called()

    @patch("posthog.helpers.command_search._transport.session.post")
    def test_overlapping_requests_skip_inference(self, infer: MagicMock) -> None:
        self.lease.return_value.lock.return_value.acquire.return_value = False
        result = CommandSearch.rank("checkout", self.candidates, team_id=1, user_id=1)
        self.assertEqual([item["id"] for item in result], ["a"])
        infer.assert_not_called()

    @patch("posthog.helpers.command_search._transport.session.post")
    @patch("posthog.helpers.command_search.cache.get", side_effect=ConnectionError)
    def test_cache_outage_does_not_bypass_budgets(self, cache_get: MagicMock, infer: MagicMock) -> None:
        self.assertEqual(CommandSearch.rank("checkout", self.candidates, team_id=1, user_id=1), self.candidates[:1])
        infer.assert_not_called()

    @patch("posthog.helpers.command_search._transport.session.post")
    @patch("posthog.helpers.command_search.cache.incr", return_value=121)
    def test_per_user_budget_exhaustion_returns_text_matches(self, increment: MagicMock, infer: MagicMock) -> None:
        self.assertEqual(CommandSearch.rank("checkout", self.candidates, team_id=1, user_id=1), self.candidates[:1])
        infer.assert_not_called()
        self.lease.return_value.lock.return_value.release.assert_called_once()

    @patch("posthog.helpers.command_search._transport.session.post")
    def test_oversized_state_uses_text_matches_without_consuming_provider_budget(self, infer: MagicMock) -> None:
        self.candidates = [{**self.candidates[0], "description": "x" * 60_000}]
        self.assertEqual(CommandSearch.rank("checkout", self.candidates, team_id=1, user_id=1), self.candidates)
        infer.assert_not_called()
        self.lease.assert_not_called()

    @patch("posthog.helpers.command_search._transport.session.post")
    def test_large_pool_shortlists_matching_files_before_inference(self, infer: MagicMock) -> None:
        candidates: list[SearchCandidate] = [
            {**self.candidates[1], "id": f"command:{index}", "name": f"Settings {index}", "description": "Preferences"}
            for index in range(253)
        ]
        candidates.append(self.candidates[0])
        infer.return_value.status_code = 200
        infer.return_value.json.return_value = {
            "model": COMMAND_SEARCH_MODEL,
            "answers": {
                "match": {
                    "type": "choice",
                    "choice": "0",
                    "confidence": 0.9,
                    "probabilities": {**{str(index): 0.0 for index in range(15)}, "0": 0.9, "none": 0.1},
                }
            },
        }
        self.assertEqual(CommandSearch.rank("chekout", candidates, team_id=1, user_id=1), self.candidates[:1])
        body = infer.call_args.kwargs["json"]
        self.assertEqual(len(body["questions"]["match"]["criteria"]), 16)
        self.assertEqual(len(body["state"]["candidates"]), 15)
        self.assertEqual(body["state"]["candidates"]["0"]["name"], "Checkout funnel")
