from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.test import SimpleTestCase

from parameterized import parameterized

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.data_catalog.backend.facade.enums import CreatedSource, MetricStatus, RelationshipStatus
from products.data_catalog.backend.logic.discovery import (
    InsightSignal,
    JoinEdge,
    MetricCandidate,
    RelationshipCandidate,
    SqlGroupSummary,
    SqlUsageSignal,
    apply_candidates,
    build_report,
    collect_endpoint_usage,
    collect_insight_signals,
    collect_sql_usage,
    distill_sql,
    group_sql_signals,
)
from products.data_catalog.backend.models import Metric, RelationshipProposal
from products.product_analytics.backend.facade.models import Insight

_TRENDS_INSIGHT_QUERY = {
    "kind": "InsightVizNode",
    "source": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
}


def _sql_metric_report(run_count: int = 10, **overrides):
    signals = [
        SqlUsageSignal(
            sql="SELECT toStartOfMonth(timestamp) AS month, count() FROM events GROUP BY month",
            run_count=run_count,
            user_count=2,
        )
    ]
    return build_report(sql_signals=signals, insight_signals=[], days=30, **overrides)


class TestDistillSql(SimpleTestCase):
    def test_extracts_shape(self) -> None:
        shape = distill_sql(
            "SELECT toStartOfMonth(timestamp) AS month, count() AS c, uniq(person_id) "
            "FROM events WHERE timestamp > '2025-01-01' GROUP BY month"
        )
        assert shape is not None
        assert shape.tables == ("events",)
        assert shape.aggregations == ("count", "uniq")
        assert shape.time_grain == "month"
        assert shape.group_keys == ("month",)

    @parameterized.expand(
        [
            (
                "date_literal",
                "SELECT count() FROM events WHERE timestamp > '2025-01-01'",
                "SELECT count() FROM events WHERE timestamp > '2025-06-15'",
            ),
            (
                "numeric_literal",
                "SELECT count() FROM events LIMIT 10",
                "SELECT count() FROM events LIMIT 500",
            ),
        ]
    )
    def test_literal_variants_share_a_fingerprint(self, _name: str, sql_a: str, sql_b: str) -> None:
        shape_a, shape_b = distill_sql(sql_a), distill_sql(sql_b)
        assert shape_a is not None and shape_b is not None
        assert shape_a.fingerprint == shape_b.fingerprint

    def test_structural_variants_get_different_fingerprints(self) -> None:
        shape_a = distill_sql("SELECT count() FROM events WHERE timestamp > '2025-01-01'")
        shape_b = distill_sql("SELECT count() FROM events WHERE timestamp > '2025-01-01' AND event = 'x'")
        assert shape_a is not None and shape_b is not None
        assert shape_a.fingerprint != shape_b.fingerprint

    def test_unparseable_sql_returns_none(self) -> None:
        assert distill_sql("INSERT INTO events VALUES (1)") is None

    def test_join_edges_are_canonical_across_orientation_and_aliases(self) -> None:
        shape_a = distill_sql("SELECT count() FROM events AS e JOIN persons AS p ON e.person_id = p.id")
        shape_b = distill_sql("SELECT count() FROM persons p JOIN events e ON p.id = e.person_id")
        assert shape_a is not None and shape_b is not None
        expected = JoinEdge(source_table="events", source_key="person_id", joining_table="persons", joining_key="id")
        assert shape_a.join_edges == (expected,)
        assert shape_b.join_edges == (expected,)

    def test_cte_names_are_not_tables_and_cte_joins_are_not_edges(self) -> None:
        shape = distill_sql(
            "WITH recent AS (SELECT event, person_id FROM events) "
            "SELECT count() FROM recent r JOIN persons p ON r.person_id = p.id"
        )
        assert shape is not None
        assert shape.tables == ("events", "persons")
        assert shape.join_edges == ()

    def test_parameterized_queries_distill_and_keep_placeholder_identity(self) -> None:
        shape_a = distill_sql(
            "SELECT count(DISTINCT t.id) FROM zendesk_tickets t JOIN zendesk_groups g ON t.group_id = g.id "
            "WHERE g.name = {variables.support_group}"
        )
        shape_b = distill_sql(
            "SELECT count(DISTINCT t.id) FROM zendesk_tickets t JOIN zendesk_groups g ON t.group_id = g.id "
            "WHERE g.name = {variables.other_group}"
        )
        assert shape_a is not None and shape_b is not None
        assert len(shape_a.join_edges) == 1
        assert shape_a.fingerprint != shape_b.fingerprint


