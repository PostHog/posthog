import re
import json
import time
import asyncio

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

import httpx
from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.functions.prompt_jev import PromptJevCall
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.transforms.prompt_jev import PromptJevBudget, PromptJevRunner

from posthog.clickhouse.client import sync_execute
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
            ("SELECT jev('a', 'q') AS p", 1000),
            ("SELECT jev('a', 'q') AS p, jev('b', 'q') AS q LIMIT 500", 1000),
            ("SELECT jev('a', 'q') AS p, jev('b', 'q') AS q LIMIT 0", 0),
            (
                "WITH c AS (SELECT jev('a', 'q') AS p LIMIT 1000) SELECT a.p, b.p FROM c a CROSS JOIN c b",
                1000,
            ),
            (
                "WITH c AS (SELECT jev('a', 'q') AS p LIMIT 600) SELECT 0.0 AS p UNION ALL SELECT p FROM c",
                600,
            ),
            (
                "WITH c AS (SELECT jev('a', 'q') AS p LIMIT 600) SELECT p FROM c UNION ALL SELECT p FROM c",
                600,
            ),
        ]
    )
    def test_query_budget_reservations(self, query: str, expected: int) -> None:
        budget = PromptJevBudget()
        budget.visit(parse_select(query))
        self.assertEqual(budget.decisions, expected)

    @override_settings(HOGQL_JEV_MAX_ROWS=5000, HOGQL_JEV_MAX_DECISIONS=10000)
    def test_raised_limits_reserve_and_allow_more_decisions(self) -> None:
        budget = PromptJevBudget()
        budget.visit(parse_select("SELECT jev('a', 'q') AS p, jev('b', 'q') AS q LIMIT 5000"))
        self.assertEqual(budget.decisions, 10000)
        with self.assertRaisesRegex(QueryError, "query budget of 10000"):
            PromptJevBudget().visit(parse_select("SELECT jev('a', 'q') AS p, jev('b', 'q') AS q, jev('c', 'q') AS r"))

    def test_unused_ctes_do_not_reserve_budget(self) -> None:
        budget = PromptJevBudget()
        budget.visit(parse_select("WITH a AS (SELECT jev('a', 'q') AS p), b AS (SELECT jev('b', 'q') AS p) SELECT 1"))
        self.assertEqual(budget.decisions, 0)

    @parameterized.expand(
        [
            ("jev('a', '')", "non-empty"),
            ("jev('a', instructions)", "literal"),
            ("jev('a', 'q', choice := ['a', 'a'])", "unique"),
            ("jev('a', 'q', choice := ['a'])", "between 2"),
            ("jev('a', 'q', batch_size := 0)", "between 1"),
            ("jev('a', 'q', noul := ['yes', 'no'])", "exactly"),
            ("jev('a', 'q', choice := ['a','b'], noul := ['true','false'])", "either"),
            ("jev('a', 'q', score := ['a','b'])", "supports"),
            ("jev('a', 'q', model := 'jevk5')", "supports"),
            ("decide('a', 'q', model := 'gpt')", "model must be one of"),
            ("decide('a', 'q', model := name)", "model must be one of"),
            ("decide('a', '')", "decide instructions must be a non-empty"),
        ]
    )
    def test_invalid_arguments(self, query: str, message: str) -> None:
        node = parse_expr(query)
        assert isinstance(node, ast.Call)
        with self.assertRaisesRegex(QueryError, message):
            PromptJevCall.parse(node)

    def test_batches_deduplicates_and_skips_nulls(self) -> None:
        node = parse_expr("jev(body, 'Refund?', batch_size := 2)")
        assert isinstance(node, ast.Call)
        spec = PromptJevCall.parse(node)
        runner = PromptJevRunner(team_id=123, distinct_id="test-user")
        with patch("httpx.AsyncClient.post", side_effect=gateway_response) as post:
            self.assertEqual(runner.evaluate(spec, [None, "refund", "hello", "refund"]), [None, 0.9, 0.1, 0.9])
            self.assertEqual(runner.evaluate(spec, ["refund"]), [0.9])
        self.assertEqual(post.call_count, 1)
        request = post.call_args.kwargs
        self.assertEqual(len(request["json"]["questions"]), 2)
        properties = json.loads(request["headers"]["X-PostHog-Properties"])
        self.assertEqual(properties["team_id"], "123")

    @parameterized.expand([(42, "must be text"), ("x" * 8193, "8 KiB")])
    def test_rejects_invalid_input_before_network(self, value: object, message: str) -> None:
        node = parse_expr("jev(body, 'Refund?')")
        assert isinstance(node, ast.Call)
        with patch("httpx.AsyncClient.post") as post, self.assertRaisesRegex(QueryError, message):
            PromptJevRunner(team_id=1, distinct_id=None).evaluate(PromptJevCall.parse(node), [value])
        post.assert_not_called()

    @parameterized.expand([(429, "could not evaluate"), (402, "used all its AI credits")])
    def test_gateway_failure_does_not_return_a_decision(self, status: int, message: str) -> None:
        node = parse_expr("jev('refund', 'Refund?')")
        assert isinstance(node, ast.Call)
        with (
            patch("httpx.AsyncClient.post", return_value=httpx.Response(status)),
            self.assertRaisesRegex(QueryError, message),
        ):
            PromptJevRunner(team_id=1, distinct_id=None).evaluate(PromptJevCall.parse(node), ["refund"])

    def test_deadline_cancels_inflight_requests_and_pending_batches(self) -> None:
        node = parse_expr("jev(body, 'Refund?', batch_size := 1)")
        assert isinstance(node, ast.Call)
        runner = PromptJevRunner(team_id=1, distinct_id=None)
        cancelled = 0
        started = 0
        timeout = asyncio.timeout
        deadline: asyncio.Timeout | None = None

        def controlled_timeout(seconds: float) -> asyncio.Timeout:
            nonlocal deadline
            deadline = timeout(None)
            return deadline

        async def stalled_response(*args: object, **kwargs: object) -> httpx.Response:
            nonlocal cancelled, started
            started += 1
            if started == 4:
                assert deadline is not None
                deadline.reschedule(asyncio.get_running_loop().time())
            try:
                await asyncio.Event().wait()
            finally:
                cancelled += 1
            raise AssertionError("The stalled response must be cancelled")

        with (
            patch("httpx.AsyncClient.post", side_effect=stalled_response) as post,
            patch("posthog.hogql.transforms.prompt_jev.asyncio.timeout", side_effect=controlled_timeout),
            self.assertRaisesRegex(QueryError, "time limit"),
        ):
            runner.evaluate(PromptJevCall.parse(node), [str(i) for i in range(8)])
        self.assertEqual(post.call_count, 4)
        self.assertEqual(cancelled, 4)

    def test_expired_deadline_sends_no_requests(self) -> None:
        node = parse_expr("jev(body, 'Refund?')")
        assert isinstance(node, ast.Call)
        runner = PromptJevRunner(team_id=1, distinct_id=None)
        runner.deadline = time.monotonic() - 1
        self.assertEqual(runner.source_timeout(), 1)
        with patch("httpx.AsyncClient.post") as post, self.assertRaisesRegex(QueryError, "time limit"):
            runner.evaluate(PromptJevCall.parse(node), ["refund"])
        post.assert_not_called()


