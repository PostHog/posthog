import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase

from asgiref.sync import async_to_sync
from parameterized import parameterized

from products.data_catalog.backend.facade.enums import HOGQL_DEFINITION_KIND, JudgeRelation, MetricStatus
from products.data_catalog.backend.logic.measure_fingerprint import extract_measures
from products.data_catalog.backend.logic.metric_fingerprint import CatalogIndex, CatalogMeasure
from products.data_catalog.backend.logic.metrics import upsert_metric
from products.data_catalog.backend.logic.usage_adjusted import (
    AgentQuery,
    CatalogCall,
    JudgeUnavailable,
    UsagePageTruncated,
    _briefs,
    _DetectionPlan,
    _plan_detection,
    assemble_adjusted_runs,
    build_candidate_groups,
    detect_adjusted_runs_into_snapshot,
    fetch_agent_queries,
    fetch_catalog_calls,
    read_metric_first,
    select_for_judging,
)
from products.data_catalog.backend.logic.usage_judge import AIConsentMissing, JudgeVerdict, MetricBrief

_MODULE = "products.data_catalog.backend.logic.usage_adjusted"

SIGNUPS = "SELECT count() FROM events WHERE event = 'signup'"
SIGNUPS_ID = UUID("00000000-0000-0000-0000-000000000001")
AT = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def _query(
    sql: str = SIGNUPS,
    *,
    trace: str = "t1",
    is_scout: bool = False,
    at: datetime = AT,
    intent: str = "weekly signups",
) -> AgentQuery:
    return AgentQuery(occurred_at=at, trace_id=trace, distinct_id="d1", intent=intent, sql=sql, is_scout=is_scout)


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

    def test_repeated_sql_is_judged_once_per_intent_and_scout_only_groups_go_last(self) -> None:
        sliced = "SELECT count() FROM events WHERE event = 'signup' AND properties.plan = 'pro'"
        groups = build_candidate_groups(
            [
                _query(sliced, is_scout=True),
                _query(sliced, is_scout=True),
                _query(),
                _query(trace="t2", intent="  Weekly   SIGNUPS "),
                _query(trace="t3", intent="signups from the launch campaign"),
                _query("SELECT sum(properties.amount) FROM events"),
            ],
            _index(),
        )

        selection = select_for_judging(groups, cap=1)

        assert sorted(len(group.occurrences) for group in groups) == [1, 2, 2]
        assert [(group.sql, group.intent) for group in selection.groups] == [(SIGNUPS, "weekly signups")]
        assert selection.over_cap == 2

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

    def test_a_capped_section_keeps_the_newest_runs(self) -> None:
        groups = build_candidate_groups([_query(), _query(trace="t2", at=AT + timedelta(hours=1))], _index())
        verdicts = [JudgeVerdict(relation=JudgeRelation.SERVES, confidence=0.9, reasoning="Same measure.")]

        with patch(f"{_MODULE}._MAX_STORED_RUNS", 1):
            runs = assemble_adjusted_runs(groups, verdicts, {SIGNUPS_ID: "signups"}, {})

        assert [run.session_id for run in runs] == ["t2"]

    @parameterized.expand(
        [
            (
                "full_day_splits_until_every_row_fits",
                [AT.replace(hour=1), AT.replace(hour=9), AT.replace(hour=20)],
                None,
            ),
            (
                "full_page_at_the_one_hour_floor_fails",
                [AT.replace(hour=10, minute=10), AT.replace(hour=10, minute=20)],
                UsagePageTruncated,
            ),
        ]
    )
    def test_a_full_page_never_drops_rows(
        self, _name: str, times: list[datetime], error: type[Exception] | None
    ) -> None:
        stored = [(at, f"t{i}", "d1", "weekly signups", SIGNUPS, "mcp") for i, at in enumerate(times)]

        def clickhouse(*, placeholders: dict[str, Any], **_: Any) -> SimpleNamespace:
            start, end = placeholders["start"].value, placeholders["end"].value
            limit = placeholders["row_limit"].value
            return SimpleNamespace(results=[row for row in stored if start <= row[0] < end][:limit])

        day = AT.replace(hour=0)
        team = MagicMock(id=1, uuid=uuid4())
        with (
            patch(f"{_MODULE}.execute_hogql_query", side_effect=clickhouse),
            patch(f"{_MODULE}._PAGE_ROW_LIMIT", 2),
        ):
            if error is not None:
                with pytest.raises(error):
                    fetch_agent_queries(
                        team=team, telemetry_team=team, window_start=day, window_end=day + timedelta(days=1)
                    )
                return
            queries = fetch_agent_queries(
                team=team, telemetry_team=team, window_start=day, window_end=day + timedelta(days=1)
            )

        assert sorted(query.trace_id for query in queries) == ["t0", "t1", "t2"]

    @parameterized.expand(
        [
            ("every_call_fails", 2, 2, True),
            ("over_a_tenth_fails", 2, 10, True),
            ("a_tenth_fails", 1, 10, False),
        ]
    )
    def test_too_many_judge_failures_fail_the_step(self, _name: str, failing: int, total: int, raises: bool) -> None:
        groups = build_candidate_groups(
            [_query(f"{SIGNUPS} AND properties.plan = 'p{i}'") for i in range(total)], _index()
        )
        plan = _DetectionPlan(
            selection=select_for_judging(groups),
            briefs={SIGNUPS_ID: MetricBrief(name="signups", description="", definition=SIGNUPS)},
            calls_by_trace={},
        )

        async def create(**kwargs: Any) -> SimpleNamespace:
            prompt = kwargs["messages"][0]["content"]
            if any(f"'p{i}'" in prompt for i in range(failing)):
                raise RuntimeError("gateway down")
            text = '{"reasoning": "Same.", "relation": "slice", "confidence": 0.9}'
            return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])

        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=create)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        with (
            patch(f"{_MODULE}._plan_detection", return_value=plan),
            patch(f"{_MODULE}.build_async_anthropic_client", return_value=client),
            patch(f"{_MODULE}.write_payload_sections") as write,
        ):
            run = async_to_sync(detect_adjusted_runs_into_snapshot)
            if raises:
                with pytest.raises(JudgeUnavailable):
                    run(team_id=1, snapshot_id=uuid4(), telemetry_team_id=1, heartbeat=lambda: None)
                write.assert_not_called()
                return
            rows = run(team_id=1, snapshot_id=uuid4(), telemetry_team_id=1, heartbeat=lambda: None)

        assert rows == total - failing
        write.assert_called_once()


