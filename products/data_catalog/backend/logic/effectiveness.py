"""Measure, per team, how many agent analysis sessions the catalog served.

Each analysis session lands in one of five outcomes: used, adapted, missed, asked with no match, and
did not ask. Every analysis session should ask the catalog, so a session that did not ask counts even
when no metric fits. Its asset kind says whether a metric existed.
The results go to PostHog's own project as events, so that staff can compare teams. They never go
into a usage snapshot, because the usage tab and its API show snapshots to the team.
"""

import uuid
import asyncio
import hashlib
import dataclasses
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from django.conf import settings

import structlog

from posthog.hogql import ast

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import build_async_anthropic_client
from posthog.models import Team
from posthog.ph_client import ph_scoped_capture
from posthog.sync import database_sync_to_async

from ..facade.enums import JudgeRelation, MetricStatus
from ..models import Metric
from .agent_sessions import Piece, SessionText, StitchedSessions, fetch_candidate_chains, gather_each, stitch_chains
from .metric_fingerprint import CatalogIndex
from .usage_adjusted import (
    AgentQuery,
    CandidateGroup,
    CatalogCall,
    JudgeUnavailable,
    build_candidate_groups,
    fetch_agent_queries,
    fetch_catalog_calls,
    judge_groups,
    metric_briefs,
    paged_rows,
    read_metric_first,
    select_for_judging,
)
from .usage_judge import JudgeVerdict, MetricBrief
from .usage_topics import (
    CoverageVerdict,
    SessionKind,
    SessionLookups,
    SessionReading,
    decode_nested_json,
    fetch_session_lookups,
    judge_coverage,
    merge_lookups,
    read_session,
)

logger = structlog.get_logger(__name__)

# Raise this when a rule changes, so that a change in the rules does not read as a change in behavior.
DEFINITION_VERSION = 1

SESSION_OUTCOME_EVENT = "data catalog session outcome"
TEAM_MEASURED_EVENT = "data catalog effectiveness measured"

# Each candidate chain costs a model call to join its pieces, and each joined conversation costs one
# model read. This check takes a larger sample than the usage scan, because it splits the sessions into
# five outcomes and reports examples of the rare ones.
EFFECTIVENESS_SESSION_LIMIT = 5000
# The lookups query lists piece ids in an IN clause, so it reads them in batches.
_LOOKUP_BATCH = 1000

# Bounds one team's judge spend. A team that reaches it reports the rest as unchecked queries.
_JUDGE_CALL_CAP = 3000

_RUN_TOOL = "data-catalog-metric-run"
_READ_TOOLS = frozenset({"metric-describe", _RUN_TOOL})
_METADATA_MARKERS = ("information_schema", "system.")
_CATALOG_END_TAG = "</governed-metric-catalog>"
_FULL_LISTING_MARKER = '"next":null'
_PAGING_ARGUMENTS = frozenset({"limit", "offset"})
EXAMPLES_PER_OUTCOME = 15
_CAPTURE_BATCH = 1000

# The metric name in a stored listing sits inside JSON text that is itself encoded as a string.
_LISTINGS_QUERY = """
SELECT
    a.trace_id,
    a.timestamp,
    ifNull(a.input_state, '') AS arguments,
    ifNull(a.output_state, '') AS output
FROM posthog.ai_events AS a
WHERE a.event = '$ai_span'
    AND a.span_name = 'metric-list'
    AND a.timestamp >= {start}
    AND a.timestamp < {end}
    AND toString(a.properties.$mcp_project_uuid) = {project}
    AND a.trace_id IN {traces}
LIMIT 50000
"""


class SessionOutcome(StrEnum):
    USED = "used"
    ADAPTED = "adapted"
    MISSED = "missed"
    DID_NOT_ASK = "did_not_ask"
    ASKED_NO_MATCH = "asked_no_match"


class AssetKind(StrEnum):
    METRIC = "metric"
    TABLE = "table"
    NONE = "none"


class MissedReason(StrEnum):
    RETURNED_IGNORED = "returned_ignored"
    NOT_RETURNED = "not_returned"
    NEVER_LISTED = "never_listed"
    UNKNOWN = "unknown"


class SkipReason(StrEnum):
    NO_AI_CONSENT = "no_ai_consent"


