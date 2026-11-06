import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.test import SimpleTestCase

from parameterized import parameterized

from products.data_catalog.backend.facade.enums import JudgeRelation, MetricStatus
from products.data_catalog.backend.logic.measure_fingerprint import extract_measures
from products.data_catalog.backend.logic.metric_fingerprint import CatalogIndex, CatalogMeasure
from products.data_catalog.backend.logic.usage_adjusted import (
    AgentQuery,
    CatalogCall,
    assemble_adjusted_runs,
    build_candidate_groups,
    fetch_agent_queries,
    fetch_catalog_calls,
    read_metric_first,
    select_for_judging,
)
from products.data_catalog.backend.logic.usage_judge import JudgeVerdict

SIGNUPS = "SELECT count() FROM events WHERE event = 'signup'"
SIGNUPS_ID = UUID("00000000-0000-0000-0000-000000000001")
AT = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def _query(sql: str = SIGNUPS, *, trace: str = "t1", is_scout: bool = False, at: datetime = AT) -> AgentQuery:
    return AgentQuery(
        occurred_at=at, trace_id=trace, distinct_id="d1", intent="weekly signups", sql=sql, is_scout=is_scout
    )


def _call(tool: str, metric_name: str = "", *, trace: str = "t1", minutes: int = -1) -> CatalogCall:
    return CatalogCall(trace_id=trace, occurred_at=AT + timedelta(minutes=minutes), tool=tool, metric_name=metric_name)


def _index() -> CatalogIndex:
    return CatalogIndex(
        CatalogMeasure(
            metric_id=SIGNUPS_ID,
            status=MetricStatus.APPROVED,
            created_at=AT,
            fingerprint=fingerprint,
        )
        for fingerprint in extract_measures(SIGNUPS)
    )


class TestAdjustedRunDetection(SimpleTestCase):
    @parameterized.expand(
        [
            ("described_first", [_call("metric-describe", "signups")], True),
            ("ran_first", [_call("data-catalog-metric-run", "signups")], True),
            ("described_after_the_query", [_call("metric-describe", "signups", minutes=1)], False),
            ("listed_only", [_call("metric-list")], False),
            ("described_another_metric", [_call("metric-describe", "revenue")], False),
            ("other_session", [_call("metric-describe", "signups", trace="t2")], False),
        ]
    )
    def test_read_metric_first(self, _name: str, calls: list[CatalogCall], expected: bool) -> None:
        assert read_metric_first(_query(), "signups", calls) is expected

    def test_repeated_sql_is_judged_once_and_scout_only_groups_go_last(self) -> None:
        sliced = "SELECT count() FROM events WHERE event = 'signup' AND properties.plan = 'pro'"
        groups = build_candidate_groups(
            [
                _query(sliced, is_scout=True),
                _query(sliced, is_scout=True),
                _query(),
                _query(trace="t2"),
                _query("SELECT sum(properties.amount) FROM events"),
            ],
            _index(),
        )

        selection = select_for_judging(groups, cap=1)

        assert sorted(len(group.occurrences) for group in groups) == [2, 2]
        assert [group.sql for group in selection.groups] == [SIGNUPS]
        assert selection.over_cap == 1

    def test_only_matching_verdicts_become_runs(self) -> None:
        groups = build_candidate_groups([_query(), _query(trace="t2", is_scout=True)], _index())
        verdicts = [JudgeVerdict(relation=JudgeRelation.SERVES, confidence=0.9, reasoning="Same measure.")]

        runs = assemble_adjusted_runs(
            groups, verdicts, {SIGNUPS_ID: "signups"}, {"t1": [_call("metric-describe", "signups")]}
        )
        dropped = assemble_adjusted_runs(
            groups,
            [JudgeVerdict(relation=JudgeRelation.DIFFERENT, confidence=0.9, reasoning="Other purpose.")],
            {SIGNUPS_ID: "signups"},
            {},
        )

        assert [(run.read_metric_first, run.is_scout) for run in runs] == [(True, False), (False, True)]
        assert dropped == []


class TestAgentTelemetryQueries(ClickhouseTestMixin, BaseTest):
    def _telemetry(self, event: str, span: str, trace: str, at: datetime, **properties: object) -> None:
        # _create_event also writes the ai_events row, so each event is seeded once.
        _create_event(
            team=self.team,
            event=event,
            distinct_id="d1",
            timestamp=at,
            properties={
                "$ai_trace_id": trace,
                "$ai_span_name": span,
                "$mcp_project_uuid": str(self.team.uuid),
                **properties,
            },
        )

    def test_reads_agent_sql_and_catalog_calls_from_the_telemetry_project(self) -> None:
        end = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
        at = end - timedelta(hours=2)
        self._telemetry(
            "$ai_generation",
            "execute-sql",
            "t1",
            at,
            **{
                "$ai_input": [{"role": "user", "content": "weekly signups"}],
                "$ai_output_choices": [{"role": "assistant", "content": SIGNUPS}],
                "source": "self_driving",
            },
        )
        self._telemetry(
            "$ai_span",
            "metric-describe",
            "t1",
            at - timedelta(minutes=1),
            **{"$ai_input_state": json.dumps({"name": "signups"})},
        )
        self._telemetry(
            "$ai_generation",
            "execute-sql",
            "other-region",
            at,
            **{
                "$ai_input": [{"role": "user", "content": "weekly signups"}],
                "$ai_output_choices": [{"role": "assistant", "content": SIGNUPS}],
                "$mcp_project_id": str(self.team.id),
                "$mcp_project_uuid": str(uuid4()),
            },
        )
        flush_persons_and_events()

        queries = fetch_agent_queries(
            team=self.team, telemetry_team=self.team, window_start=end - timedelta(days=2), window_end=end
        )
        calls = fetch_catalog_calls(
            team=self.team, telemetry_team=self.team, window_start=end - timedelta(days=2), window_end=end
        )

        assert [(query.trace_id, query.intent, query.sql, query.is_scout) for query in queries] == [
            ("t1", "weekly signups", SIGNUPS, True)
        ]
        assert [(call.tool, call.metric_name) for call in calls["t1"]] == [("metric-describe", "signups")]
