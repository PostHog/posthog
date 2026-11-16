import dataclasses
from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.workload import Workload
from posthog.models import Organization, Team

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.data_catalog.backend.facade.contracts import AgentSource, ChartSource, SurfaceSource, UncoveredGroup
from products.data_catalog.backend.facade.enums import ShapeOutcome
from products.data_catalog.backend.logic.usage_proposed_metrics import (
    STORED_CHART_SOURCES,
    ChartName,
    MeasureEvidence,
    ShapeSourceRow,
    build_proposed_metrics,
    fetch_chart_names,
    fetch_shape_sources,
)
from products.data_catalog.backend.logic.usage_uncovered import HUMAN_QUERY_FILTER, HUMAN_QUERY_PARAMETERS
from products.product_analytics.backend.facade.models import Insight

AT = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
PEOPLE = {user_id: f"person-{user_id}" for user_id in range(1, 20)}


def _group(digest: str, draft: str | None, runs: int = 10) -> UncoveredGroup:
    return UncoveredGroup(
        fingerprint_digest=digest,
        measure=f"measure {digest}",
        outcome=ShapeOutcome.UNCOVERED,
        matched_metric_id=None,
        distinct_people=2,
        built=runs,
        sample_sql="SELECT 1",
        draft_name=draft,
        draft_description=f"{draft} description",
        draft_definition=f"SELECT {draft}",
    )


def _evidence(
    *hashes: int,
    people: tuple[str, ...] = ("person-1",),
    agents: tuple[str, ...] = (),
    sessions: tuple[str, ...] = (),
    agent_runs: int = 0,
) -> MeasureEvidence:
    return MeasureEvidence(
        people=frozenset(people),
        shape_hashes=frozenset(hashes),
        agent_people=frozenset(agents),
        agent_sessions=frozenset(sessions),
        agent_runs=agent_runs,
    )


def _row(
    query_hash: int,
    users: tuple[int, ...],
    runs: int,
    insight: int = 0,
    dashboard: int = 0,
    product: str = "sql_editor",
) -> ShapeSourceRow:
    return ShapeSourceRow(
        query_hash=query_hash,
        insight_id=insight,
        dashboard_id=dashboard,
        product=product,
        user_ids=frozenset(users),
        runs=runs,
    )


class TestBuildProposedMetrics(SimpleTestCase):
    def test_measures_with_one_draft_merge_without_counting_a_shared_query_twice(self) -> None:
        groups = [_group("a", "signups", runs=9), _group("b", "signups", runs=5), _group("c", "revenue", runs=1)]
        evidence = {
            "a": _evidence(1, 2, people=("person-1", "person-2")),
            "b": _evidence(1, people=("person-2", "person-3")),
            "c": _evidence(3, people=("person-9",)),
        }
        rows = [
            _row(1, (1, 2), 8, insight=100, dashboard=200, product="product_analytics"),
            _row(2, (3,), 2, insight=100, dashboard=200, product="product_analytics"),
            _row(2, (1,), 2, insight=101, dashboard=300, product="product_analytics"),
            _row(2, (3,), 2, insight=101, dashboard=301, product="product_analytics"),
            _row(2, (4,), 3, product="sql_editor"),
            _row(1, (2,), 400, product="canvas"),
            _row(2, (2,), 300, product="canvas"),
            _row(3, (9,), 1, insight=999, dashboard=0, product="product_analytics"),
        ]
        names = {
            100: ChartName(short_id="abc", name="Signups", dashboards={200: "Growth"}),
            101: ChartName(short_id="def", name="Moved chart", dashboards={}),
        }

        proposals = build_proposed_metrics(groups, evidence, rows, names, PEOPLE)

        assert [proposal.name for proposal in proposals] == ["signups", "revenue"]
        signups = proposals[0]
        assert (signups.measures, signups.people, signups.built) == (2, 3, 9)
        assert signups.charts == [
            ChartSource(
                insight_short_id="abc",
                insight_name="Signups",
                dashboard_id=200,
                dashboard_name="Growth",
                people=3,
            ),
            ChartSource(
                insight_short_id="def",
                insight_name="Moved chart",
                dashboard_id=None,
                dashboard_name=None,
                people=2,
            ),
        ]
        assert signups.surfaces == [
            SurfaceSource(product="canvas", people=1, runs=700),
            SurfaceSource(product="sql_editor", people=1, runs=3),
        ]
        assert signups.agents is None
        # The chart behind "revenue" has no live name, so it is not listed.
        assert proposals[1].charts == []

    def test_agent_sessions_union_across_measures_and_charts_keep_the_top_ones(self) -> None:
        groups = [_group("a", "errors"), _group("b", "errors")]
        evidence = {
            "a": _evidence(1, agents=("person-1", "person-2"), sessions=("s1", "s2"), agent_runs=4),
            "b": _evidence(1, agents=("person-2",), sessions=("s2", "s3"), agent_runs=3),
        }
        chart_count = STORED_CHART_SOURCES + 2
        people = {user_id: f"person-{user_id}" for user_id in range(1, chart_count + 2)}
        rows = [
            _row(1, tuple(range(1, insight + 2)), 1, insight=insight, product="product_analytics")
            for insight in range(1, chart_count + 1)
        ]
        names = {
            insight: ChartName(short_id=f"s{insight}", name=f"Chart {insight}", dashboards={})
            for insight in range(1, chart_count + 1)
        }

        proposal = build_proposed_metrics(groups, evidence, rows, names, people)[0]

        assert proposal.agents == AgentSource(people=2, sessions=3, runs=4)
        assert proposal.charts[0].insight_name == f"Chart {chart_count}"
        assert len(proposal.charts) == STORED_CHART_SOURCES
        assert proposal.other_charts == 2
        assert proposal.fingerprint_digests == ["a", "b"]
        assert proposal.charts[0].dashboard_id is None

    def test_a_dashboard_that_no_longer_holds_the_chart_is_not_named(self) -> None:
        rows = [_row(1, (1,), 2, insight=5, dashboard=77, product="product_analytics")]
        names = {5: ChartName(short_id="s", name="Chart", dashboards={})}

        proposal = build_proposed_metrics([_group("a", "x")], {"a": _evidence(1)}, rows, names, PEOPLE)[0]

        assert (proposal.charts[0].dashboard_id, proposal.charts[0].dashboard_name) == (None, None)

    def test_one_name_with_two_definitions_stays_two_proposals(self) -> None:
        groups = [_group("a", "signups"), dataclasses.replace(_group("b", "signups"), draft_definition="SELECT other")]

        proposals = build_proposed_metrics(groups, {"a": _evidence(1), "b": _evidence(2)}, [], {}, PEOPLE)

        assert sorted((proposal.name, proposal.definition, proposal.measures) for proposal in proposals) == [
            ("signups", "SELECT other", 1),
            ("signups", "SELECT signups", 1),
        ]