_SERVED = frozenset({SessionOutcome.USED, SessionOutcome.ADAPTED})
# Staff read these sessions to check that an outcome is right and to see why the catalog did not serve them.
_EXAMPLE_OUTCOMES = frozenset({SessionOutcome.MISSED, SessionOutcome.DID_NOT_ASK, SessionOutcome.ASKED_NO_MATCH})
_OUTCOME_ORDER = tuple(SessionOutcome)


def fetch_outcome(query: AgentQuery, metric_name: str, calls: Iterable[CatalogCall]) -> SessionOutcome:
    """How the agent reached a query that re-derives a metric: through the metric, past the catalog, or without it."""
    if read_metric_first(query, metric_name, calls):
        return SessionOutcome.ADAPTED
    if any(call.trace_id == query.trace_id and call.occurred_at <= query.occurred_at for call in calls):
        return SessionOutcome.MISSED
    return SessionOutcome.DID_NOT_ASK


def count_unchecked_queries(verdicts: Iterable[JudgeVerdict], over_cap: int) -> int:
    """Candidate queries with no verdict, because the judge failed or the run hit the call cap."""
    return over_cap + sum(1 for verdict in verdicts if verdict.failed)


@frozen
class CatalogListing:
    """One stored `metric-list` result. The store cuts long outputs, so the text can stop mid-list."""

    trace_id: str
    occurred_at: datetime
    arguments: str
    output: str


@frozen
class MatchedQuery:
    """One agent query that the judge matched to one metric."""

    query: AgentQuery
    metric_id: UUID
    relation: JudgeRelation
    reasoning: str = ""


@frozen
class OutcomeRow:
    """One session and one asset. Exactly one row of each session is the session's headline.

    ``question`` and ``reasoning`` hold text from customer queries. They serve the staff command only,
    and the captured events never carry them, because the events outlive the 30 days of `ai_events`.
    """

    session_id: str
    client: str
    source: str
    outcome: SessionOutcome
    asset_kind: AssetKind
    is_headline: bool
    metric_id: UUID | None = None
    metric_status: MetricStatus | None = None
    relation: JudgeRelation | None = None
    missed_reason: MissedReason | None = None
    metric_name: str = ""
    started_at: datetime | None = None
    is_example: bool = False
    question: str = ""
    reasoning: str = ""


@frozen
class SessionEvidence:
    """What decides one session's outcomes, gathered from the scan's reads and judges."""

    session_id: str
    client: str
    source: str
    asked: bool
    used_metric_ids: frozenset[UUID]
    used_table: bool
    matches: tuple[MatchedQuery, ...]
    started_at: datetime | None = None
    question: str = ""


@frozen
class TeamEffectiveness:
    team_id: int
    window_start: datetime
    window_end: datetime
    sessions_read: int
    is_sample: bool
    chains_read: int = 0
    pieces_read: int = 0
    stitch_failures: int = 0
    unread_sessions: int
    analysis_sessions: int
    unchecked_queries: int
    unchecked_sessions: int
    telemetry_team_id: int
    rows: tuple[OutcomeRow, ...]

    @property
    def headline_counts(self) -> Counter[SessionOutcome]:
        return Counter(row.outcome for row in self.rows if row.is_headline)

    @property
    def metric_pair_counts(self) -> Counter[SessionOutcome]:
        return Counter(row.outcome for row in self.rows if row.asset_kind == AssetKind.METRIC)

    @property
    def served_share(self) -> float | None:
        """Does not depend on fit detection, because the base is every analysis session."""
        if not self.analysis_sessions:
            return None
        counts = self.headline_counts
        return sum(counts[outcome] for outcome in _SERVED) / self.analysis_sessions

    @property
    def capture_share(self) -> float | None:
        """Reads too high while fit detection misses queries, because a missed query lowers the base."""
        counts = self.metric_pair_counts
        return sum(counts[outcome] for outcome in _SERVED) / total if (total := sum(counts.values())) else None


@frozen
class TeamSkipped:
    team_id: int
    reason: SkipReason


