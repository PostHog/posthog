from datetime import UTC, datetime

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import prepare_and_print_ast

from posthog.hogql_queries.web_analytics.bot_analytics import (
    BOT_ANALYTICS_EVENTS,
    BotTrendsBreakdown,
    bot_trends_select_query,
    ensure_bot_analytics_precomputed,
)
from posthog.hogql_queries.web_analytics.bot_analytics.precomputation import _bot_filter_expr

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import LazyComputationResult
from products.analytics_platform.backend.models import PreaggregationJob


class TestBotAnalyticsPrecomputation(ClickhouseTestMixin, BaseTest):
    def test_creates_jobs_for_each_daily_window(self):
        result = ensure_bot_analytics_precomputed(
            team=self.team,
            breakdown=BotTrendsBreakdown.CRAWLER,
            date_from=datetime(2024, 1, 1, tzinfo=UTC),
            date_to=datetime(2024, 1, 4, tzinfo=UTC),
        )

        assert result.ready is True
        assert len(result.job_ids) == 3

        jobs = list(PreaggregationJob.objects.filter(id__in=result.job_ids).order_by("time_range_start"))
        for job in jobs:
            assert job.team_id == self.team.id
            assert job.status == PreaggregationJob.Status.READY

    def test_idempotent_within_same_range(self):
        first = ensure_bot_analytics_precomputed(
            team=self.team,
            breakdown=BotTrendsBreakdown.CRAWLER,
            date_from=datetime(2024, 1, 1, tzinfo=UTC),
            date_to=datetime(2024, 1, 2, tzinfo=UTC),
        )
        second = ensure_bot_analytics_precomputed(
            team=self.team,
            breakdown=BotTrendsBreakdown.CRAWLER,
            date_from=datetime(2024, 1, 1, tzinfo=UTC),
            date_to=datetime(2024, 1, 2, tzinfo=UTC),
        )
        assert first.job_ids == second.job_ids

    @parameterized.expand(
        [
            (BotTrendsBreakdown.CRAWLER, BotTrendsBreakdown.CATEGORY),
            (BotTrendsBreakdown.CRAWLER, BotTrendsBreakdown.HOST),
            (BotTrendsBreakdown.CRAWLER, BotTrendsBreakdown.PATHNAME),
            (BotTrendsBreakdown.HOST, BotTrendsBreakdown.PATHNAME),
        ]
    )
    def test_different_breakdowns_produce_different_jobs(
        self, first_breakdown: BotTrendsBreakdown, second_breakdown: BotTrendsBreakdown
    ):
        first = ensure_bot_analytics_precomputed(
            team=self.team,
            breakdown=first_breakdown,
            date_from=datetime(2024, 2, 1, tzinfo=UTC),
            date_to=datetime(2024, 2, 2, tzinfo=UTC),
        )
        second = ensure_bot_analytics_precomputed(
            team=self.team,
            breakdown=second_breakdown,
            date_from=datetime(2024, 2, 1, tzinfo=UTC),
            date_to=datetime(2024, 2, 2, tzinfo=UTC),
        )

        first_job = PreaggregationJob.objects.get(id=first.job_ids[0])
        second_job = PreaggregationJob.objects.get(id=second.job_ids[0])
        assert first_job.query_hash != second_job.query_hash

    def test_bot_filter_expr_shape(self):
        expr = _bot_filter_expr()
        assert isinstance(expr, ast.And)
        assert len(expr.exprs) == 2

        is_bot, has_name = expr.exprs
        assert isinstance(is_bot, ast.CompareOperation)
        assert is_bot.op == ast.CompareOperationOp.Eq
        assert isinstance(is_bot.left, ast.Field) and is_bot.left.chain == ["$virt_is_bot"]
        assert isinstance(is_bot.right, ast.Constant) and is_bot.right.value is True

        assert isinstance(has_name, ast.CompareOperation)
        assert has_name.op == ast.CompareOperationOp.NotEq
        assert isinstance(has_name.left, ast.Field) and has_name.left.chain == ["$virt_bot_name"]


class TestBotTrendsSelectQuery(ClickhouseTestMixin, BaseTest):
    def test_returns_zero_row_query_when_no_jobs(self):
        query = bot_trends_select_query(
            job_ids=[],
            date_from=datetime(2024, 1, 1, tzinfo=UTC),
            date_to=datetime(2024, 1, 8, tzinfo=UTC),
            interval="day",
        )
        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
        sql, _ = prepare_and_print_ast(query, context=context, dialect="clickhouse")
        assert "SELECT" in sql

    @parameterized.expand(
        [
            ("hour", "time_window_start"),
            ("day", "toStartOfDay"),
            ("week", "toStartOfWeek"),
            ("month", "toStartOfMonth"),
        ]
    )
    def test_interval_bucketing(self, interval: str, expected_substring: str):
        query = bot_trends_select_query(
            job_ids=["00000000-0000-0000-0000-000000000001"],
            date_from=datetime(2024, 1, 1, tzinfo=UTC),
            date_to=datetime(2024, 1, 8, tzinfo=UTC),
            interval=interval,
            limit_breakdowns=None,
        )
        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
        hogql, _ = prepare_and_print_ast(query, context=context, dialect="hogql")
        assert expected_substring in hogql

    def test_top_n_wrapper_is_applied(self):
        query = bot_trends_select_query(
            job_ids=["00000000-0000-0000-0000-000000000001"],
            date_from=datetime(2024, 1, 1, tzinfo=UTC),
            date_to=datetime(2024, 1, 8, tzinfo=UTC),
            interval="day",
            limit_breakdowns=5,
        )
        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
        hogql, _ = prepare_and_print_ast(query, context=context, dialect="hogql")
        assert "LIMIT 5" in hogql
        assert "sum(requests)" in hogql


class TestBotAnalyticsConstants(BaseTest):
    def test_bot_events_match_frontend(self):
        # Mirror of `BOT_ANALYTICS_EVENTS` in
        # `frontend/src/scenes/web-analytics/common.ts`. If this changes,
        # either update the frontend in lockstep or split the constant.
        assert BOT_ANALYTICS_EVENTS == ("$pageview", "$screen", "$http_log")


class TestBotAnalyticsWarming(ClickhouseTestMixin, BaseTest):
    def test_warm_function_runs_all_breakdowns(self):
        from posthog.hogql_queries.web_analytics.bot_analytics.warming import warm_bot_analytics_for_team

        results = warm_bot_analytics_for_team(team=self.team, days=2)
        assert set(results.keys()) == set(BotTrendsBreakdown)
        for result in results.values():
            assert result.ready is True

    def test_warm_function_isolates_breakdown_failures(self):
        from posthog.hogql_queries.web_analytics.bot_analytics import warming as warming_module

        call_count = {"n": 0}

        def fake_ensure(team, breakdown, date_from, date_to):
            call_count["n"] += 1
            if breakdown == BotTrendsBreakdown.HOST:
                raise RuntimeError("boom")
            return LazyComputationResult(ready=True, job_ids=[])

        with patch.object(warming_module, "ensure_bot_analytics_precomputed", side_effect=fake_ensure):
            results = warming_module.warm_bot_analytics_for_team(team=self.team, days=1)

        assert call_count["n"] == len(BotTrendsBreakdown)
        assert BotTrendsBreakdown.HOST not in results
        assert BotTrendsBreakdown.CRAWLER in results
