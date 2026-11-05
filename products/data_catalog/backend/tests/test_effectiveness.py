import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from uuid import UUID

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from asgiref.sync import async_to_sync, sync_to_async
from parameterized import parameterized

from posthog.models import Team

from products.data_catalog.backend.facade.enums import HOGQL_DEFINITION_KIND, JudgeRelation, MetricStatus
from products.data_catalog.backend.logic.effectiveness import (
    SESSION_OUTCOME_EVENT,
    TEAM_MEASURED_EVENT,
    AssetKind,
    CatalogListing,
    MatchedQuery,
    MissedReason,
    OutcomeRow,
    SessionEvidence,
    SessionOutcome,
    SkipReason,
    TeamEffectiveness,
    TeamSkipped,
    build_evidence,
    capture_effectiveness,
    capture_team_skipped,
    classify_session,
    mark_examples,
    measure_team,
    merge_candidate_groups,
    missed_reason,
    nominate_read_metrics,
)
from products.data_catalog.backend.logic.usage_adjusted import AgentQuery, CandidateGroup, CatalogCall
from products.data_catalog.backend.logic.usage_topics import CoverageVerdict, SessionText
from products.data_catalog.backend.models import Metric
from products.data_catalog.backend.temporal.effectiveness.workflows import previous_full_days

SIGNUPS_ID = UUID("00000000-0000-0000-0000-000000000001")
REVENUE_ID = UUID("00000000-0000-0000-0000-000000000002")
NAMES = {SIGNUPS_ID: "signups", REVENUE_ID: "revenue"}
IDS = {name: metric_id for metric_id, name in NAMES.items()}
STATUSES = {SIGNUPS_ID: MetricStatus.APPROVED, REVENUE_ID: MetricStatus.PROPOSED}
AT = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
SQL = "SELECT count() FROM events"


def _query(sql: str = SQL, *, trace: str = "s1") -> AgentQuery:
    return AgentQuery(occurred_at=AT, trace_id=trace, distinct_id="d1", intent="signups", sql=sql, is_scout=False)


def _call(tool: str, metric_name: str = "", *, failed: bool = False, minutes: int = -1) -> CatalogCall:
    return CatalogCall(
        trace_id="s1", occurred_at=AT + timedelta(minutes=minutes), tool=tool, metric_name=metric_name, failed=failed
    )


def _match(metric_id: UUID = SIGNUPS_ID, relation: JudgeRelation = JudgeRelation.SERVES) -> MatchedQuery:
    return MatchedQuery(query=_query(), metric_id=metric_id, relation=relation)


def _listing(output: str, arguments: str = '"{\\"limit\\":100}"', minutes: int = -1) -> CatalogListing:
    return CatalogListing(
        trace_id="s1", occurred_at=AT + timedelta(minutes=minutes), arguments=arguments, output=output
    )


def _stored_listing(*names: str, next_page: str = "null", complete: bool = True) -> str:
    results = ",".join(json.dumps({"name": name}) for name in names)
    body = f'{{"count":{len(names)},"next":{next_page},"results":[{results}]}}'
    text = f"<governed-metric-catalog>\n{body}\n" + ("</governed-metric-catalog>" if complete else "")
    return json.dumps(text)


def _outcomes(
    *,
    calls: list[CatalogCall],
    used: frozenset[UUID] = frozenset(),
    used_table: bool = False,
    matches: tuple[MatchedQuery, ...] = (),
    listings: tuple[CatalogListing, ...] = (),
) -> list[OutcomeRow]:
    evidence = SessionEvidence(
        session_id="s1",
        client="claude",
        asked=bool(calls),
        used_metric_ids=used,
        used_table=used_table,
        matches=matches,
    )
    return classify_session(evidence, calls=calls, listings=listings, metric_names=NAMES, metric_statuses=STATUSES)