def missed_reason(query: AgentQuery, metric_name: str, listings: Iterable[CatalogListing]) -> MissedReason:
    """Why an agent that asked the catalog went past a metric that fits."""
    earlier = [listing for listing in listings if listing.occurred_at <= query.occurred_at]
    if not earlier:
        return MissedReason.NEVER_LISTED
    if any(_listing_holds(listing, metric_name) for listing in earlier):
        return MissedReason.RETURNED_IGNORED
    if all(_CATALOG_END_TAG in listing.output for listing in earlier):
        return MissedReason.NOT_RETURNED
    return MissedReason.UNKNOWN


def _listing_holds(listing: CatalogListing, metric_name: str) -> bool:
    text = listing.output.replace("\\", "")
    if f'"name":"{metric_name}"' in text:
        return True
    # The store cuts a long output, so a complete and unfiltered first page holds the metric even
    # when the stored text stops before its name.
    return _FULL_LISTING_MARKER in text and _lists_everything(listing.arguments)


def _lists_everything(raw_arguments: str) -> bool:
    arguments = decode_nested_json(raw_arguments)
    if not isinstance(arguments, dict):
        return False
    return not arguments.get("offset") and set(arguments) <= _PAGING_ARGUMENTS


def classify_session(
    evidence: SessionEvidence,
    *,
    calls: Sequence[CatalogCall],
    listings: Sequence[CatalogListing],
    metric_names: dict[UUID, str],
    metric_statuses: dict[UUID, MetricStatus],
) -> list[OutcomeRow]:
    """One row per asset. The session's headline is its best outcome, so a session that ran one metric
    and derived another again counts as served, and the other metric still shows in the pair counts."""
    rows = [
        _row(
            evidence,
            SessionOutcome.USED,
            AssetKind.METRIC,
            metric_id=metric_id,
            metric_name=metric_names.get(metric_id, ""),
            metric_status=metric_statuses.get(metric_id),
        )
        for metric_id in sorted(evidence.used_metric_ids, key=str)
    ]
    if evidence.used_table:
        rows.append(_row(evidence, SessionOutcome.USED, AssetKind.TABLE))

    matches_by_metric: dict[UUID, list[MatchedQuery]] = defaultdict(list)
    for match in evidence.matches:
        if match.metric_id not in evidence.used_metric_ids:
            matches_by_metric[match.metric_id].append(match)
    for metric_id in sorted(matches_by_metric, key=str):
        rows.append(
            _matched_row(
                evidence,
                metric_id,
                matches_by_metric[metric_id],
                calls=calls,
                listings=listings,
                metric_name=metric_names.get(metric_id, ""),
                metric_status=metric_statuses.get(metric_id),
            )
        )

    if not rows:
        outcome = SessionOutcome.ASKED_NO_MATCH if evidence.asked else SessionOutcome.DID_NOT_ASK
        rows.append(_row(evidence, outcome, AssetKind.NONE))
    return _mark_headline(rows)


def _row(evidence: SessionEvidence, outcome: SessionOutcome, asset_kind: AssetKind, **fields: Any) -> OutcomeRow:
    return OutcomeRow(
        session_id=evidence.session_id,
        client=evidence.client,
        source=evidence.source,
        outcome=outcome,
        asset_kind=asset_kind,
        is_headline=False,
        started_at=evidence.started_at,
        question=evidence.question,
        **fields,
    )


def _matched_row(
    evidence: SessionEvidence,
    metric_id: UUID,
    matches: Sequence[MatchedQuery],
    *,
    calls: Sequence[CatalogCall],
    listings: Sequence[CatalogListing],
    metric_name: str,
    metric_status: MetricStatus | None,
) -> OutcomeRow:
    attributed = [(fetch_outcome(match.query, metric_name, calls), match) for match in matches]
    outcome, chosen = min(
        attributed,
        key=lambda pair: (_OUTCOME_ORDER.index(pair[0]), pair[1].relation != JudgeRelation.SERVES),
    )
    return _row(
        evidence,
        outcome,
        AssetKind.METRIC,
        metric_id=metric_id,
        metric_name=metric_name,
        metric_status=metric_status,
        relation=chosen.relation,
        reasoning=chosen.reasoning,
        missed_reason=missed_reason(chosen.query, metric_name, listings) if outcome == SessionOutcome.MISSED else None,
    )


def _mark_headline(rows: Sequence[OutcomeRow]) -> list[OutcomeRow]:
    best = min(rows, key=lambda row: _OUTCOME_ORDER.index(row.outcome))
    return [dataclasses.replace(row, is_headline=row is best) for row in rows]


