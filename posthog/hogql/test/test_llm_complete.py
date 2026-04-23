from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from posthog.test.base import BaseTest

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import QueryError
from posthog.hogql.functions.llm_complete import extract_llm_complete_args
from posthog.hogql.parser import parse_select
from posthog.hogql.timings import HogQLTimings
from posthog.hogql.transforms.llm_completions import LlmCompletionSpec, rewrite_llm_completions
from posthog.llm.hogql_runner import apply_llm_completions


class TestExtractLlmCompleteArgs(BaseTest):
    def test_two_args(self):
        call = ast.Call(
            name="__preview_llm_complete",
            args=[ast.Constant(value="claude-haiku-4-5"), ast.Constant(value="hi")],
        )
        model, prompt, system = extract_llm_complete_args(call)
        self.assertEqual(model, "claude-haiku-4-5")
        self.assertEqual(prompt, ast.Constant(value="hi"))
        self.assertIsNone(system)

    def test_three_args(self):
        call = ast.Call(
            name="__preview_llm_complete",
            args=[
                ast.Constant(value="m"),
                ast.Constant(value="hi"),
                ast.Constant(value="be terse"),
            ],
        )
        _, _, system = extract_llm_complete_args(call)
        self.assertEqual(system, "be terse")

    def test_non_constant_model_rejected(self):
        call = ast.Call(
            name="__preview_llm_complete",
            args=[ast.Field(chain=["model"]), ast.Constant(value="hi")],
        )
        with self.assertRaises(QueryError):
            extract_llm_complete_args(call)

    def test_empty_model_rejected(self):
        call = ast.Call(
            name="__preview_llm_complete",
            args=[ast.Constant(value=""), ast.Constant(value="hi")],
        )
        with self.assertRaises(QueryError):
            extract_llm_complete_args(call)

    def test_non_constant_system_rejected(self):
        call = ast.Call(
            name="__preview_llm_complete",
            args=[
                ast.Constant(value="m"),
                ast.Constant(value="hi"),
                ast.Field(chain=["sys"]),
            ],
        )
        with self.assertRaises(QueryError):
            extract_llm_complete_args(call)

    def test_arity_rejected(self):
        call = ast.Call(name="__preview_llm_complete", args=[ast.Constant(value="m")])
        with self.assertRaises(QueryError):
            extract_llm_complete_args(call)


class TestRewriteLlmCompletions(BaseTest):
    def _ctx(self) -> HogQLContext:
        return HogQLContext(team_id=self.team.id)

    def test_noop_when_absent(self):
        select = cast(ast.SelectQuery, parse_select("SELECT 1, 2"))
        ctx = self._ctx()
        rewrite_llm_completions(select, ctx)
        self.assertEqual(ctx.llm_completions, [])

    def test_rewrites_aliased_top_level(self):
        select = cast(
            ast.SelectQuery,
            parse_select("SELECT event, __preview_llm_complete('m', concat('p: ', properties)) AS summary FROM events"),
        )
        ctx = self._ctx()
        rewrite_llm_completions(select, ctx)
        self.assertEqual(len(ctx.llm_completions), 1)
        spec = ctx.llm_completions[0]
        self.assertEqual(spec.column_index, 1)
        self.assertEqual(spec.column_alias, "summary")
        self.assertEqual(spec.model, "m")
        self.assertIsNone(spec.system_prompt)

        # After rewrite, the second column should be an Alias(summary, concat(...)) — no Call.
        rewritten = select.select[1]
        self.assertIsInstance(rewritten, ast.Alias)
        self.assertEqual(rewritten.alias, "summary")
        assert isinstance(rewritten.expr, ast.Call)
        self.assertEqual(rewritten.expr.name, "concat")

    def test_assigns_synthetic_alias_when_missing(self):
        select = cast(
            ast.SelectQuery,
            parse_select("SELECT __preview_llm_complete('m', 'hi') FROM events"),
        )
        ctx = self._ctx()
        rewrite_llm_completions(select, ctx)
        self.assertEqual(ctx.llm_completions[0].column_alias, "__llm_complete_0")
        self.assertIsInstance(select.select[0], ast.Alias)

    def test_three_arg_system_prompt(self):
        select = cast(
            ast.SelectQuery,
            parse_select("SELECT __preview_llm_complete('m', 'hi', 'be terse') AS s FROM events"),
        )
        ctx = self._ctx()
        rewrite_llm_completions(select, ctx)
        self.assertEqual(ctx.llm_completions[0].system_prompt, "be terse")

    def test_rejects_use_in_where(self):
        select = cast(
            ast.SelectQuery,
            parse_select(
                "SELECT event FROM events WHERE __preview_llm_complete('m', 'hi') = 'yes'"
            ),
        )
        with self.assertRaises(QueryError):
            rewrite_llm_completions(select, self._ctx())

    def test_rejects_nested_usage(self):
        select = cast(
            ast.SelectQuery,
            parse_select("SELECT lower(__preview_llm_complete('m', 'hi')) AS s FROM events"),
        )
        with self.assertRaises(QueryError):
            rewrite_llm_completions(select, self._ctx())

    def test_multiple_calls_each_get_spec(self):
        select = cast(
            ast.SelectQuery,
            parse_select(
                "SELECT __preview_llm_complete('m', 'a') AS x, __preview_llm_complete('m', 'b') AS y FROM events"
            ),
        )
        ctx = self._ctx()
        rewrite_llm_completions(select, ctx)
        self.assertEqual([s.column_alias for s in ctx.llm_completions], ["x", "y"])
        self.assertEqual([s.column_index for s in ctx.llm_completions], [0, 1])


def _make_response(text: str) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=text))]
    return response


