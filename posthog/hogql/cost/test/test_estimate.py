from datetime import UTC, datetime
from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import HogLanguage, HogQLMetadata

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.cost.estimate import DEFAULT_RANGE_DAYS, EventsScanEstimate, estimate_events_scan
from posthog.hogql.cost.statistics import EventVolume, FixedStatisticsProvider
from posthog.hogql.database.database import Database
from posthog.hogql.metadata import get_hogql_metadata
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import resolve_types

NOW = datetime(2026, 9, 11, tzinfo=UTC)
# 100k events per day, 60% pageviews, 40% signups.
VOLUME = EventVolume(total=1_000_000, by_event={"$pageview": 600_000, "signup": 400_000}, days=10)


class TestEstimateEventsScan(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.context = HogQLContext(
            database=Database.create_for(team=self.team), team_id=self.team.pk, enable_select_queries=True
        )
        self.provider = FixedStatisticsProvider(event_volume={self.team.pk: VOLUME})

    def _estimate(self, sql: str) -> EventsScanEstimate | None:
        node = cast(ast.SelectQuery, resolve_types(parse_select(sql), self.context, dialect="clickhouse"))
        return estimate_events_scan(node, self.context, self.provider, now=NOW)

    @parameterized.expand(
        [
            (
                "bounded_range_and_one_event",
                "SELECT count() FROM events WHERE timestamp > '2026-08-12' AND timestamp < '2026-09-11' AND event = '$pageview'",
                EventsScanEstimate(rows=1_800_000, days=30.0, events=("$pageview",), time_range="bounded"),
            ),
            (
                "relative_lower_bound_only",
                "SELECT count() FROM events WHERE timestamp > now() - interval 7 day",
                EventsScanEstimate(rows=700_000, days=7.0, events=(), time_range="open"),
            ),
            (
                "aliased_table_and_in_list_with_an_unseen_event",
                "SELECT count() FROM events AS e WHERE e.event IN ('signup', 'never_seen')",
                EventsScanEstimate(
                    rows=14_600_000, days=float(DEFAULT_RANGE_DAYS), events=("never_seen", "signup"), time_range="open"
                ),
            ),
            (
                "flipped_comparison_and_datetime_literal",
                "SELECT count() FROM events WHERE '2026-09-01 00:00:00' <= timestamp AND timestamp <= '2026-09-03 12:00:00'",
                EventsScanEstimate(rows=250_000, days=2.5, events=(), time_range="bounded"),
            ),
        ]
    )
    def test_estimates_events_only_selects(self, _name, sql, expected):
        assert self._estimate(sql) == expected

    @parameterized.expand(
        [
            ("or_between_events", "SELECT count() FROM events WHERE event = '$pageview' OR event = 'signup'"),
            ("negated_event", "SELECT count() FROM events WHERE NOT event = '$pageview'"),
            ("property_filter_is_ignored", "SELECT count() FROM events WHERE properties.$browser = 'Chrome'"),
            ("unparseable_bound", "SELECT count() FROM events WHERE timestamp > toStartOfMonth(now())"),
        ]
    )
    def test_predicates_it_cannot_narrow_on_widen_to_the_whole_table(self, _name, sql):
        assert self._estimate(sql) == EventsScanEstimate(
            rows=100_000 * DEFAULT_RANGE_DAYS, days=float(DEFAULT_RANGE_DAYS), events=(), time_range="open"
        )

    @parameterized.expand(
        [
            ("join", "SELECT count() FROM events e JOIN persons p ON p.id = e.person_id"),
            ("other_table", "SELECT count() FROM persons"),
            ("subquery_source", "SELECT count() FROM (SELECT event FROM events)"),
        ]
    )
    def test_shapes_outside_events_only_return_none(self, _name, sql):
        assert self._estimate(sql) is None

    def test_team_without_volume_returns_none(self):
        self.provider = FixedStatisticsProvider()

        assert self._estimate("SELECT count() FROM events") is None

    @parameterized.expand(
        [
            ("events_only_select", "select count() from events where event = 'signup'", 14_600_000),
            ("join_has_no_estimate", "select count() from events e join persons p on p.id = e.person_id", None),
        ]
    )
    def test_metadata_carries_the_estimate_when_the_flag_is_on(self, _name, sql, expected_rows):
        with (
            patch("posthog.hogql.metadata.feature_enabled_or_false", return_value=True),
            patch("posthog.hogql.metadata.ClickHouseStatisticsProvider", return_value=self.provider),
        ):
            response = get_hogql_metadata(
                HogQLMetadata(kind="HogQLMetadata", language=HogLanguage.HOG_QL, query=sql, indexUsage=True),
                self.team,
            )

        assert response.isValid is True
        if expected_rows is None:
            assert response.events_scan_estimate is None
        else:
            assert response.events_scan_estimate is not None
            assert response.events_scan_estimate.rows == expected_rows
            assert response.events_scan_estimate.events == ["signup"]

    def test_metadata_omits_the_estimate_when_the_flag_is_off(self):
        with patch("posthog.hogql.metadata.feature_enabled_or_false", return_value=False):
            response = get_hogql_metadata(
                HogQLMetadata(
                    kind="HogQLMetadata",
                    language=HogLanguage.HOG_QL,
                    query="select count() from events",
                    indexUsage=True,
                ),
                self.team,
            )

        assert response.events_scan_estimate is None