def mark_examples(rows: Iterable[OutcomeRow], per_outcome: int = EXAMPLES_PER_OUTCOME) -> list[OutcomeRow]:
    """Mark a few sessions of each outcome that the catalog did not serve. The choice comes from a hash of
    the session id, so a rerun marks the same sessions and one busy hour cannot fill the list. Sessions with
    and without a metric are marked apart, because far more sessions have none and would fill the list."""
    all_rows = list(rows)
    candidates: dict[tuple[SessionOutcome, AssetKind], list[OutcomeRow]] = defaultdict(list)
    for row in all_rows:
        if row.outcome in _EXAMPLE_OUTCOMES:
            candidates[(row.outcome, row.asset_kind)].append(row)
    examples = {
        id(row)
        for outcome_rows in candidates.values()
        for row in sorted(outcome_rows, key=lambda row: hashlib.sha256(row.session_id.encode()).hexdigest())[
            :per_outcome
        ]
    }
    return [dataclasses.replace(row, is_example=id(row) in examples) for row in all_rows]


def trace_url(session_id: str, telemetry_team_id: int) -> str:
    """An MCP session id is also its trace id, so the session opens as one trace in the telemetry project."""
    return f"{settings.SITE_URL}/project/{telemetry_team_id}/ai-observability/traces/{session_id}"


def nominate_read_metrics(
    queries: Iterable[AgentQuery],
    calls_by_trace: dict[str, list[CatalogCall]],
    metric_ids_by_name: dict[str, UUID],
) -> list[CandidateGroup]:
    """Pair each query with the metrics its session read first. An agent can change a metric's query so
    much that the fingerprint no longer matches, and that is still an adapted metric if the judge agrees."""
    occurrences: dict[tuple[UUID, str], list[AgentQuery]] = defaultdict(list)
    for query in queries:
        if any(marker in query.sql.lower() for marker in _METADATA_MARKERS):
            continue
        read = {
            metric_ids_by_name[call.metric_name]
            for call in calls_by_trace.get(query.trace_id, [])
            if call.tool in _READ_TOOLS
            and not call.failed
            and call.occurred_at <= query.occurred_at
            and call.metric_name in metric_ids_by_name
        }
        for metric_id in read:
            occurrences[(metric_id, query.sql.strip())].append(query)
    return [
        CandidateGroup(metric_id=metric_id, sql=runs[0].sql, intent=runs[0].intent, occurrences=tuple(runs))
        for (metric_id, _), runs in occurrences.items()
    ]


def merge_candidate_groups(
    fingerprinted: Iterable[CandidateGroup], nominated: Iterable[CandidateGroup]
) -> list[CandidateGroup]:
    """A fingerprint group holds every run of its SQL, so it wins over a group of the same pair."""
    merged = {(group.metric_id, group.sql.strip()): group for group in nominated}
    merged.update({(group.metric_id, group.sql.strip()): group for group in fingerprinted})
    return list(merged.values())


def fetch_listings(
    *, team: Team, telemetry_team: Team, window_start: datetime, window_end: datetime, trace_ids: Iterable[str]
) -> dict[str, list[CatalogListing]]:
    traces = sorted(set(trace_ids))
    if not traces:
        return {}
    listings: dict[str, list[CatalogListing]] = defaultdict(list)
    for trace_id, occurred_at, arguments, output in paged_rows(
        _LISTINGS_QUERY,
        team,
        telemetry_team,
        window_start,
        window_end,
        "DataCatalogEffectivenessListings",
        placeholders={"traces": ast.Tuple(exprs=[ast.Constant(value=trace) for trace in traces])},
    ):
        listings[trace_id].append(
            CatalogListing(trace_id=trace_id, occurred_at=occurred_at, arguments=arguments, output=output)
        )
    return listings


@frozen
class _CatalogView:
    team: Team
    telemetry_team: Team
    consented: bool
    index: CatalogIndex
    briefs: dict[UUID, MetricBrief]
    metric_ids_by_name: dict[str, UUID]
    metric_statuses: dict[UUID, MetricStatus]