class TestBuildReport(SimpleTestCase):
    def test_recurring_aggregate_sql_becomes_a_metric_candidate(self) -> None:
        report = _sql_metric_report(run_count=10)
        assert len(report.metric_candidates) == 1
        candidate = report.metric_candidates[0]
        assert candidate.name == "monthly_count_events_by_month"
        assert candidate.definition is not None and candidate.definition["kind"] == "HogQLQuery"
        assert candidate.evidence["run_count"] == 10

    def test_sql_below_run_threshold_is_not_proposed(self) -> None:
        report = _sql_metric_report(run_count=2, min_sql_runs=5)
        assert report.metric_candidates == ()

    def test_literal_variants_group_and_sum_runs(self) -> None:
        signals = [
            SqlUsageSignal(sql="SELECT count() FROM events WHERE timestamp > '2025-01-01'", run_count=4, user_count=1),
            SqlUsageSignal(sql="SELECT count() FROM events WHERE timestamp > '2025-02-01'", run_count=3, user_count=2),
        ]
        groups = group_sql_signals(signals)
        assert len(groups) == 1
        assert groups[0].run_count == 7
        assert groups[0].variant_count == 2

    def test_meta_only_queries_are_dropped(self) -> None:
        signals = [
            SqlUsageSignal(sql="SELECT count() FROM query_log", run_count=50, user_count=5),
            SqlUsageSignal(sql="SELECT * FROM system.information_schema.tables", run_count=50, user_count=5),
        ]
        assert group_sql_signals(signals) == []

    def test_dashboard_insight_becomes_a_linked_metric_candidate(self) -> None:
        signal = InsightSignal(
            short_id="abc123",
            title="Churn rate MoM",
            description="",
            dashboard_names=("Churn analysis",),
            source_kind="TrendsQuery",
            run_count=12,
        )
        report = build_report(sql_signals=[], insight_signals=[signal], days=30)
        assert len(report.metric_candidates) == 1
        candidate = report.metric_candidates[0]
        assert candidate.name == "churn_rate_mom"
        assert candidate.source_insight_short_id == "abc123"
        assert candidate.definition is None
        assert "Churn analysis" in candidate.reasoning

    @parameterized.expand(
        [
            ("unsupported_kind", "RetentionQuery", ("Churn analysis",), 5),
            ("no_dashboards_no_runs", "TrendsQuery", (), 0),
        ]
    )
    def test_insights_without_signal_or_support_are_skipped(
        self, _name: str, kind: str, dashboards: tuple, runs: int
    ) -> None:
        signal = InsightSignal(
            short_id="abc123",
            title="Some insight",
            description="",
            dashboard_names=dashboards,
            source_kind=kind,
            run_count=runs,
        )
        report = build_report(sql_signals=[], insight_signals=[signal], days=30)
        assert report.metric_candidates == ()

    def test_existing_metric_name_skips_the_candidate(self) -> None:
        signal = InsightSignal(
            short_id="abc123",
            title="Churn rate MoM",
            description="",
            dashboard_names=("Churn analysis",),
            source_kind="TrendsQuery",
            run_count=0,
        )
        report = build_report(
            sql_signals=[],
            insight_signals=[signal],
            days=30,
            existing_metric_names=frozenset({"churn_rate_mom"}),
        )
        assert report.metric_candidates == ()

    def test_intra_report_name_collisions_get_suffixes(self) -> None:
        signals = [
            InsightSignal(
                short_id=f"id{i}",
                title="Churn rate",
                description="",
                dashboard_names=("Churn analysis",),
                source_kind="TrendsQuery",
                run_count=i,
            )
            for i in range(2)
        ]
        report = build_report(sql_signals=[], insight_signals=signals, days=30)
        assert sorted(c.name for c in report.metric_candidates) == ["churn_rate", "churn_rate_2"]

    # Structurally different queries sharing one join: literal-only variants would collapse
    # into a single shape and count as one occurrence.
    _JOIN_QUERY_SHAPES = [
        "SELECT count() FROM persons p JOIN events e ON p.id = e.person_id",
        "SELECT uniq(e.event) FROM persons p JOIN events e ON p.id = e.person_id",
        "SELECT max(e.timestamp), count() FROM persons p JOIN events e ON p.id = e.person_id GROUP BY p.id",
    ]

    def test_repeated_join_becomes_a_relationship_candidate(self) -> None:
        signals = [SqlUsageSignal(sql=sql, run_count=4, user_count=1) for sql in self._JOIN_QUERY_SHAPES]
        report = build_report(sql_signals=signals, insight_signals=[], days=30, min_join_occurrences=3)
        assert len(report.relationship_candidates) == 1
        candidate = report.relationship_candidates[0]
        assert candidate.source_table_name == "events"
        assert candidate.source_table_key == "person_id"
        assert candidate.joining_table_name == "persons"
        assert candidate.joining_table_key == "id"
        assert candidate.evidence["distinct_query_shapes"] == 3

    def test_known_join_pairs_are_not_re_proposed(self) -> None:
        signals = [SqlUsageSignal(sql=sql, run_count=4, user_count=1) for sql in self._JOIN_QUERY_SHAPES]
        existing = frozenset({frozenset({("events", "person_id"), ("persons", "id")})})
        report = build_report(
            sql_signals=signals,
            insight_signals=[],
            days=30,
            min_join_occurrences=3,
            existing_join_pairs=existing,
        )
        assert report.relationship_candidates == ()

    def test_llm_summary_overrides_heuristic_naming(self) -> None:
        summary = SqlGroupSummary(
            name="monthly_active_events",
            display_name="Monthly active events",
            description="Events counted per calendar month.",
            unit="events",
        )
        report = _sql_metric_report(run_count=10, summarize_sql_group=lambda group: summary)
        candidate = report.metric_candidates[0]
        assert candidate.name == "monthly_active_events"
        assert candidate.description == "Events counted per calendar month."
        assert candidate.unit == "events"

    def test_failing_summarizer_falls_back_to_heuristic(self) -> None:
        def broken(group):
            raise RuntimeError("llm down")

        report = _sql_metric_report(run_count=10, summarize_sql_group=broken)
        assert report.metric_candidates[0].name == "monthly_count_events_by_month"