class TestSessionOutcomes(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "ran_a_metric",
                {"calls": [_call("data-catalog-metric-run", "signups")], "used": frozenset({SIGNUPS_ID})},
                SessionOutcome.USED,
            ),
            ("read_a_described_table", {"calls": [_call("execute-sql")], "used_table": True}, SessionOutcome.USED),
            (
                "read_then_wrote_sql",
                {"calls": [_call("metric-describe", "signups")], "matches": (_match(),)},
                SessionOutcome.ADAPTED,
            ),
            ("listed_then_wrote_sql", {"calls": [_call("metric-list")], "matches": (_match(),)}, SessionOutcome.MISSED),
            (
                "read_another_metric_then_wrote_sql",
                {"calls": [_call("metric-describe", "revenue")], "matches": (_match(),)},
                SessionOutcome.MISSED,
            ),
            (
                "searched_tables_then_wrote_sql",
                {"calls": [_call("execute-sql")], "matches": (_match(),)},
                SessionOutcome.MISSED,
            ),
            ("never_asked", {"calls": [], "matches": (_match(),)}, SessionOutcome.DID_NOT_ASK),
            ("asked_and_nothing_fit", {"calls": [_call("metric-list")]}, SessionOutcome.ASKED_NO_MATCH),
            ("never_asked_and_nothing_fit", {"calls": []}, SessionOutcome.NO_ASK_NO_FIT),
        ]
    )
    def test_each_kind_of_session_gets_its_outcome(self, _name: str, evidence: dict, expected: SessionOutcome) -> None:
        rows = _outcomes(**evidence)

        assert [row.outcome for row in rows] == [expected]
        assert rows[0].is_headline

    def test_a_run_metric_that_is_also_derived_again_stays_used(self) -> None:
        rows = _outcomes(
            calls=[_call("data-catalog-metric-run", "signups")],
            used=frozenset({SIGNUPS_ID}),
            matches=(_match(relation=JudgeRelation.SLICE),),
        )

        assert [(row.outcome, row.metric_id) for row in rows] == [(SessionOutcome.USED, SIGNUPS_ID)]

    def test_the_headline_is_the_best_outcome_and_the_other_asset_keeps_its_row(self) -> None:
        rows = _outcomes(
            calls=[_call("data-catalog-metric-run", "signups")],
            used=frozenset({SIGNUPS_ID}),
            matches=(_match(REVENUE_ID),),
        )

        assert {(row.metric_id, row.outcome, row.is_headline, row.metric_status) for row in rows} == {
            (SIGNUPS_ID, SessionOutcome.USED, True, MetricStatus.APPROVED),
            (REVENUE_ID, SessionOutcome.MISSED, False, MetricStatus.PROPOSED),
        }

    @parameterized.expand(
        [
            ("judge_says_it_fits", CoverageVerdict(metric=True), False, {SIGNUPS_ID}),
            ("judge_says_it_does_not_fit", CoverageVerdict(metric=False), False, set()),
            ("judge_failed", CoverageVerdict(failed=True), False, {SIGNUPS_ID}),
            ("no_verdict", None, False, {SIGNUPS_ID}),
            ("the_run_failed", CoverageVerdict(metric=True), True, set()),
        ]
    )
    def test_a_run_counts_as_used_when_it_worked_and_fits(
        self, _name: str, verdict: CoverageVerdict | None, failed: bool, expected: set[UUID]
    ) -> None:
        evidence = build_evidence(
            SessionText(session_id="s1", person="d1", notes=(), tools=frozenset()),
            calls=[_call("data-catalog-metric-run", "signups", failed=failed)],
            verdict=verdict,
            matches=[],
            metric_ids_by_name=IDS,
        )

        assert evidence.used_metric_ids == expected
        assert evidence.asked

    @parameterized.expand(
        [
            ("no_listing", [], MissedReason.NEVER_LISTED),
            ("listing_after_the_query", [_listing(_stored_listing("signups"), minutes=1)], MissedReason.NEVER_LISTED),
            ("name_in_listing", [_listing(_stored_listing("revenue", "signups"))], MissedReason.RETURNED_IGNORED),
            (
                "whole_catalog_cut_before_the_name",
                [_listing(_stored_listing("revenue", complete=False))],
                MissedReason.RETURNED_IGNORED,
            ),
            (
                "complete_search_without_the_name",
                [_listing(_stored_listing("revenue"), arguments='"{\\"search\\":\\"cost\\"}"')],
                MissedReason.NOT_RETURNED,
            ),
            (
                "cut_search_without_the_name",
                [_listing(_stored_listing("revenue", complete=False), arguments='"{\\"search\\":\\"cost\\"}"')],
                MissedReason.UNKNOWN,
            ),
            (
                "first_page_of_many_cut_before_the_name",
                [_listing(_stored_listing("revenue", next_page='"url"', complete=False))],
                MissedReason.UNKNOWN,
            ),
            ("output_not_stored", [_listing("")], MissedReason.UNKNOWN),
        ]
    )
    def test_missed_reason(self, _name: str, listings: list[CatalogListing], expected: MissedReason) -> None:
        assert missed_reason(_query(), "signups", listings) == expected

    def test_a_metric_the_session_read_is_nominated_without_a_fingerprint_match(self) -> None:
        reshaped = "SELECT toStartOfWeek(timestamp), uniq(person_id) FROM events GROUP BY 1"
        calls = {"s1": [_call("metric-describe", "signups"), _call("metric-describe", "revenue", minutes=1)]}

        groups = nominate_read_metrics(
            [_query(reshaped), _query("SELECT description FROM system.information_schema.tables")], calls, IDS
        )

        assert [(group.metric_id, group.sql) for group in groups] == [(SIGNUPS_ID, reshaped)]

    def test_a_fingerprint_group_keeps_every_run_when_a_read_nominates_the_same_pair(self) -> None:
        other_session = _query(trace="s2")
        fingerprinted = CandidateGroup(
            metric_id=SIGNUPS_ID, sql=SQL, intent="signups", occurrences=(_query(), other_session)
        )
        nominated = CandidateGroup(metric_id=SIGNUPS_ID, sql=SQL, intent="signups", occurrences=(_query(),))

        assert merge_candidate_groups([fingerprinted], [nominated]) == [fingerprinted]

    def test_previous_full_days_leave_no_gap_between_weekly_runs(self) -> None:
        first = previous_full_days(datetime(2026, 11, 2, 7, 3, tzinfo=UTC), 7)
        second = previous_full_days(datetime(2026, 11, 9, 7, 1, tzinfo=UTC), 7)

        assert first.end == second.start == datetime(2026, 11, 2, tzinfo=UTC)
        assert (first.start, second.end) == (datetime(2026, 10, 26, tzinfo=UTC), datetime(2026, 11, 9, tzinfo=UTC))