def _load_catalog(team_id: int, telemetry_team_id: int) -> _CatalogView:
    team = Team.objects.select_related("organization").get(id=team_id)
    metrics = list(Metric.objects.for_team(team_id).filter(deleted=False))
    return _CatalogView(
        team=team,
        telemetry_team=Team.objects.get(id=telemetry_team_id),
        consented=bool(team.organization.is_ai_data_processing_approved),
        index=CatalogIndex.for_team(team),
        briefs=metric_briefs(team),
        metric_ids_by_name={metric.name: metric.id for metric in metrics},
        metric_statuses={metric.id: MetricStatus(metric.status) for metric in metrics},
    )


@frozen
class _AgentActivity:
    queries: list[AgentQuery]
    calls_by_trace: dict[str, list[CatalogCall]]


@frozen
class _AnalysisSession:
    session: SessionText
    question: str


def _matches_from_verdicts(
    groups: Iterable[CandidateGroup], verdicts: Iterable[JudgeVerdict]
) -> dict[str, list[MatchedQuery]]:
    matches: dict[str, list[MatchedQuery]] = defaultdict(list)
    for group, verdict in zip(groups, verdicts, strict=True):
        if verdict.relation == JudgeRelation.DIFFERENT:
            continue
        for occurrence in group.occurrences:
            matches[occurrence.trace_id].append(
                MatchedQuery(
                    query=occurrence,
                    metric_id=group.metric_id,
                    relation=verdict.relation,
                    reasoning=verdict.reasoning,
                )
            )
    return matches


def _used_metric_ids(
    calls: Iterable[CatalogCall], verdict: CoverageVerdict | None, metric_ids_by_name: dict[str, UUID]
) -> frozenset[UUID]:
    """A failed run answers nothing, and the judge can say that a metric the agent ran did not fit the
    question. With no verdict from the judge, a successful run still counts as used."""
    if verdict is not None and not verdict.failed and not verdict.metric:
        return frozenset()
    return frozenset(
        metric_ids_by_name[call.metric_name]
        for call in calls
        if call.tool == _RUN_TOOL and not call.failed and call.metric_name in metric_ids_by_name
    )


def build_evidence(
    session: SessionText,
    *,
    calls: Sequence[CatalogCall],
    verdict: CoverageVerdict | None,
    matches: Sequence[MatchedQuery],
    metric_ids_by_name: dict[str, UUID],
    question: str = "",
) -> SessionEvidence:
    return SessionEvidence(
        session_id=session.session_id,
        client=session.client,
        source=session.source,
        started_at=session.started_at,
        question=question,
        asked=bool(calls),
        used_metric_ids=_used_metric_ids(calls, verdict, metric_ids_by_name),
        used_table=verdict is not None and verdict.description,
        matches=tuple(matches),
    )


@frozen
class _TelemetryWindow:
    team: Team
    telemetry_team: Team
    start: datetime
    end: datetime

    def chains(self) -> list[list[Piece]]:
        return fetch_candidate_chains(
            team=self.team,
            telemetry_team=self.telemetry_team,
            window_start=self.start,
            window_end=self.end,
            chain_limit=EFFECTIVENESS_SESSION_LIMIT,
        )

    def lookup_pieces(self, pieces: list[str]) -> dict[str, SessionLookups]:
        return fetch_session_lookups(
            team=self.team,
            telemetry_team=self.telemetry_team,
            window_start=self.start,
            window_end=self.end,
            session_ids=pieces,
        )

    def activity(self, stitched: StitchedSessions, session_ids: set[str]) -> _AgentActivity:
        unit_of = {
            piece: unit
            for unit, unit_pieces in stitched.members.items()
            if unit in session_ids
            for piece in unit_pieces
        }
        # Only the sampled sessions matter, so unrelated traffic neither costs memory nor fills a page.
        traces = sorted(unit_of)
        queries = fetch_agent_queries(
            team=self.team,
            telemetry_team=self.telemetry_team,
            window_start=self.start,
            window_end=self.end,
            trace_ids=traces,
        )
        calls = fetch_catalog_calls(
            team=self.team,
            telemetry_team=self.telemetry_team,
            window_start=self.start,
            window_end=self.end,
            trace_ids=traces,
        )
        calls_by_unit: dict[str, list[CatalogCall]] = defaultdict(list)
        for trace, trace_calls in calls.items():
            if trace in unit_of:
                calls_by_unit[unit_of[trace]].extend(
                    dataclasses.replace(call, trace_id=unit_of[trace]) for call in trace_calls
                )
        return _AgentActivity(
            queries=[
                dataclasses.replace(query, trace_id=unit_of[query.trace_id])
                for query in queries
                if query.trace_id in unit_of
            ],
            calls_by_trace={
                unit: sorted(unit_calls, key=lambda call: call.occurred_at)
                for unit, unit_calls in calls_by_unit.items()
            },
        )

    def listings(self, stitched: StitchedSessions, session_ids: set[str]) -> dict[str, list[CatalogListing]]:
        unit_of = {piece: unit for unit in session_ids for piece in stitched.members[unit]}
        by_unit: dict[str, list[CatalogListing]] = defaultdict(list)
        for trace, trace_listings in fetch_listings(
            team=self.team,
            telemetry_team=self.telemetry_team,
            window_start=self.start,
            window_end=self.end,
            trace_ids=set(unit_of),
        ).items():
            by_unit[unit_of[trace]].extend(
                dataclasses.replace(listing, trace_id=unit_of[trace]) for listing in trace_listings
            )
        return {unit: sorted(items, key=lambda item: item.occurred_at) for unit, items in by_unit.items()}