class TestFetchSources(ClickhouseTestMixin, BaseTest):
    def _log(self, query: str, user: int, insight: int, dashboard: int, method: str = "", at: datetime = AT) -> None:
        sync_execute(
            """INSERT INTO sharded_query_log_archive_v3
            (initial_query_start_time, initial_query_id, event_time_microseconds, team_id, type, is_initial_query,
             normalized_query_hash, lc_query__query, lc_user_id, lc_access_method, lc_product, lc_feature,
             lc_insight_id, lc_dashboard_id) VALUES""",
            [
                (
                    # The archive TTL reads this column, so it holds the real time. The reads filter on the event time.
                    datetime.now(UTC),
                    f"q{query}{user}{insight}{dashboard}{method}{at}",
                    at,
                    self.team.id,
                    "QueryFinish",
                    1,
                    # Every query shares one normalized hash, so the read must tell them apart by their text.
                    0,
                    query,
                    user,
                    method,
                    "product_analytics",
                    "query",
                    insight,
                    dashboard,
                )
            ],
            workload=Workload.OFFLINE,
        )

    # The archive table is not cleared between tests, so each case reads its own day.
    @parameterized.expand([("one_batch", 50_000, AT), ("one_hash_per_batch", 1, AT + timedelta(days=7))])
    def test_reads_only_the_requested_queries_with_the_scan_filter(self, _name: str, batch: int, at: datetime) -> None:
        for query, user, insight, dashboard, method in [
            ("SELECT 1", 7, 100, 200, ""),
            ("SELECT 1", 8, 100, 200, ""),
            ("SELECT 1", 9, 0, 0, ""),
            ("SELECT 1", 7, 300, 0, "api"),
            ("SELECT 2", 7, 400, 0, ""),
            ("SELECT 3", 7, 500, 0, ""),
        ]:
            self._log(query, user, insight, dashboard, method, at=at)
        [[first, second]] = sync_execute("SELECT cityHash64('SELECT 1'), cityHash64('SELECT 2')")

        with patch("products.data_catalog.backend.logic.usage_proposed_metrics._HASH_BATCH", batch):
            rows = fetch_shape_sources(
                team=self.team,
                window_start=at - timedelta(days=1),
                window_end=at + timedelta(days=1),
                query_hashes={first, second},
                where=HUMAN_QUERY_FILTER,
                parameters=HUMAN_QUERY_PARAMETERS,
            )

        assert sorted((row.insight_id, row.dashboard_id, row.user_ids, row.runs) for row in rows) == [
            (0, 0, frozenset({9}), 1),
            (100, 200, frozenset({7, 8}), 2),
            (400, 0, frozenset({7}), 1),
        ]

    def test_chart_names_stay_inside_the_team_and_skip_deleted_ones(self) -> None:
        other_org = Organization.objects.create(name="Other")
        other_team = Team.objects.create(organization=other_org, name="Other")
        live = Insight.objects.create(team=self.team, name="Live", short_id="live1")
        derived = Insight.objects.create(team=self.team, derived_name="Derived", short_id="drvd1")
        deleted = Insight.objects.create(team=self.team, name="Deleted", deleted=True)
        foreign = Insight.objects.create(team=other_team, name="Foreign")
        dashboard = Dashboard.objects.create(team=self.team, name="Growth")
        old_dashboard = Dashboard.objects.create(team=self.team, name="Old", deleted=True)
        left_dashboard = Dashboard.objects.create(team=self.team, name="Left")
        DashboardTile.objects.create(dashboard=dashboard, insight=live)
        DashboardTile.objects.create(dashboard=old_dashboard, insight=live)
        DashboardTile.objects.create(dashboard=left_dashboard, insight=live, deleted=True)

        names = fetch_chart_names(team=self.team, insight_ids={live.id, derived.id, deleted.id, foreign.id})

        assert names == {
            live.id: ChartName(short_id="live1", name="Live", dashboards={dashboard.id: "Growth"}),
            derived.id: ChartName(short_id="drvd1", name="Derived", dashboards={}),
        }