@override_settings(AI_GATEWAY_URL="https://gateway.example.com/v1", AI_GATEWAY_API_KEY="test-key")
class TestPromptJevQuery(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag = patch("posthog.hogql.transforms.prompt_jev.feature_enabled_or_false", return_value=True)
        self.feature_enabled = flag.start()
        self.addCleanup(flag.stop)

    @parameterized.expand(
        [
            ("SELECT " + ", ".join(f"jev('a', 'q{i}') AS p{i}" for i in range(10)) + " LIMIT 101",),
            ("SELECT jev('a', 'q') AS p, jev('b', 'q') AS q",),
            ("SELECT jev('a', 'q') AS p LIMIT 501 UNION ALL SELECT jev('b', 'q') AS p LIMIT 500",),
            ("SELECT jev(toString(p), 'q') AS q FROM (SELECT jev('a', 'q') AS p LIMIT 501) LIMIT 500",),
            (
                "WITH c AS (SELECT jev(toString(number), 'first') AS p FROM numbers(1000) LIMIT 1000) "
                "SELECT 0.0 AS p UNION ALL SELECT jev('refund', 'second') AS p FROM c LIMIT 1",
            ),
        ]
    )
    def test_combined_budget_rejects_before_source_queries_or_inference(self, query: str) -> None:
        with (
            patch("posthog.hogql.query.sync_execute") as execute,
            patch("httpx.AsyncClient.post") as post,
            self.assertRaisesRegex(QueryError, "across all columns and SELECTs"),
        ):
            execute_hogql_query(query, self.team, user=self.user)
        execute.assert_not_called()
        post.assert_not_called()

    @parameterized.expand([(False,), (None,)])
    def test_unapproved_project_cannot_start_inference(self, enabled: bool | None) -> None:
        self.feature_enabled.return_value = enabled
        with (
            patch("posthog.hogql.query.sync_execute") as execute,
            patch("httpx.AsyncClient.post") as post,
            self.assertRaisesRegex(QueryError, "not enabled for this project"),
        ):
            execute_hogql_query("SELECT jev('refund', 'Refund?') AS p", self.team, user=self.user)
        execute.assert_not_called()
        post.assert_not_called()
        self.assertEqual(self.feature_enabled.call_args.kwargs["groups"]["project"], str(self.team.pk))

    def test_team_out_of_ai_credits_cannot_start_inference(self) -> None:
        with (
            patch("ee.billing.quota_limiting.is_team_over_ai_credit_budget", return_value=True) as limited,
            patch("posthog.hogql.query.sync_execute") as execute,
            patch("httpx.AsyncClient.post") as post,
            self.assertRaisesRegex(QueryError, "used all its AI credits"),
        ):
            execute_hogql_query("SELECT jev('refund', 'Refund?') AS p", self.team, user=self.user)
        execute.assert_not_called()
        post.assert_not_called()
        limited.assert_called_once_with(self.team.api_token)

    def test_credit_lookup_failure_does_not_block_the_query(self) -> None:
        with (
            patch("ee.billing.quota_limiting.is_team_over_ai_credit_budget", side_effect=RuntimeError("redis down")),
            patch("httpx.AsyncClient.post", side_effect=gateway_response),
        ):
            response = execute_hogql_query("SELECT jev('refund', 'Refund?') AS p", self.team, user=self.user)
        self.assertEqual(response.results, [(0.9,)])

    @parameterized.expand([("global",), ("team",)])
    def test_http_route_is_rejected_before_query_or_inference(self, mode: str) -> None:
        with (
            override_settings(
                CLICKHOUSE_USE_HTTP=mode == "global",
                CLICKHOUSE_USE_HTTP_PER_TEAM=[self.team.pk] if mode == "team" else [],
            ),
            patch("posthog.hogql.query.sync_execute") as execute,
            patch("httpx.AsyncClient.post") as post,
            self.assertRaisesRegex(QueryError, "native ClickHouse connection"),
        ):
            execute_hogql_query("SELECT jev('refund', 'Refund?') AS p", self.team, user=self.user)
        execute.assert_not_called()
        post.assert_not_called()

    def test_query_api_only_classifies_the_requesting_teams_events(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        for team, message in [(self.team, "refund please"), (other_team, "different project message")]:
            _create_event(
                team=team, event="jev_test_message", distinct_id="synthetic-user", properties={"message": message}
            )
        flush_persons_and_events()
        with patch("httpx.AsyncClient.post", side_effect=gateway_response) as post:
            response = self.client.post(
                f"/api/environments/{self.team.id}/query/",
                {
                    "query": {
                        "kind": "HogQLQuery",
                        "query": "SELECT jev(properties.message, 'Refund?') AS probability FROM events WHERE event = 'jev_test_message' LIMIT 10",
                    }
                },
            )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["results"], [[0.9]])
        self.assertEqual(list(post.call_args.kwargs["json"]["state"].values()), ["refund please"])

    @parameterized.expand(
        [
            (
                "SELECT probability FROM (SELECT jev('refund please', 'Refund?') AS probability) WHERE probability > 0.5",
                [(0.9,)],
            ),
            (
                "SELECT result.choice, count() FROM (SELECT jev(body, 'Route?', choice := ['billing', 'other']) AS result FROM (SELECT arrayJoin(['refund', 'hello', 'refund']) AS body)) GROUP BY result.choice ORDER BY result.choice",
                [("billing", 2), ("other", 1)],
            ),
            (
                "WITH classified AS (SELECT jev('refund', 'Refund?') AS p) SELECT a.p, b.p FROM classified a CROSS JOIN classified b",
                [(0.9, 0.9)],
            ),
            (
                "WITH a AS (SELECT jev('refund', 'Refund?') AS p), b AS (SELECT p FROM a) SELECT p FROM b",
                [(0.9,)],
            ),
            (
                "SELECT label FROM (SELECT jev(body, 'Refund?') AS label FROM (SELECT label AS body FROM (SELECT 'refund' AS label)))",
                [(0.9,)],
            ),
            ("SELECT jev(NULL, 'Refund?') AS p", [(None,)]),
            ("SELECT decide('refund', 'Refund?', model := 'jevk5') AS p", [(0.9,)]),
            ("SELECT jev('hello', 'Refund?') AS p LIMIT 0", []),
            (
                "SELECT " + ", ".join(f"jev('refund', 'Refund?') AS p{i}" for i in range(10)) + " LIMIT 100",
                [(0.9,) * 10],
            ),
            (
                "WITH messages AS (SELECT 'refund' AS body) SELECT 0.0 AS p UNION ALL SELECT jev(body, 'Refund?') AS p FROM messages LIMIT 10",
                [(0.0,), (0.9,)],
            ),
        ]
    )
    def test_sql_decisions(self, query: str, expected: list) -> None:
        with patch("httpx.AsyncClient.post", side_effect=gateway_response) as post:
            response = execute_hogql_query(query, self.team, user=self.user)
        # UNION ALL without ORDER BY returns rows in any order.
        self.assertEqual(sorted(response.results), sorted(expected))
        self.assertLessEqual(post.call_count, 1)

    def test_one_query_mixes_models_with_a_call_per_model(self) -> None:
        with patch("httpx.AsyncClient.post", side_effect=gateway_response) as post:
            response = execute_hogql_query(
                "SELECT jev('refund', 'Refund?') AS a, decide('refund', 'Refund?', model := 'jevk5') AS b LIMIT 1",
                self.team,
                user=self.user,
            )
        assert response.results == [(0.9, 0.9)]
        calls = [
            (call.kwargs["json"]["model"], call.kwargs["headers"]["X-PostHog-Product"]) for call in post.call_args_list
        ]
        assert sorted(calls) == [
            ("posthog/hogference/jeeves-0.1", "hogql_decide"),
            ("posthog/hogference/jevk5-fp8-0.2", "hogql_decide"),
        ]

    @parameterized.expand(
        [
            ("WITH unused AS (SELECT jev('refund', 'Refund?') AS p) SELECT 1",),
            ("WITH a AS (SELECT jev('refund', 'Refund?') AS p), b AS (SELECT p FROM a) SELECT 1",),
        ]
    )
    def test_unused_ctes_send_no_requests(self, query: str) -> None:
        with patch("httpx.AsyncClient.post") as post:
            response = execute_hogql_query(query, self.team, user=self.user)
        self.assertEqual(response.results, [(1,)])
        post.assert_not_called()

    @parameterized.expand([(150, 1000), (1200, 2000)])
    def test_explicit_limit_above_the_default_keeps_every_row(self, rows: int, limit: int) -> None:
        with (
            override_settings(HOGQL_JEV_MAX_ROWS=limit, HOGQL_JEV_MAX_DECISIONS=limit),
            patch("httpx.AsyncClient.post", side_effect=gateway_response),
        ):
            response = execute_hogql_query(
                f"SELECT jev(toString(number), 'Refund?') AS p FROM numbers({rows}) LIMIT {rows}",
                self.team,
                user=self.user,
            )
        self.assertEqual(len(response.results or []), rows)

    def test_outer_query_reads_properties_off_a_passthrough_column(self) -> None:
        _create_event(
            team=self.team,
            event="jev_test_message",
            distinct_id="synthetic-user",
            properties={"message": "refund please", "category": "billing"},
        )
        flush_persons_and_events()
        with patch("httpx.AsyncClient.post", side_effect=gateway_response):
            response = execute_hogql_query(
                "SELECT props.category, p FROM (SELECT properties AS props, jev(properties.message, 'Refund?') AS p FROM events WHERE event = 'jev_test_message' LIMIT 1)",
                self.team,
                user=self.user,
            )
        self.assertEqual(response.results, [("billing", 0.9)])

    def test_source_scan_stays_within_the_inference_deadline(self) -> None:
        with (
            patch("httpx.AsyncClient.post", side_effect=gateway_response),
            patch("posthog.hogql.query.sync_execute", wraps=sync_execute) as execute,
        ):
            execute_hogql_query("SELECT jev('refund', 'Refund?') AS p", self.team, user=self.user)
        timeouts = [
            int(seconds)
            for call in execute.call_args_list
            for seconds in re.findall(r"max_execution_time=(\d+)", call.args[0])
        ]
        self.assertEqual(len(timeouts), 2)
        self.assertLessEqual(max(timeouts), 60)

    @parameterized.expand(
        [
            ("SELECT jev('a', 'q')", "named SELECT"),
            ("SELECT jev('a', 'q') AS p ORDER BY p", "outside"),
            ("SELECT jev('a', 'q') AS p WHERE p > 0.5", "outer query"),
            ("SELECT labl FROM (SELECT jev('refund', 'Refund?') AS label)", "labl"),
            ("SELECT jev(toString(number), 'q') AS p FROM numbers(1001)", "at most 1000"),
            (
                "SELECT jev(toString(number), 'Topic?') AS a, jev(toString(number), 'Tone?') AS b FROM numbers(600)",
                "query budget",
            ),
        ]
    )
    def test_rejects_unsafe_query_shapes_before_inference(self, query: str, message: str) -> None:
        with patch("httpx.AsyncClient.post") as post, self.assertRaisesRegex(QueryError, message):
            execute_hogql_query(query, self.team, user=self.user)
        post.assert_not_called()

    @override_settings(AI_GATEWAY_URL="", AI_GATEWAY_API_KEY="")
    def test_missing_gateway_configuration(self) -> None:
        with patch("httpx.AsyncClient.post") as post, self.assertRaisesRegex(QueryError, "not configured"):
            execute_hogql_query("SELECT jev('a', 'q') AS p", self.team, user=self.user)
        post.assert_not_called()