class TestPlanDetection(BaseTest):
    def test_a_metric_whose_brief_fails_is_skipped_not_the_scan(self) -> None:
        upsert_metric(team=self.team, user=self.user, name="mrr", description="Monthly revenue")

        with patch(f"{_MODULE}.definition_to_hogql", side_effect=RecursionError()):
            assert _briefs(self.team) == {}

    def test_a_hogql_brief_carries_its_placeholder_values(self) -> None:
        metric = upsert_metric(
            team=self.team,
            user=self.user,
            name="signups",
            description="Signups",
            definition={
                "kind": HOGQL_DEFINITION_KIND,
                "query": "SELECT count() FROM events WHERE event = {event}",
                "values": {"event": "signup"},
            },
        )

        assert '"event": "signup"' in _briefs(self.team)[metric.id].definition

    def test_refuses_to_scan_without_ai_consent(self) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        with patch(f"{_MODULE}.execute_hogql_query") as clickhouse, pytest.raises(AIConsentMissing):
            _plan_detection(team_id=self.team.id, snapshot_id=uuid4(), telemetry_team_id=self.team.id)
        clickhouse.assert_not_called()


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
        self._telemetry(
            "$ai_span",
            "metric-describe",
            "failed-describe",
            at - timedelta(minutes=1),
            **{"$ai_input_state": json.dumps({"name": "signups"}), "$ai_is_error": True},
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
        assert "failed-describe" not in calls