async def measure_team(
    *,
    team_id: int,
    telemetry_team_id: int,
    window_start: datetime,
    window_end: datetime,
    heartbeat: Callable[[], None],
) -> TeamEffectiveness | TeamSkipped:
    catalog = await database_sync_to_async(_load_catalog, thread_sensitive=False)(team_id, telemetry_team_id)
    if not catalog.consented:
        return TeamSkipped(team_id=team_id, reason=SkipReason.NO_AI_CONSENT)

    window = _TelemetryWindow(
        team=catalog.team, telemetry_team=catalog.telemetry_team, start=window_start, end=window_end
    )
    chains = await database_sync_to_async(window.chains, thread_sensitive=False)()

    async with build_async_anthropic_client(
        product="django",
        ai_product="data_catalog_effectiveness",
        team_id=team_id,
        trace_id=f"data-catalog-effectiveness-{team_id}-{window_start.date()}",
    ) as client:
        stitched = await stitch_chains(client, chains, heartbeat)
        # Joined chains can hold more conversations than chains, so the read budget caps the sessions too.
        sessions = stitched.sessions[:EFFECTIVENESS_SESSION_LIMIT]
        readings: list[SessionReading] = await gather_each(
            (read_session(client, session) for session in sessions), heartbeat
        )
        # A week with every read failed would look like a week with no analysis, so the activity retries.
        if sessions and all(reading.kind == SessionKind.UNREAD for reading in readings):
            raise SessionReadsUnavailable(f"All {len(readings)} session reads failed.")
        analysis = {
            session.session_id: _AnalysisSession(session=session, question=reading.question)
            for session, reading in zip(sessions, readings, strict=True)
            if reading.kind == SessionKind.ANALYSIS and reading.catalog_check
        }
        session_ids = list(analysis)
        lookups = await _session_lookups(window, stitched, session_ids, heartbeat)
        checked = [
            session_id
            for session_id in session_ids
            if (found := lookups.get(session_id)) and (found.ran_metric or found.read_descriptions)
        ]
        coverage_verdicts: list[CoverageVerdict] = await gather_each(
            (judge_coverage(client, analysis[session_id].question, lookups[session_id]) for session_id in checked),
            heartbeat,
        )

        activity = await database_sync_to_async(window.activity, thread_sensitive=False)(stitched, set(session_ids))
        questions = {session_id: member.question for session_id, member in analysis.items()}
        # Fingerprinting parses every query, so it runs off the event loop that sends the heartbeats.
        groups = await asyncio.to_thread(_candidate_groups, activity, catalog, questions)
        selection = select_for_judging(groups, _JUDGE_CALL_CAP)
        if selection.over_cap:
            logger.warning("data_catalog_effectiveness_judge_cap_reached", team_id=team_id, over_cap=selection.over_cap)
        verdicts = await judge_groups(
            client,
            selection.groups,
            catalog.briefs,
            heartbeat,
            questions=questions,
        )
        # Results with no judged match after an outage would look like a clean week, so the activity retries.
        if selection.groups and all(verdict.failed for verdict in verdicts):
            raise JudgeUnavailable(f"All {len(verdicts)} judge calls failed.")

    matches_by_session = _matches_from_verdicts(selection.groups, verdicts)
    metric_names = {metric_id: name for name, metric_id in catalog.metric_ids_by_name.items()}
    listings = await database_sync_to_async(window.listings, thread_sensitive=False)(
        stitched, _sessions_needing_listings(matches_by_session, activity.calls_by_trace, metric_names)
    )
    coverage = dict(zip(checked, coverage_verdicts, strict=True))

    rows: list[OutcomeRow] = []
    for session_id, member in analysis.items():
        calls = activity.calls_by_trace.get(session_id, [])
        evidence = build_evidence(
            member.session,
            calls=calls,
            verdict=coverage.get(session_id),
            matches=matches_by_session.get(session_id, []),
            metric_ids_by_name=catalog.metric_ids_by_name,
            question=member.question,
        )
        rows.extend(
            classify_session(
                evidence,
                calls=calls,
                listings=listings.get(session_id, []),
                metric_names=metric_names,
                metric_statuses=catalog.metric_statuses,
            )
        )

    return TeamEffectiveness(
        team_id=team_id,
        window_start=window_start,
        window_end=window_end,
        sessions_read=len(sessions),
        is_sample=len(chains) >= EFFECTIVENESS_SESSION_LIMIT,
        chains_read=stitched.chains,
        pieces_read=stitched.pieces,
        stitch_failures=stitched.failed_calls,
        unread_sessions=sum(reading.kind == SessionKind.UNREAD for reading in readings),
        analysis_sessions=len(analysis),
        unchecked_queries=count_unchecked_queries(verdicts, selection.over_cap),
        unchecked_sessions=sum(verdict.failed for verdict in coverage_verdicts),
        telemetry_team_id=telemetry_team_id,
        rows=tuple(mark_examples(rows)),
    )