def _team() -> Team:
    return cast(Team, SimpleNamespace(id=2, organization_id="org", uuid="project"))


def _result(rows: tuple[OutcomeRow, ...], analysis_sessions: int = 2) -> TeamEffectiveness:
    return TeamEffectiveness(
        team_id=2,
        window_start=AT,
        window_end=AT + timedelta(days=7),
        sessions_read=4,
        is_sample=False,
        unread_sessions=0,
        analysis_sessions=analysis_sessions,
        unchecked_queries=0,
        unchecked_sessions=0,
        telemetry_team_id=2,
        rows=rows,
    )


def _row(session: str, outcome: SessionOutcome, kind: AssetKind, *, headline: bool = True) -> OutcomeRow:
    return OutcomeRow(
        session_id=session,
        client="claude",
        outcome=outcome,
        asset_kind=kind,
        is_headline=headline,
        metric_id=SIGNUPS_ID if kind == AssetKind.METRIC else None,
    )


class TestTeamEffectiveness(SimpleTestCase):
    def test_shares_use_their_own_bases(self) -> None:
        result = _result(
            (
                _row("s1", SessionOutcome.USED, AssetKind.TABLE),
                _row("s1", SessionOutcome.DID_NOT_ASK, AssetKind.METRIC, headline=False),
                _row("s2", SessionOutcome.NO_ASK_NO_FIT, AssetKind.NONE),
                _row("s3", SessionOutcome.ADAPTED, AssetKind.METRIC),
                _row("s4", SessionOutcome.MISSED, AssetKind.METRIC),
            ),
            analysis_sessions=4,
        )

        assert result.served_share == 0.5
        assert result.capture_share == 1 / 3

    def test_examples_are_capped_per_unserved_outcome_and_stable(self) -> None:
        rows = [_row(f"used{n}", SessionOutcome.USED, AssetKind.METRIC) for n in range(3)]
        rows += [_row(f"silent{n}", SessionOutcome.DID_NOT_ASK, AssetKind.METRIC) for n in range(9)]
        rows += [_row("asked", SessionOutcome.ASKED_NO_MATCH, AssetKind.NONE)]

        examples = [row for row in mark_examples(rows, per_outcome=4) if row.is_example]
        rerun = [row for row in mark_examples(list(reversed(rows)), per_outcome=4) if row.is_example]

        assert Counter(row.outcome for row in examples) == {
            SessionOutcome.DID_NOT_ASK: 4,
            SessionOutcome.ASKED_NO_MATCH: 1,
        }
        assert {row.session_id for row in rerun} == {row.session_id for row in examples}

    def test_no_sessions_give_no_share(self) -> None:
        result = _result((), analysis_sessions=0)

        assert result.served_share is None
        assert result.capture_share is None

    @patch("products.data_catalog.backend.logic.effectiveness.ph_scoped_capture")
    def test_a_skipped_team_sends_the_team_event_with_the_reason(self, scoped_capture: MagicMock) -> None:
        capture = scoped_capture.return_value.__enter__.return_value
        team = _team()

        capture_team_skipped(
            TeamSkipped(team_id=2, reason=SkipReason.NO_AI_CONSENT),
            team,
            window_start=AT,
            window_end=AT + timedelta(days=7),
        )

        call = capture.call_args
        assert call.args[0] == TEAM_MEASURED_EVENT
        assert call.kwargs["properties"]["skipped_reason"] == "no_ai_consent"

    @patch("products.data_catalog.backend.logic.effectiveness.ph_scoped_capture")
    def test_a_rerun_sends_the_same_event_ids_and_no_query_text(self, scoped_capture: MagicMock) -> None:
        capture = scoped_capture.return_value.__enter__.return_value
        team = _team()
        result = _result(
            (
                _row("s1", SessionOutcome.USED, AssetKind.METRIC),
                _row("s1", SessionOutcome.USED, AssetKind.TABLE, headline=False),
            )
        )

        capture_effectiveness(result, team)
        capture_effectiveness(result, team)

        calls = capture.call_args_list
        events = [call.args[0] for call in calls]
        assert events == [SESSION_OUTCOME_EVENT, SESSION_OUTCOME_EVENT, TEAM_MEASURED_EVENT] * 2
        ids = [call.kwargs["uuid"] for call in calls]
        assert ids[:3] == ids[3:] and len(set(ids[:3])) == 3
        assert all(call.kwargs["timestamp"] == AT for call in calls)
        assert calls[0].kwargs["groups"] == {"organization": "org", "project": "project"}
        first = calls[0].kwargs["properties"]
        assert set(first).isdisjoint({"sql", "intent", "question", "reasoning"})
        assert first["trace_url"].endswith("/project/2/ai-observability/traces/s1")


