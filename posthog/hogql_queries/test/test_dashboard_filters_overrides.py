from collections.abc import Callable

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import (
    DashboardFilter,
    EventsNode,
    FunnelsQuery,
    IntervalType,
    LifecycleQuery,
    PathsFilter,
    PathsQuery,
    RetentionFilter,
    RetentionQuery,
    StickinessQuery,
    TrendsQuery,
)

from posthog.hogql_queries.insights.funnels.funnels_query_runner import FunnelsQueryRunner
from posthog.hogql_queries.insights.lifecycle.lifecycle_query_runner import LifecycleQueryRunner
from posthog.hogql_queries.insights.retention.retention_query_runner import RetentionQueryRunner
from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.models import Team

from products.product_analytics.backend.hogql_queries.paths.paths_query_runner import PathsQueryRunner
from products.product_analytics.backend.hogql_queries.stickiness.stickiness_query_runner import StickinessQueryRunner

_TIME_SERIES = [EventsNode(event="$pageview")]

# Runners whose query model carries an `interval` field.
INTERVAL_QUERY_RUNNERS: list[tuple[str, Callable[[Team], QueryRunner]]] = [
    (
        "trends",
        lambda team: TrendsQueryRunner(query=TrendsQuery(series=_TIME_SERIES, interval=IntervalType.DAY), team=team),
    ),
    (
        "funnels",
        lambda team: FunnelsQueryRunner(query=FunnelsQuery(series=_TIME_SERIES), team=team),
    ),
    (
        "stickiness",
        lambda team: StickinessQueryRunner(
            query=StickinessQuery(series=_TIME_SERIES, interval=IntervalType.DAY), team=team
        ),
    ),
    (
        "lifecycle",
        lambda team: LifecycleQueryRunner(
            query=LifecycleQuery(series=_TIME_SERIES, interval=IntervalType.DAY), team=team
        ),
    ),
]

# Runners whose query model has no `interval` field.
NON_INTERVAL_QUERY_RUNNERS: list[tuple[str, Callable[[Team], QueryRunner]]] = [
    (
        "retention",
        lambda team: RetentionQueryRunner(query=RetentionQuery(retentionFilter=RetentionFilter()), team=team),
    ),
    (
        "paths",
        lambda team: PathsQueryRunner(query=PathsQuery(pathsFilter=PathsFilter()), team=team),
    ),
]

# Every supported query type carries a `filterTestAccounts` field.
ALL_QUERY_RUNNERS = INTERVAL_QUERY_RUNNERS + NON_INTERVAL_QUERY_RUNNERS


class TestDashboardFiltersIntervalOverride(BaseTest):
    def _runner(self, build: Callable[[Team], QueryRunner]) -> QueryRunner:
        return build(self.team)

    @parameterized.expand(INTERVAL_QUERY_RUNNERS)
    def test_interval_override_written_onto_interval_supporting_query(self, _name, build):
        runner = self._runner(build)

        runner.apply_dashboard_filters(DashboardFilter(interval=IntervalType.WEEK))

        assert runner.query.interval == IntervalType.WEEK

    @parameterized.expand(NON_INTERVAL_QUERY_RUNNERS)
    def test_interval_override_silently_skipped_for_non_interval_query(self, _name, build):
        runner = self._runner(build)

        runner.apply_dashboard_filters(DashboardFilter(interval=IntervalType.WEEK))

        assert not hasattr(runner.query, "interval")

    @parameterized.expand(INTERVAL_QUERY_RUNNERS)
    def test_absent_interval_leaves_query_interval_untouched(self, _name, build):
        runner = self._runner(build)
        original = runner.query.interval

        runner.apply_dashboard_filters(DashboardFilter())

        assert runner.query.interval == original


class TestDashboardFiltersTestAccountsOverride(BaseTest):
    def _runner(self, build: Callable[[Team], QueryRunner]) -> QueryRunner:
        return build(self.team)

    @parameterized.expand(ALL_QUERY_RUNNERS)
    def test_test_accounts_override_forces_on(self, _name, build):
        runner = self._runner(build)

        runner.apply_dashboard_filters(DashboardFilter(filterTestAccounts=True))

        assert runner.query.filterTestAccounts is True

    @parameterized.expand(ALL_QUERY_RUNNERS)
    def test_test_accounts_override_forces_off(self, _name, build):
        runner = self._runner(build)
        runner.query.filterTestAccounts = True

        runner.apply_dashboard_filters(DashboardFilter(filterTestAccounts=False))

        assert runner.query.filterTestAccounts is False

    @parameterized.expand(ALL_QUERY_RUNNERS)
    def test_inherit_leaves_query_test_accounts_untouched(self, _name, build):
        runner = self._runner(build)
        runner.query.filterTestAccounts = True

        runner.apply_dashboard_filters(DashboardFilter())

        assert runner.query.filterTestAccounts is True