async def _session_lookups(
    window: _TelemetryWindow, stitched: StitchedSessions, session_ids: list[str], heartbeat: Callable[[], None]
) -> dict[str, SessionLookups]:
    """Each batch is several daily queries, so the activity reports progress after every batch."""
    pieces = [piece for session_id in session_ids for piece in stitched.members[session_id]]
    by_piece: dict[str, SessionLookups] = {}
    for start in range(0, len(pieces), _LOOKUP_BATCH):
        by_piece.update(
            await database_sync_to_async(window.lookup_pieces, thread_sensitive=False)(
                pieces[start : start + _LOOKUP_BATCH]
            )
        )
        heartbeat()
    return {
        session_id: merged
        for session_id in session_ids
        if (merged := merge_lookups([by_piece[piece] for piece in stitched.members[session_id] if piece in by_piece]))
    }


class SessionReadsUnavailable(Exception):
    pass


def _candidate_groups(
    activity: _AgentActivity, catalog: _CatalogView, questions: Mapping[str, str]
) -> list[CandidateGroup]:
    groups = merge_candidate_groups(
        build_candidate_groups(activity.queries, catalog.index),
        nominate_read_metrics(activity.queries, activity.calls_by_trace, catalog.metric_ids_by_name),
    )
    # A metric whose brief did not load cannot be judged, so its candidates drop out here.
    return split_by_question([group for group in groups if group.metric_id in catalog.briefs], questions)


def split_by_question(groups: Iterable[CandidateGroup], questions: Mapping[str, str]) -> list[CandidateGroup]:
    """The judge reads one session question per group, so the same SQL asked for another question is its own group."""
    split: list[CandidateGroup] = []
    for group in groups:
        by_question: dict[str, list[AgentQuery]] = defaultdict(list)
        for occurrence in group.occurrences:
            by_question[questions.get(occurrence.trace_id, "")].append(occurrence)
        split.extend(
            dataclasses.replace(group, intent=runs[0].intent, occurrences=tuple(runs)) for runs in by_question.values()
        )
    return split


def _sessions_needing_listings(
    matches_by_session: dict[str, list[MatchedQuery]],
    calls_by_trace: dict[str, list[CatalogCall]],
    metric_names: dict[UUID, str],
) -> set[str]:
    """Stored listings are large, so read them only for the sessions that hold a missed metric."""
    return {
        session_id
        for session_id, matches in matches_by_session.items()
        if any(
            fetch_outcome(match.query, metric_names.get(match.metric_id, ""), calls_by_trace.get(session_id, []))
            == SessionOutcome.MISSED
            for match in matches
        )
    }