class _JudgeMessages:
    def __init__(self) -> None:
        self.judged_sql: list[str] = []

    def stream(self, *, model: str, max_tokens: int, messages: list[dict[str, str]]) -> "_Stream":
        prompt = messages[0]["content"]
        if "<steps" in prompt:
            return _Stream('{"metric": true, "description": false}')
        kind = "lookup" if "open the ticket thread" in prompt else "analysis"
        return _Stream(json.dumps({"kind": kind, "question": "How many signups happen each week?"}))

    async def create(
        self, *, model: str, system: str, messages: list[dict[str, str]], max_tokens: int
    ) -> SimpleNamespace:
        prompt = messages[0]["content"]
        self.judged_sql.append(prompt)
        relation = "different" if "page_views" in prompt else "serves"
        reply = json.dumps({"reasoning": "It counts signups.", "relation": relation, "confidence": 0.9})
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=reply)])


class _Stream:
    def __init__(self, reply: str) -> None:
        self._reply = reply

    async def __aenter__(self) -> "_Stream":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def get_final_message(self) -> SimpleNamespace:
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self._reply)])


class _FakeClient:
    def __init__(self) -> None:
        self.messages = _JudgeMessages()

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


@patch(
    "products.data_catalog.backend.logic.effectiveness.database_sync_to_async",
    lambda function, thread_sensitive=False: sync_to_async(function, thread_sensitive=True),
)
class TestMeasureTeam(ClickhouseTestMixin, BaseTest):
    SIGNUPS_SQL = "SELECT count() FROM events WHERE event = 'signed_up'"
    END = datetime(2026, 10, 20, tzinfo=UTC)

    def setUp(self) -> None:
        super().setUp()
        metric = Metric.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            name="signups",
            display_name="Signups",
            description="People who signed up.",
            status=MetricStatus.APPROVED.value,
            definition={"kind": HOGQL_DEFINITION_KIND, "query": self.SIGNUPS_SQL},
        )
        Metric.objects.for_team(self.team.id).filter(id=metric.id).update(created_at=self.END - timedelta(days=30))
        self.metric_id = metric.id

    def _session(self, session: str, intent: str, sql: str | None, *catalog_tools: str) -> None:
        at = self.END - timedelta(hours=6)
        shared = {"$mcp_project_uuid": str(self.team.uuid), "$session_id": session, "$ai_trace_id": session}
        _create_event(
            team=self.team,
            event="$mcp_tool_call",
            distinct_id="d1",
            timestamp=at,
            properties={**shared, "$mcp_intent": intent, "$mcp_tool_name": "execute-sql", "$mcp_client_name": "claude"},
        )
        for offset, tool in enumerate(catalog_tools, start=1):
            _create_event(
                team=self.team,
                event="$ai_span",
                distinct_id="d1",
                timestamp=at - timedelta(minutes=offset),
                properties={
                    **shared,
                    "$ai_span_name": tool,
                    "$ai_input_state": json.dumps({"name": "signups"}),
                    "$ai_output_state": "{}",
                },
            )
        if sql:
            _create_event(
                team=self.team,
                event="$ai_generation",
                distinct_id="d1",
                timestamp=at,
                properties={
                    **shared,
                    "$ai_span_name": "execute-sql",
                    "$ai_input": [{"role": "user", "content": intent}],
                    "$ai_output_choices": [{"role": "assistant", "content": sql}],
                },
            )

    def _measure(self, client: _FakeClient) -> TeamEffectiveness | TeamSkipped:
        with patch(
            "products.data_catalog.backend.logic.effectiveness.build_async_anthropic_client", return_value=client
        ):
            return async_to_sync(measure_team)(
                team_id=self.team.id,
                telemetry_team_id=self.team.id,
                window_start=self.END - timedelta(days=2),
                window_end=self.END,
                heartbeat=lambda: None,
            )

    def test_every_analysis_session_gets_one_headline_from_the_joined_telemetry(self) -> None:
        self._session("ran", "weekly signups", None, "data-catalog-metric-run")
        self._session("read", "weekly signups", self.SIGNUPS_SQL, "metric-describe")
        self._session("listed", "weekly signups", self.SIGNUPS_SQL, "metric-list")
        self._session("silent", "weekly signups", self.SIGNUPS_SQL)
        self._session("nofit", "weekly page views", "SELECT uniq(person_id) FROM page_views")
        self._session("asked", "weekly page views", "SELECT uniq(person_id) FROM page_views", "metric-list")
        self._session("ticket", "open the ticket thread", "SELECT uniq(person_id) FROM page_views")
        flush_persons_and_events()

        result = self._measure(_FakeClient())

        assert isinstance(result, TeamEffectiveness)
        assert result.analysis_sessions == 6
        assert {row.session_id: (row.outcome, row.client) for row in result.rows if row.is_headline} == {
            "ran": (SessionOutcome.USED, "claude"),
            "read": (SessionOutcome.ADAPTED, "claude"),
            "listed": (SessionOutcome.MISSED, "claude"),
            "silent": (SessionOutcome.DID_NOT_ASK, "claude"),
            "nofit": (SessionOutcome.NO_ASK_NO_FIT, "claude"),
            "asked": (SessionOutcome.ASKED_NO_MATCH, "claude"),
        }
        assert result.served_share == 2 / 6
        silent = next(row for row in result.rows if row.session_id == "silent")
        assert (silent.metric_name, silent.is_example, silent.reasoning) == ("signups", True, "It counts signups.")
        assert silent.question == "How many signups happen each week?"
        assert silent.started_at == self.END - timedelta(hours=6)

    def test_a_team_without_ai_consent_reaches_no_model(self) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        with patch("products.data_catalog.backend.logic.effectiveness.fetch_topic_sessions") as fetch:
            result = self._measure(MagicMock(side_effect=AssertionError("The model must not run.")))

        assert result == TeamSkipped(team_id=self.team.id, reason=SkipReason.NO_AI_CONSENT)
        fetch.assert_not_called()
