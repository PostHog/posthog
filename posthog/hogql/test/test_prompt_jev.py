import json

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

import httpx
from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.functions.prompt_jev import PromptJevCall
from posthog.hogql.parser import parse_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.transforms.prompt_jev import PromptJevRunner

from posthog.models.team import Team


def gateway_response(_url: str, *, json: dict, headers: dict) -> httpx.Response:
    answers = {}
    for name, question in json["questions"].items():
        text = json["state"][name]
        if question["type"] == "noul":
            answers[name] = {"type": "noul", "noul": 0.9 if "refund" in text else 0.1}
        else:
            choice = "billing" if "refund" in text else "other"
            answers[name] = {
                "type": "choice",
                "choice": choice,
                "confidence": 0.9,
                "probabilities": {label: 0.9 if label == choice else 0.1 for label in question["criteria"]},
            }
    return httpx.Response(200, json={"model": "jevk5-0.2", "answers": answers, "usage": {"input_tokens": 10}})


@override_settings(AI_GATEWAY_URL="https://gateway.example.com/v1", AI_GATEWAY_API_KEY="test-key")
class TestPromptJev(SimpleTestCase):
    @parameterized.expand(
        [
            ("prompt_jev('a', '')", "non-empty"),
            ("prompt_jev('a', instructions)", "literal"),
            ("prompt_jev('a', 'q', choice := ['a', 'a'])", "unique"),
            ("prompt_jev('a', 'q', choice := ['a'])", "between 2"),
            ("prompt_jev('a', 'q', batch_size := 0)", "between 1"),
            ("prompt_jev('a', 'q', noul := ['yes', 'no'])", "exactly"),
            ("prompt_jev('a', 'q', choice := ['a','b'], noul := ['true','false'])", "either"),
            ("prompt_jev('a', 'q', score := ['a','b'])", "supports"),
        ]
    )
    def test_invalid_arguments(self, query: str, message: str) -> None:
        node = parse_expr(query)
        assert isinstance(node, ast.Call)
        with self.assertRaisesRegex(QueryError, message):
            PromptJevCall.parse(node)

    def test_batches_deduplicates_and_skips_nulls(self) -> None:
        node = parse_expr("prompt_jev(body, 'Refund?', batch_size := 2)")
        assert isinstance(node, ast.Call)
        spec = PromptJevCall.parse(node)
        runner = PromptJevRunner(team_id=123, distinct_id="test-user")
        with patch("httpx.Client.post", side_effect=gateway_response) as post:
            self.assertEqual(runner.evaluate(spec, [None, "refund", "hello", "refund"]), [None, 0.9, 0.1, 0.9])
            self.assertEqual(runner.evaluate(spec, ["refund"]), [0.9])
        self.assertEqual(post.call_count, 1)
        request = post.call_args.kwargs
        self.assertEqual(len(request["json"]["questions"]), 2)
        properties = json.loads(request["headers"]["X-PostHog-Properties"])
        self.assertEqual(properties["team_id"], "123")

    @parameterized.expand([(42, "must be text"), ("x" * 8193, "8 KiB")])
    def test_rejects_invalid_input_before_network(self, value: object, message: str) -> None:
        node = parse_expr("prompt_jev(body, 'Refund?')")
        assert isinstance(node, ast.Call)
        with patch("httpx.Client.post") as post, self.assertRaisesRegex(QueryError, message):
            PromptJevRunner(team_id=1, distinct_id=None).evaluate(PromptJevCall.parse(node), [value])
        post.assert_not_called()

    def test_gateway_failure_does_not_return_a_decision(self) -> None:
        node = parse_expr("prompt_jev('refund', 'Refund?')")
        assert isinstance(node, ast.Call)
        with (
            patch("httpx.Client.post", return_value=httpx.Response(429)),
            self.assertRaisesRegex(QueryError, "could not evaluate"),
        ):
            PromptJevRunner(team_id=1, distinct_id=None).evaluate(PromptJevCall.parse(node), ["refund"])


@override_settings(
    HOGQL_PROMPT_JEV_ENABLED=True, AI_GATEWAY_URL="https://gateway.example.com/v1", AI_GATEWAY_API_KEY="test-key"
)
class TestPromptJevQuery(ClickhouseTestMixin, APIBaseTest):
    def test_query_api_only_classifies_the_requesting_teams_events(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        for team, message in [(self.team, "refund please"), (other_team, "different project message")]:
            _create_event(
                team=team, event="jev_test_message", distinct_id="synthetic-user", properties={"message": message}
            )
        flush_persons_and_events()
        with patch("httpx.Client.post", side_effect=gateway_response) as post:
            response = self.client.post(
                f"/api/environments/{self.team.id}/query/",
                {
                    "query": {
                        "kind": "HogQLQuery",
                        "query": "SELECT prompt_jev(properties.message, 'Refund?') AS probability FROM events WHERE event = 'jev_test_message' LIMIT 10",
                    }
                },
            )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["results"], [[0.9]])
        self.assertEqual(list(post.call_args.kwargs["json"]["state"].values()), ["refund please"])

    @parameterized.expand(
        [
            (
                "SELECT probability FROM (SELECT prompt_jev('refund please', 'Refund?') AS probability) WHERE probability > 0.5",
                [(0.9,)],
            ),
            (
                "SELECT result.choice, count() FROM (SELECT prompt_jev(body, 'Route?', choice := ['billing', 'other']) AS result FROM (SELECT arrayJoin(['refund', 'hello', 'refund']) AS body)) GROUP BY result.choice ORDER BY result.choice",
                [("billing", 2), ("other", 1)],
            ),
            (
                "WITH classified AS (SELECT prompt_jev('refund', 'Refund?') AS p) SELECT a.p, b.p FROM classified a CROSS JOIN classified b",
                [(0.9, 0.9)],
            ),
            ("SELECT prompt_jev(NULL, 'Refund?') AS p", [(None,)]),
            ("SELECT prompt_jev('hello', 'Refund?') AS p LIMIT 0", []),
        ]
    )
    def test_sql_decisions(self, query: str, expected: list) -> None:
        with patch("httpx.Client.post", side_effect=gateway_response) as post:
            response = execute_hogql_query(query, self.team, user=self.user)
        self.assertEqual(response.results, expected)
        self.assertLessEqual(post.call_count, 1)

    @parameterized.expand(
        [
            ("SELECT prompt_jev('a', 'q')", "named SELECT"),
            ("SELECT prompt_jev('a', 'q') AS p ORDER BY p", "outside"),
            ("SELECT prompt_jev('a', 'q') AS p WHERE p > 0.5", "outer query"),
            ("SELECT prompt_jev(toString(number), 'q') AS p FROM numbers(1001)", "at most 1000"),
        ]
    )
    def test_rejects_unsafe_query_shapes_before_inference(self, query: str, message: str) -> None:
        with patch("httpx.Client.post") as post, self.assertRaisesRegex(QueryError, message):
            execute_hogql_query(query, self.team, user=self.user)
        post.assert_not_called()

    @override_settings(HOGQL_PROMPT_JEV_ENABLED=False)
    def test_disabled(self) -> None:
        with patch("httpx.Client.post") as post, self.assertRaisesRegex(QueryError, "disabled"):
            execute_hogql_query("SELECT prompt_jev('a', 'q') AS p", self.team, user=self.user)
        post.assert_not_called()