def capture_effectiveness(result: TeamEffectiveness, team: Team) -> None:
    """Send the results to PostHog's own project. The ids repeat for the same session and window, so a
    rerun of a week replaces its events and does not count them twice."""
    distinct_id = _team_distinct_id(team)
    groups = _team_groups(team)
    shared = _shared_properties(team, result.window_start, result.window_end)
    # The SDK drops events once its queue is full, and that drop does not raise, so each batch flushes on its own.
    for start in range(0, len(result.rows), _CAPTURE_BATCH):
        with ph_scoped_capture(raise_on_error=True) as capture:
            for row in result.rows[start : start + _CAPTURE_BATCH]:
                capture(
                    SESSION_OUTCOME_EVENT,
                    distinct_id=distinct_id,
                    groups=groups,
                    timestamp=result.window_start,
                    uuid=_stable_uuid(team.id, result.window_start, row.session_id, row.asset_kind, row.metric_id),
                    properties={
                        **shared,
                        "session_id": row.session_id,
                        "client": row.client,
                        "source": row.source,
                        "outcome": row.outcome.value,
                        "asset_kind": row.asset_kind.value,
                        "is_headline": row.is_headline,
                        "metric_id": str(row.metric_id) if row.metric_id else None,
                        "metric_status": row.metric_status.value if row.metric_status else None,
                        "relation": row.relation.value if row.relation else None,
                        "missed_reason": row.missed_reason.value if row.missed_reason else None,
                        "metric_name": row.metric_name or None,
                        "session_started_at": row.started_at.isoformat() if row.started_at else None,
                        "is_example": row.is_example,
                        "trace_url": trace_url(row.session_id, result.telemetry_team_id),
                    },
                )
    with ph_scoped_capture(raise_on_error=True) as capture:
        capture(
            TEAM_MEASURED_EVENT,
            distinct_id=distinct_id,
            groups=groups,
            timestamp=result.window_start,
            uuid=_stable_uuid(team.id, result.window_start, "team", AssetKind.NONE, None),
            properties={
                **shared,
                "sessions_read": result.sessions_read,
                "is_sample": result.is_sample,
                "chains_read": result.chains_read,
                "pieces_read": result.pieces_read,
                "stitch_failures": result.stitch_failures,
                "unread_sessions": result.unread_sessions,
                "analysis_sessions": result.analysis_sessions,
                "unchecked_queries": result.unchecked_queries,
                "unchecked_sessions": result.unchecked_sessions,
                **{f"sessions_{outcome.value}": count for outcome, count in result.headline_counts.items()},
            },
        )


def capture_team_skipped(skipped: TeamSkipped, team: Team, *, window_start: datetime, window_end: datetime) -> None:
    """Without this event, a skipped team looks the same as a team that never ran."""
    with ph_scoped_capture(raise_on_error=True) as capture:
        capture(
            TEAM_MEASURED_EVENT,
            distinct_id=_team_distinct_id(team),
            groups=_team_groups(team),
            timestamp=window_start,
            uuid=_stable_uuid(team.id, window_start, "team", AssetKind.NONE, None),
            properties={
                **_shared_properties(team, window_start, window_end),
                "skipped_reason": skipped.reason.value,
            },
        )


def _team_distinct_id(team: Team) -> str:
    return f"data_catalog_effectiveness_team_{team.id}"


def _team_groups(team: Team) -> dict[str, str]:
    return {"organization": str(team.organization_id), "project": str(team.uuid)}


def _shared_properties(team: Team, window_start: datetime, window_end: datetime) -> dict[str, Any]:
    return {
        "$process_person_profile": False,
        "team_id": team.id,
        "definition_version": DEFINITION_VERSION,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
    }


def _stable_uuid(
    team_id: int, window_start: datetime, subject: str, asset_kind: AssetKind, metric_id: UUID | None
) -> str:
    name = f"{DEFINITION_VERSION}:{team_id}:{window_start.isoformat()}:{subject}:{asset_kind}:{metric_id}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, name))
