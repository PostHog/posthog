import pytest
from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.modifiers import HogQLQueryModifiers
from posthog.hogql.transforms.pageview_optimizer import optimize_pageview_queries, PageviewOptimizer
from posthog.test.base import BaseTest


class TestPageviewOptimizer(BaseTest):
    def setUp(self):
        super().setUp()
        self.context = HogQLContext(
            team_id=1,
            team=self.team,
            modifiers=HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=True),
        )

    def test_optimize_pageview_queries_disabled_when_no_modifier(self):
        """Test that optimization is disabled when useWebAnalyticsPreAggregatedTables is False"""
        context = HogQLContext(
            team_id=1,
            team=self.team,
            modifiers=HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=False),
        )
        
        query = ast.SelectQuery(
            select=[ast.Call(name="count", args=[])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.CompareOperation(
                left=ast.Field(chain=["event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value="$pageview"),
            ),
        )
        
        optimized = optimize_pageview_queries(query, "clickhouse", None, context)
        
        # Should not be optimized - still querying events table
        assert isinstance(optimized.select_from.table, ast.Field)
        assert optimized.select_from.table.chain == ["events"]

    def test_optimize_pageview_queries_disabled_when_no_modifiers(self):
        """Test that optimization is disabled when modifiers is None"""
        context = HogQLContext(team_id=1, team=self.team, modifiers=None)
        
        query = ast.SelectQuery(
            select=[ast.Call(name="count", args=[])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.CompareOperation(
                left=ast.Field(chain=["event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value="$pageview"),
            ),
        )
        
        optimized = optimize_pageview_queries(query, "clickhouse", None, context)
        
        # Should not be optimized - still querying events table
        assert isinstance(optimized.select_from.table, ast.Field)
        assert optimized.select_from.table.chain == ["events"]

    def test_simple_pageview_count_optimization(self):
        """Test basic pageview count query optimization"""
        query = ast.SelectQuery(
            select=[ast.Call(name="count", args=[])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.CompareOperation(
                left=ast.Field(chain=["event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value="$pageview"),
            ),
        )
        
        optimized = optimize_pageview_queries(query, "clickhouse", None, self.context)
        
        # Should be optimized to use web_stats_combined
        assert isinstance(optimized.select_from.table, ast.Field)
        assert optimized.select_from.table.chain == ["web_stats_combined"]
        
        # Should transform count() to sumMerge(pageviews_count_state)
        assert len(optimized.select) == 1
        assert isinstance(optimized.select[0], ast.Call)
        assert optimized.select[0].name == "sumMerge"
        assert len(optimized.select[0].args) == 1
        assert isinstance(optimized.select[0].args[0], ast.Field)
        assert optimized.select[0].args[0].chain == ["pageviews_count_state"]

    def test_pageview_countif_optimization(self):
        """Test pageview countIf query optimization"""
        query = ast.SelectQuery(
            select=[
                ast.Call(
                    name="countIf",
                    args=[
                        ast.CompareOperation(
                            left=ast.Field(chain=["event"]),
                            op=ast.CompareOperationOp.Eq,
                            right=ast.Constant(value="$pageview"),
                        )
                    ],
                )
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.CompareOperation(
                left=ast.Field(chain=["event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value="$pageview"),
            ),
        )
        
        optimized = optimize_pageview_queries(query, "clickhouse", None, self.context)
        
        # Should be optimized to use web_stats_combined
        assert isinstance(optimized.select_from.table, ast.Field)
        assert optimized.select_from.table.chain == ["web_stats_combined"]
        
        # Should transform countIf to sumMerge(pageviews_count_state)
        assert len(optimized.select) == 1
        assert isinstance(optimized.select[0], ast.Call)
        assert optimized.select[0].name == "sumMerge"

    def test_unique_visitors_optimization(self):
        """Test unique visitors query optimization"""
        query = ast.SelectQuery(
            select=[ast.Call(name="uniq", args=[ast.Field(chain=["distinct_id"])])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.CompareOperation(
                left=ast.Field(chain=["event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value="$pageview"),
            ),
        )
        
        optimized = optimize_pageview_queries(query, "clickhouse", None, self.context)
        
        # Should be optimized to use web_stats_combined
        assert isinstance(optimized.select_from.table, ast.Field)
        assert optimized.select_from.table.chain == ["web_stats_combined"]
        
        # Should transform uniq(distinct_id) to uniqMerge(persons_uniq_state)
        assert len(optimized.select) == 1
        assert isinstance(optimized.select[0], ast.Call)
        assert optimized.select[0].name == "uniqMerge"
        assert len(optimized.select[0].args) == 1
        assert isinstance(optimized.select[0].args[0], ast.Field)
        assert optimized.select[0].args[0].chain == ["persons_uniq_state"]

    def test_screen_event_optimization(self):
        """Test that $screen events are also optimized"""
        query = ast.SelectQuery(
            select=[ast.Call(name="count", args=[])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.CompareOperation(
                left=ast.Field(chain=["event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value="$screen"),
            ),
        )
        
        optimized = optimize_pageview_queries(query, "clickhouse", None, self.context)
        
        # Should be optimized to use web_stats_combined
        assert isinstance(optimized.select_from.table, ast.Field)
        assert optimized.select_from.table.chain == ["web_stats_combined"]

    def test_mixed_event_types_not_optimized(self):
        """Test that queries with mixed event types are not optimized"""
        query = ast.SelectQuery(
            select=[ast.Call(name="count", args=[])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.CompareOperation(
                left=ast.Field(chain=["event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value="custom_event"),
            ),
        )
        
        optimized = optimize_pageview_queries(query, "clickhouse", None, self.context)
        
        # Should not be optimized - still querying events table
        assert isinstance(optimized.select_from.table, ast.Field)
        assert optimized.select_from.table.chain == ["events"]

    def test_non_events_table_not_optimized(self):
        """Test that queries from non-events tables are not optimized"""
        query = ast.SelectQuery(
            select=[ast.Call(name="count", args=[])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["sessions"])),
            where=ast.CompareOperation(
                left=ast.Field(chain=["event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value="$pageview"),
            ),
        )
        
        optimized = optimize_pageview_queries(query, "clickhouse", None, self.context)
        
        # Should not be optimized - still querying sessions table
        assert isinstance(optimized.select_from.table, ast.Field)
        assert optimized.select_from.table.chain == ["sessions"]

    def test_complex_where_clause_preservation(self):
        """Test that compatible WHERE clauses are preserved"""
        query = ast.SelectQuery(
            select=[ast.Call(name="count", args=[])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(
                exprs=[
                    ast.CompareOperation(
                        left=ast.Field(chain=["event"]),
                        op=ast.CompareOperationOp.Eq,
                        right=ast.Constant(value="$pageview"),
                    ),
                    ast.CompareOperation(
                        left=ast.Field(chain=["team_id"]),
                        op=ast.CompareOperationOp.Eq,
                        right=ast.Constant(value=1),
                    ),
                ]
            ),
        )
        
        optimized = optimize_pageview_queries(query, "clickhouse", None, self.context)
        
        # Should be optimized to use web_stats_combined
        assert isinstance(optimized.select_from.table, ast.Field)
        assert optimized.select_from.table.chain == ["web_stats_combined"]
        
        # Should preserve the team_id filter but remove the event filter
        assert optimized.where is not None
        assert isinstance(optimized.where, ast.CompareOperation)
        assert isinstance(optimized.where.left, ast.Field)
        assert optimized.where.left.chain == ["team_id"]

    def test_unsupported_aggregation_not_optimized(self):
        """Test that unsupported aggregations are not optimized"""
        query = ast.SelectQuery(
            select=[ast.Call(name="median", args=[ast.Field(chain=["properties", "price"])])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.CompareOperation(
                left=ast.Field(chain=["event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value="$pageview"),
            ),
        )
        
        optimized = optimize_pageview_queries(query, "clickhouse", None, self.context)
        
        # Should not be optimized - still querying events table
        assert isinstance(optimized.select_from.table, ast.Field)
        assert optimized.select_from.table.chain == ["events"]

    def test_is_pageview_optimizable(self):
        """Test the pageview optimizable detection logic"""
        optimizer = PageviewOptimizer(stack=None, context=self.context, dialect="clickhouse")
        
        # Valid pageview query
        valid_query = ast.SelectQuery(
            select=[ast.Call(name="count", args=[])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.CompareOperation(
                left=ast.Field(chain=["event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value="$pageview"),
            ),
        )
        
        assert optimizer._is_pageview_optimizable(valid_query) is True
        
        # Invalid query - not from events table
        invalid_query = ast.SelectQuery(
            select=[ast.Call(name="count", args=[])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["sessions"])),
            where=ast.CompareOperation(
                left=ast.Field(chain=["event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value="$pageview"),
            ),
        )
        
        assert optimizer._is_pageview_optimizable(invalid_query) is False

    def test_pageview_filter_detection(self):
        """Test pageview filter detection logic"""
        optimizer = PageviewOptimizer(stack=None, context=self.context, dialect="clickhouse")
        
        # Test single pageview filter
        pageview_filter = ast.CompareOperation(
            left=ast.Field(chain=["event"]),
            op=ast.CompareOperationOp.Eq,
            right=ast.Constant(value="$pageview"),
        )
        
        assert optimizer._contains_pageview_filter(pageview_filter) is True
        
        # Test screen event filter
        screen_filter = ast.CompareOperation(
            left=ast.Field(chain=["event"]),
            op=ast.CompareOperationOp.Eq,
            right=ast.Constant(value="$screen"),
        )
        
        assert optimizer._contains_pageview_filter(screen_filter) is True
        
        # Test non-pageview filter
        other_filter = ast.CompareOperation(
            left=ast.Field(chain=["event"]),
            op=ast.CompareOperationOp.Eq,
            right=ast.Constant(value="custom_event"),
        )
        
        assert optimizer._contains_pageview_filter(other_filter) is False

    def test_supported_aggregation_detection(self):
        """Test supported aggregation detection"""
        optimizer = PageviewOptimizer(stack=None, context=self.context, dialect="clickhouse")
        
        # Supported aggregations
        supported_calls = [
            ast.Call(name="count", args=[]),
            ast.Call(name="countIf", args=[]),
            ast.Call(name="uniq", args=[]),
            ast.Call(name="uniqIf", args=[]),
            ast.Call(name="sum", args=[]),
            ast.Call(name="avg", args=[]),
        ]
        
        for call in supported_calls:
            assert optimizer._is_supported_aggregation(call) is True
        
        # Unsupported aggregation
        unsupported_call = ast.Call(name="median", args=[])
        assert optimizer._is_supported_aggregation(unsupported_call) is False
        
        # Non-call expressions should be considered supported
        field = ast.Field(chain=["timestamp"])
        assert optimizer._is_supported_aggregation(field) is True