class TestSignalCollection(ClickhouseTestMixin, BaseTest):
    def test_query_log_collectors_resolve_against_the_schema(self) -> None:
        assert collect_sql_usage(self.team, days=7, min_runs=1, limit=10) == []
        assert collect_endpoint_usage(self.team, days=7) == {}

    def test_collect_insight_signals_reads_dashboards_and_skips_deleted(self) -> None:
        insight = Insight.objects.create(team=self.team, name="Churn rate MoM", query=_TRENDS_INSIGHT_QUERY)
        Insight.objects.create(team=self.team, name="", derived_name="", query=_TRENDS_INSIGHT_QUERY)
        dashboard = Dashboard.objects.create(team=self.team, name="Churn analysis")
        deleted_dashboard = Dashboard.objects.create(team=self.team, name="Old board", deleted=True)
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)
        DashboardTile.objects.create(dashboard=deleted_dashboard, insight=insight)

        signals = collect_insight_signals(self.team, endpoint_usage={f"Insight/{insight.short_id}": 7})

        assert len(signals) == 1
        assert signals[0].title == "Churn rate MoM"
        assert signals[0].dashboard_names == ("Churn analysis",)
        assert signals[0].source_kind == "TrendsQuery"
        assert signals[0].run_count == 7


class TestApplyCandidates(BaseTest):
    def test_writes_proposed_ai_generated_rows_and_skips_existing(self) -> None:
        metric = MetricCandidate(
            name="recurring_event_count",
            display_name="Recurring event count",
            description="Total events, proposed from query history.",
            definition={"kind": "HogQLQuery", "query": "SELECT count() FROM events"},
            source_insight_short_id=None,
            unit="",
            confidence=0.6,
            reasoning="Ran repeatedly in the query log.",
            evidence={"signal": "query_history"},
        )
        relationship = RelationshipCandidate(
            source_table_name="events",
            source_table_key="distinct_id",
            joining_table_name="persons",
            joining_table_key="id",
            field_name="discovered_person",
            confidence=0.5,
            reasoning="Joined in 3 recurring query shapes.",
            evidence={"signal": "query_history"},
        )
        report = build_report(sql_signals=[], insight_signals=[], days=30)
        report = type(report)(
            metric_candidates=(metric,),
            relationship_candidates=(relationship,),
            sql_groups=report.sql_groups,
            stats=report.stats,
        )

        summary = apply_candidates(report, team=self.team, ai_model="test-model")

        assert summary.created_metrics == ("recurring_event_count",)
        assert summary.created_relationships == ("events -> persons",)
        created = Metric.objects.for_team(self.team.id).get(name="recurring_event_count")
        assert created.status == MetricStatus.PROPOSED
        assert created.created_source == CreatedSource.AI_GENERATED
        assert created.ai_model == "test-model"
        assert created.confidence == 0.6
        proposal = RelationshipProposal.objects.for_team(self.team.id).get()
        assert proposal.status == RelationshipStatus.PROPOSED
        assert proposal.field_name == "discovered_person"

        # A second apply must not refine the existing rows: both land as skips.
        summary_again = apply_candidates(report, team=self.team, ai_model="test-model")
        assert summary_again.created_metrics == ()
        assert summary_again.skipped_metrics[0].name == "recurring_event_count"
        assert summary_again.created_relationships == ()
        assert len(summary_again.skipped_relationships) == 1