class TestApplyLlmCompletions(BaseTest):
    def _spec(self, **kwargs) -> LlmCompletionSpec:
        return LlmCompletionSpec(
            column_index=kwargs.get("column_index", 0),
            column_alias=kwargs.get("column_alias", "x"),
            model=kwargs.get("model", "claude-haiku-4-5"),
            system_prompt=kwargs.get("system_prompt"),
        )

    def test_empty_specs_shortcircuits(self):
        result = apply_llm_completions(
            [("a",), ("b",)],
            [],
            user=None,
            timings=HogQLTimings(),
        )
        self.assertEqual(result, [("a",), ("b",)])

    def test_row_cap_raises_before_any_calls(self):
        with patch("posthog.llm.hogql_runner.get_async_llm_client") as client:
            with patch("posthog.llm.hogql_runner.settings") as mock_settings:
                mock_settings.HOGQL_LLM_COMPLETE_MAX_ROWS = 2
                mock_settings.HOGQL_LLM_COMPLETE_CONCURRENCY = 20
                mock_settings.HOGQL_LLM_COMPLETE_TIMEOUT_SECONDS = 30.0
                mock_settings.HOGQL_LLM_COMPLETE_MAX_TOKENS = 512
                with self.assertRaises(QueryError):
                    apply_llm_completions(
                        [("p1",), ("p2",), ("p3",)],
                        [self._spec()],
                        user=None,
                        timings=HogQLTimings(),
                    )
                client.assert_not_called()

    def test_deduplicates_identical_prompts(self):
        async_client = MagicMock()
        async_client.chat.completions.create = AsyncMock(return_value=_make_response("OUT"))
        with patch("posthog.llm.hogql_runner.get_async_llm_client", return_value=async_client):
            result = apply_llm_completions(
                [("same",), ("same",), ("other",), ("same",)],
                [self._spec()],
                user=None,
                timings=HogQLTimings(),
            )
        # Two distinct prompts → two gateway calls, not four.
        self.assertEqual(async_client.chat.completions.create.await_count, 2)
        self.assertEqual([row[0] for row in result], ["OUT", "OUT", "OUT", "OUT"])

    def test_per_row_errors_become_none(self):
        async_client = MagicMock()

        async def flaky(**kwargs):
            content = kwargs["messages"][-1]["content"]
            if content == "bad":
                raise RuntimeError("boom")
            return _make_response("ok-" + content)

        async_client.chat.completions.create = AsyncMock(side_effect=flaky)
        with patch("posthog.llm.hogql_runner.get_async_llm_client", return_value=async_client):
            result = apply_llm_completions(
                [("good",), ("bad",), ("good",)],
                [self._spec()],
                user=None,
                timings=HogQLTimings(),
            )
        self.assertEqual(result[0][0], "ok-good")
        self.assertIsNone(result[1][0])
        self.assertEqual(result[2][0], "ok-good")

    def test_distinct_id_attributed_when_user_present(self):
        async_client = MagicMock()
        async_client.chat.completions.create = AsyncMock(return_value=_make_response("x"))
        user = MagicMock()
        user.distinct_id = "user-123"
        with patch("posthog.llm.hogql_runner.get_async_llm_client", return_value=async_client):
            apply_llm_completions(
                [("p",)],
                [self._spec()],
                user=user,
                timings=HogQLTimings(),
            )
        kwargs = async_client.chat.completions.create.await_args.kwargs
        self.assertEqual(kwargs["user"], "user-123")

    def test_no_user_attribution_when_none(self):
        async_client = MagicMock()
        async_client.chat.completions.create = AsyncMock(return_value=_make_response("x"))
        with patch("posthog.llm.hogql_runner.get_async_llm_client", return_value=async_client):
            apply_llm_completions(
                [("p",)],
                [self._spec()],
                user=None,
                timings=HogQLTimings(),
            )
        self.assertNotIn("user", async_client.chat.completions.create.await_args.kwargs)

    def test_system_prompt_is_first_message(self):
        async_client = MagicMock()
        async_client.chat.completions.create = AsyncMock(return_value=_make_response("x"))
        with patch("posthog.llm.hogql_runner.get_async_llm_client", return_value=async_client):
            apply_llm_completions(
                [("u",)],
                [self._spec(system_prompt="you are terse")],
                user=None,
                timings=HogQLTimings(),
            )
        messages = async_client.chat.completions.create.await_args.kwargs["messages"]
        self.assertEqual(messages[0], {"role": "system", "content": "you are terse"})
        self.assertEqual(messages[1], {"role": "user", "content": "u"})


class TestLlmCompleteFunctionRegistration(BaseTest):
    def test_function_registered(self):
        from posthog.hogql.functions import find_hogql_posthog_function

        meta = find_hogql_posthog_function("__preview_llm_complete")
        self.assertIsNotNone(meta)
        assert meta is not None  # narrow for mypy
        self.assertEqual(meta.clickhouse_name, "__preview_llm_complete")
        self.assertEqual(meta.min_args, 2)
        self.assertEqual(meta.max_args, 3)


class TestTimingsEntry(BaseTest):
    def test_llm_completions_timing_recorded(self):
        async_client = MagicMock()
        async_client.chat.completions.create = AsyncMock(return_value=_make_response("ok"))
        timings = HogQLTimings()
        with patch("posthog.llm.hogql_runner.get_async_llm_client", return_value=async_client):
            apply_llm_completions(
                [("p",)],
                [LlmCompletionSpec(column_index=0, column_alias="x", model="m", system_prompt=None)],
                user=None,
                timings=timings,
            )
        keys = [k for k in timings.to_dict().keys() if "llm_completions" in k]
        self.assertTrue(keys, f"expected an llm_completions timing entry, got {list(timings.to_dict().keys())}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
