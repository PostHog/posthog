"""Plan and run a replay of destination and workflow invocations that failed during an incident.

The rerun endpoint replays whatever matches a filter. That is too blunt after an
incident, because some failed invocations must not be sent again:

- A destination that syncs person state (a CRM contact upsert) needs only the
  latest failed run per person, and none when a later run for that person
  succeeded. The other runs only send the destination redundant updates.
- An event that a later run already delivered would be delivered twice.
- A function whose integration still fails would only fail again.

So a replay is computed up front as an explicit list of invocation IDs, shown to
an operator, and sent by ID. A plan can be sent once: the send claims the plan's
fingerprint first, so a double submit or a second operator cannot send it again.
The rerun worker also re-checks each invocation's latest status before it
enqueues it.
"""

import uuid
import hashlib
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from django.core.cache import caches

import structlog
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    ConnectTimeout,
)
from urllib3.exceptions import NewConnectionError

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.models.team.team import Team
from posthog.plugins.plugin_server_api import rerun_hog_invocations

from products.cdp.backend.models.hog_functions.hog_function import TYPES_THAT_CAN_RERUN, HogFunction
from products.cdp.backend.presentation.hog_invocations.rerun import (
    HOG_INVOCATION_RERUN_MAX_COUNT,
    RERUN_MAX_WINDOW_DAYS,
)
from products.workflows.backend.facade.workflows import get_workflow_replay_targets

logger = structlog.get_logger(__name__)

# Templates whose runs write the current state of the triggering person to the
# destination, so one successful run makes every earlier failed run for that
# person redundant. A template keyed on something else, like a company, does
# not belong here, because two failures of one person can target two records.
DEFAULT_LATEST_PER_PERSON_TEMPLATE_IDS = ("template-hubspot",)

# Long enough to look up a replay after it ran, and to keep refusing a resend of
# the same plan while its runs are still in flight.
REPLAY_STATE_TTL_SECONDS = 7 * 24 * 60 * 60
FUNCTION_RESERVATION_SECONDS = 60 * 60
STALLED_AFTER = timedelta(minutes=15)

FunctionKind = Literal["hog_function", "hog_flow"]

SkipReason = Literal[
    "function_not_replayable",
    "sends_sensitive_email",
    "already_rerun",
    "already_delivered",
    "superseded_by_later_success",
    "older_run_for_same_person",
    "no_success_since_window",
    "failing_before_window",
]

SKIP_REASON_LABELS: dict[SkipReason, str] = {
    "function_not_replayable": "Disabled, deleted, or of a type that cannot be re-run",
    "sends_sensitive_email": "Workflow sends sensitive email, whose message data is not stored",
    "already_rerun": "Already re-run once",
    "already_delivered": "The same event was delivered by a later run",
    "superseded_by_later_success": "A later run for the same person succeeded",
    "older_run_for_same_person": "Not the latest failed run for this person",
    "no_success_since_window": "Function has not succeeded since the window ended",
    "failing_before_window": "Function already failed this way in the day before the window",
}

# How far before the window to look for the same failure. A function that failed
# this way before the incident has a cause of its own, like a revoked key, so a
# replay would only fail again.
BASELINE_LOOKBACK = timedelta(days=1)

# Candidate functions: any function with a failed lifecycle row in the window
# that matches the error filters. The row-level filter is a superset of the
# invocation-level check in _FAILURES_QUERY, which is the one that decides.
_CANDIDATE_FUNCTIONS_QUERY = """
SELECT DISTINCT team_id, function_id
FROM hog_invocation_results
WHERE function_kind = %(function_kind)s
    AND scheduled_at >= %(window_start)s
    AND scheduled_at < %(window_end)s
    AND status = 'failed'
    {team_clause}
    {error_kind_clause}
    {error_message_clause}
"""

# The scans below have no upper bound on scheduled_at, because a later retry row
# (cyclotron rewrites scheduled_at on every attempt) or a later success must
# count when the latest status is resolved. Aliases differ from the column
# names, because the ClickHouse analyzer resolves a name in WHERE to a
# same-named SELECT alias.
#
# The latest row must be inside the window, because the rerun worker selects
# rows inside the window and would not find the invocation otherwise. Ordering
# between runs uses first_scheduled_at, which a retry does not rewrite.
#
# Only invocations with a failed row in the window are grouped. Without that
# restriction the query groups every run since the window start, which at
# incident scale includes hours of traffic that cannot be a target.
_FAILURES_QUERY = """
SELECT
    function_id,
    invocation_id,
    argMax(person_id, version) AS latest_person_id,
    argMax(event_uuid, version) AS latest_event_uuid,
    min(first_scheduled_at) AS original_scheduled_at,
    max(is_retry) AS was_rerun
FROM hog_invocation_results
WHERE function_kind = %(function_kind)s
    AND team_id IN %(team_ids)s
    AND function_id IN %(function_ids)s
    AND scheduled_at >= %(window_start)s
    AND invocation_id IN (
        SELECT invocation_id
        FROM hog_invocation_results
        WHERE function_kind = %(function_kind)s
            AND team_id IN %(team_ids)s
            AND function_id IN %(function_ids)s
            AND scheduled_at >= %(window_start)s
            AND scheduled_at < %(window_end)s
            AND status = 'failed'
    )
GROUP BY function_id, invocation_id
HAVING argMax(is_deleted, version) = 0
    AND argMax(status, version) = 'failed'
    AND argMax(scheduled_at, version) >= %(window_start)s
    AND argMax(scheduled_at, version) < %(window_end)s
    {error_kind_clause}
    {error_message_clause}
"""

# Only the successes that can change a decision about one of the failures: the
# same person or the same event on the same function. The result stays
# proportional to the failures and not to the traffic after the incident. The
# match runs against the failures query inside ClickHouse, because passing the
# failures' person and event IDs as literals exceeds the maximum query size at
# incident scale. Rows are matched before grouping, which is safe because the
# person and the event of an invocation are the same on all of its rows.
_RELATED_SUCCESSES_QUERY = """
WITH failures AS ({failures_query})
SELECT function_id, latest_person_id, latest_event_uuid, original_scheduled_at
FROM (
    SELECT
        function_id,
        invocation_id,
        argMax(person_id, version) AS latest_person_id,
        argMax(event_uuid, version) AS latest_event_uuid,
        min(first_scheduled_at) AS original_scheduled_at
    FROM hog_invocation_results
    WHERE function_kind = %(function_kind)s
        AND team_id IN %(team_ids)s
        AND function_id IN %(function_ids)s
        AND scheduled_at >= %(window_start)s
        AND (
            (function_id, person_id) IN (
                SELECT function_id, latest_person_id FROM failures WHERE latest_person_id != ''
            )
            OR (function_id, event_uuid) IN (
                SELECT function_id, latest_event_uuid FROM failures WHERE latest_event_uuid != ''
            )
        )
    GROUP BY function_id, invocation_id
    HAVING argMax(is_deleted, version) = 0 AND argMax(status, version) = 'succeeded'
)
"""

_FUNCTIONS_FAILING_BEFORE_QUERY = """
SELECT DISTINCT function_id
FROM hog_invocation_results
WHERE function_kind = %(function_kind)s
    AND team_id IN %(team_ids)s
    AND function_id IN %(function_ids)s
    AND scheduled_at >= %(baseline_start)s
    AND scheduled_at < %(window_start)s
    AND status = 'failed'
    {error_kind_clause}
    {error_message_clause}
"""

_FUNCTIONS_WITH_SUCCESS_SINCE_QUERY = """
SELECT DISTINCT function_id
FROM hog_invocation_results
WHERE function_kind = %(function_kind)s
    AND team_id IN %(team_ids)s
    AND function_id IN %(function_ids)s
    AND scheduled_at >= %(since)s
    AND status = 'succeeded'
"""


@frozen
class ReplayCriteria:
    window_start: datetime
    window_end: datetime
    # Case-insensitive substring of the latest error message, e.g. "401".
    error_message_contains: str
    error_kinds: tuple[str, ...]
    team_ids: tuple[int, ...]
    template_ids: tuple[str, ...]
    exclude_template_ids: tuple[str, ...]
    latest_per_person_template_ids: tuple[str, ...]
    require_success_since_window: bool
    skip_already_rerun: bool
    skip_failing_before_window: bool
    include_workflows: bool

    def __post_init__(self) -> None:
        if self.window_start.tzinfo is None or self.window_end.tzinfo is None:
            raise ValueError("window_start and window_end must be timezone-aware")
        if self.window_end <= self.window_start:
            raise ValueError("window_end must be after window_start")
        if self.window_end - self.window_start > timedelta(days=RERUN_MAX_WINDOW_DAYS):
            raise ValueError(f"The window cannot exceed {RERUN_MAX_WINDOW_DAYS} days")
        if not self.error_message_contains and not self.error_kinds:
            # Without an error filter the plan would replay every failure in the
            # window, including ones the incident did not cause.
            raise ValueError("Set error_message_contains or error_kinds")

    def to_payload(self) -> dict[str, Any]:
        return {
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "error_message_contains": self.error_message_contains,
            "error_kinds": list(self.error_kinds),
            "team_ids": list(self.team_ids),
            "template_ids": list(self.template_ids),
            "exclude_template_ids": list(self.exclude_template_ids),
            "latest_per_person_template_ids": list(self.latest_per_person_template_ids),
            "require_success_since_window": self.require_success_since_window,
            "skip_already_rerun": self.skip_already_rerun,
            "skip_failing_before_window": self.skip_failing_before_window,
            "include_workflows": self.include_workflows,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ReplayCriteria":
        return cls(
            window_start=datetime.fromisoformat(payload["window_start"]),
            window_end=datetime.fromisoformat(payload["window_end"]),
            error_message_contains=payload["error_message_contains"],
            error_kinds=tuple(payload["error_kinds"]),
            team_ids=tuple(payload["team_ids"]),
            template_ids=tuple(payload["template_ids"]),
            exclude_template_ids=tuple(payload["exclude_template_ids"]),
            latest_per_person_template_ids=tuple(payload["latest_per_person_template_ids"]),
            require_success_since_window=payload["require_success_since_window"],
            skip_already_rerun=payload["skip_already_rerun"],
            skip_failing_before_window=payload["skip_failing_before_window"],
            # A task queued before workflows could be replayed carries no such key.
            include_workflows=payload.get("include_workflows", False),
        )


@frozen
class FunctionReplay:
    team_id: int
    team_name: str
    organization_name: str
    function_kind: FunctionKind
    function_id: str
    function_name: str
    # Empty for a workflow, whose steps can use several templates.
    template_id: str
    invocation_ids: tuple[str, ...]
    skipped: dict[SkipReason, int]


@frozen
class TeamReplaySummary:
    team_id: int
    team_name: str
    organization_name: str
    function_count: int
    invocation_count: int


@frozen
class ReplayPlan:
    criteria: ReplayCriteria
    functions: tuple[FunctionReplay, ...]

    @property
    def replayable_functions(self) -> tuple[FunctionReplay, ...]:
        return tuple(f for f in self.functions if f.invocation_ids)

    @property
    def invocation_count(self) -> int:
        return sum(len(f.invocation_ids) for f in self.functions)

    @property
    def request_count(self) -> int:
        return sum(-(-len(f.invocation_ids) // HOG_INVOCATION_RERUN_MAX_COUNT) for f in self.functions)

    @property
    def team_count(self) -> int:
        return len({f.team_id for f in self.replayable_functions})

    @property
    def skipped(self) -> dict[SkipReason, int]:
        total: Counter[SkipReason] = Counter()
        for f in self.functions:
            total.update(f.skipped)
        return dict(total)

    @property
    def invocations_by_template(self) -> dict[str, int]:
        counts: Counter[str] = Counter()
        for f in self.functions:
            counts["(workflows)" if f.function_kind == "hog_flow" else f.template_id] += len(f.invocation_ids)
        return dict(counts.most_common())

    @property
    def teams(self) -> tuple[TeamReplaySummary, ...]:
        by_team: dict[int, list[FunctionReplay]] = {}
        for f in self.replayable_functions:
            by_team.setdefault(f.team_id, []).append(f)
        summaries = [
            TeamReplaySummary(
                team_id=team_id,
                team_name=functions[0].team_name,
                organization_name=functions[0].organization_name,
                function_count=len(functions),
                invocation_count=sum(len(f.invocation_ids) for f in functions),
            )
            for team_id, functions in by_team.items()
        ]
        return tuple(sorted(summaries, key=lambda s: s.invocation_count, reverse=True))

    @property
    def fingerprint(self) -> str:
        """Identifies the exact set of invocations, so a send can refuse a plan that changed after the preview."""
        digest = hashlib.sha256()
        for f in sorted(self.replayable_functions, key=lambda f: f.function_id):
            for invocation_id in sorted(f.invocation_ids):
                digest.update(f"{f.function_id}:{invocation_id}\n".encode())
        return digest.hexdigest()[:16]


@frozen
class FunctionReplayResult:
    team_id: int
    function_kind: FunctionKind
    function_id: str
    invocation_count: int
    status_code: int
    detail: str


@frozen
class _Target:
    """A destination or a workflow with failures in the window."""

    team_id: int
    team_name: str
    organization_name: str
    function_kind: FunctionKind
    function_id: str
    function_name: str
    template_id: str
    not_replayable: SkipReason | None
    latest_per_person: bool


@frozen
class _Failure:
    function_id: str
    invocation_id: str
    person_id: str
    event_uuid: str
    scheduled_at: datetime
    was_rerun: bool


@frozen
class _Success:
    function_id: str
    person_id: str
    event_uuid: str
    scheduled_at: datetime


def _as_utc(value: datetime) -> datetime:
    # The ClickHouse driver returns naive datetimes for DateTime64 columns.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@frozen
class _ErrorClauses:
    kind: str
    message: str

    def apply(self, template: str, **values: str) -> str:
        return template.format(error_kind_clause=self.kind, error_message_clause=self.message, **values)


def _error_clauses(criteria: ReplayCriteria, *, column: str, params: dict[str, Any]) -> _ErrorClauses:
    kind = message = ""
    if criteria.error_kinds:
        kind = f"AND {column.format('error_kind')} IN %(error_kinds)s"
        params["error_kinds"] = list(criteria.error_kinds)
    if criteria.error_message_contains:
        message = f"AND positionCaseInsensitive({column.format('error_message')}, %(error_message_contains)s) > 0"
        params["error_message_contains"] = criteria.error_message_contains
    return _ErrorClauses(kind=kind, message=message)


def _find_candidate_functions(criteria: ReplayCriteria, kind: FunctionKind) -> list[tuple[int, str]]:
    params: dict[str, Any] = {
        "function_kind": kind,
        "window_start": criteria.window_start,
        "window_end": criteria.window_end,
    }
    team_clause = ""
    if criteria.team_ids:
        team_clause = "AND team_id IN %(team_ids)s"
        params["team_ids"] = list(criteria.team_ids)
    clauses = _error_clauses(criteria, column="{}", params=params)
    rows = sync_execute(clauses.apply(_CANDIDATE_FUNCTIONS_QUERY, team_clause=team_clause), params)
    return [(int(row[0]), str(row[1])) for row in rows]


def _failures_query(criteria: ReplayCriteria, scope: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    params = {**scope, "window_end": criteria.window_end}
    clauses = _error_clauses(criteria, column="argMax({}, version)", params=params)
    return clauses.apply(_FAILURES_QUERY), params


def _load_failures(criteria: ReplayCriteria, scope: dict[str, Any]) -> list[_Failure]:
    rows = sync_execute(*_failures_query(criteria, scope))
    return [
        _Failure(
            function_id=row[0],
            invocation_id=row[1],
            person_id=row[2],
            event_uuid=row[3],
            scheduled_at=_as_utc(row[4]),
            was_rerun=bool(row[5]),
        )
        for row in rows
    ]


def _load_related_successes(criteria: ReplayCriteria, scope: dict[str, Any]) -> list[_Success]:
    failures_query, params = _failures_query(criteria, scope)
    rows = sync_execute(_RELATED_SUCCESSES_QUERY.format(failures_query=failures_query), params)
    return [
        _Success(function_id=row[0], person_id=row[1], event_uuid=row[2], scheduled_at=_as_utc(row[3])) for row in rows
    ]


def _plan_function(
    target: _Target,
    failures: list[_Failure],
    successes: list[_Success],
    *,
    succeeded_since_window: bool,
    failing_before_window: bool,
    criteria: ReplayCriteria,
) -> FunctionReplay:
    skipped: Counter[SkipReason] = Counter()

    if target.not_replayable:
        skipped[target.not_replayable] = len(failures)
        return _function_replay(target, (), skipped)
    if criteria.skip_failing_before_window and failing_before_window:
        skipped["failing_before_window"] = len(failures)
        return _function_replay(target, (), skipped)
    if criteria.require_success_since_window and not succeeded_since_window:
        skipped["no_success_since_window"] = len(failures)
        return _function_replay(target, (), skipped)

    delivered_events = {s.event_uuid for s in successes if s.event_uuid}
    last_success_by_person: dict[str, datetime] = {}
    for success in successes:
        if success.person_id:
            last_success_by_person[success.person_id] = max(
                success.scheduled_at, last_success_by_person.get(success.person_id, success.scheduled_at)
            )

    latest_per_person = target.latest_per_person
    latest_failure_by_person: dict[str, str] = {}
    for failure in sorted(failures, key=lambda f: f.scheduled_at):
        if failure.person_id:
            latest_failure_by_person[failure.person_id] = failure.invocation_id

    replay: list[str] = []
    for failure in failures:
        if criteria.skip_already_rerun and failure.was_rerun:
            skipped["already_rerun"] += 1
        elif failure.event_uuid and failure.event_uuid in delivered_events:
            skipped["already_delivered"] += 1
        elif latest_per_person and failure.person_id:
            last_success = last_success_by_person.get(failure.person_id)
            if last_success and last_success > failure.scheduled_at:
                skipped["superseded_by_later_success"] += 1
            elif latest_failure_by_person[failure.person_id] != failure.invocation_id:
                skipped["older_run_for_same_person"] += 1
            else:
                replay.append(failure.invocation_id)
        else:
            replay.append(failure.invocation_id)

    return _function_replay(target, tuple(sorted(replay)), skipped)


def _function_replay(target: _Target, invocation_ids: tuple[str, ...], skipped: Counter[SkipReason]) -> FunctionReplay:
    return FunctionReplay(
        team_id=target.team_id,
        team_name=target.team_name,
        organization_name=target.organization_name,
        function_kind=target.function_kind,
        function_id=target.function_id,
        function_name=target.function_name,
        template_id=target.template_id,
        invocation_ids=invocation_ids,
        skipped=dict(skipped),
    )


def _destination_targets(criteria: ReplayCriteria, candidates: list[tuple[int, str]]) -> list[_Target]:
    # nosemgrep: idor-lookup-without-team -- staff-only incident tooling that spans teams by design; each id is paired with the team ClickHouse reported for it
    queryset = HogFunction.objects.select_related("team", "team__organization").filter(
        id__in=[function_id for _, function_id in candidates],
        team_id__in={team_id for team_id, _ in candidates},
    )
    if criteria.template_ids:
        queryset = queryset.filter(template_id__in=criteria.template_ids)
    if criteria.exclude_template_ids:
        queryset = queryset.exclude(template_id__in=criteria.exclude_template_ids)
    return [
        _Target(
            team_id=function.team_id,
            team_name=function.team.name,
            organization_name=function.team.organization.name,
            function_kind="hog_function",
            function_id=str(function.id),
            function_name=function.name or "",
            template_id=function.template_id or "",
            not_replayable=(
                "function_not_replayable"
                if not function.enabled or function.deleted or function.type not in TYPES_THAT_CAN_RERUN
                else None
            ),
            latest_per_person=(function.template_id or "") in criteria.latest_per_person_template_ids,
        )
        for function in queryset
    ]


def _workflow_targets(criteria: ReplayCriteria, candidates: list[tuple[int, str]]) -> list[_Target]:
    workflows = get_workflow_replay_targets(
        team_ids=sorted({team_id for team_id, _ in candidates}),
        workflow_ids=[workflow_id for _, workflow_id in candidates],
    )
    # A workflow matches a template filter when one of its steps uses the template.
    if criteria.template_ids:
        workflows = [w for w in workflows if set(w.template_ids) & set(criteria.template_ids)]
    if criteria.exclude_template_ids:
        workflows = [w for w in workflows if not set(w.template_ids) & set(criteria.exclude_template_ids)]
    teams = {
        team.id: team
        for team in Team.objects.select_related("organization").filter(id__in={w.team_id for w in workflows})
    }
    targets = []
    for workflow in workflows:
        not_replayable: SkipReason | None = None
        if workflow.status != "active":
            not_replayable = "function_not_replayable"
        elif workflow.sends_sensitive_email:
            not_replayable = "sends_sensitive_email"
        team = teams[workflow.team_id]
        targets.append(
            _Target(
                team_id=workflow.team_id,
                team_name=team.name,
                organization_name=team.organization.name,
                function_kind="hog_flow",
                function_id=workflow.id,
                function_name=workflow.name,
                template_id="",
                not_replayable=not_replayable,
                # A workflow run can send messages too, so a later run does not make an earlier one redundant.
                latest_per_person=False,
            )
        )
    return targets


def plan_replay(criteria: ReplayCriteria) -> ReplayPlan:
    kinds: list[FunctionKind] = ["hog_function", "hog_flow"] if criteria.include_workflows else ["hog_function"]
    with tags_context(product=Product.PIPELINE_DESTINATIONS, feature=Feature.DEBUG_QUERY):
        replays = [replay for kind in kinds for replay in _plan_kind(criteria, kind)]
    replays.sort(key=lambda f: (-len(f.invocation_ids), f.team_id, f.function_id))
    return ReplayPlan(criteria=criteria, functions=tuple(replays))


def _plan_kind(criteria: ReplayCriteria, kind: FunctionKind) -> list[FunctionReplay]:
    candidates = _find_candidate_functions(criteria, kind)
    if not candidates:
        return []
    if kind == "hog_function":
        targets = _destination_targets(criteria, candidates)
    else:
        targets = _workflow_targets(criteria, candidates)
    if not targets:
        return []

    scope: dict[str, Any] = {
        "function_kind": kind,
        "team_ids": sorted({t.team_id for t in targets}),
        "function_ids": [t.function_id for t in targets],
        "window_start": criteria.window_start,
    }
    failures = _load_failures(criteria, scope)
    if not failures:
        return []
    successes = _load_related_successes(criteria, scope)
    succeeded_since_window = {
        row[0]
        for row in sync_execute(
            _FUNCTIONS_WITH_SUCCESS_SINCE_QUERY,
            {
                "function_kind": kind,
                "team_ids": scope["team_ids"],
                "function_ids": scope["function_ids"],
                "since": criteria.window_end,
            },
        )
    }

    failing_before_window: set[str] = set()
    if criteria.skip_failing_before_window:
        params: dict[str, Any] = {
            "function_kind": kind,
            "team_ids": scope["team_ids"],
            "function_ids": scope["function_ids"],
            "baseline_start": criteria.window_start - BASELINE_LOOKBACK,
            "window_start": criteria.window_start,
        }
        clauses = _error_clauses(criteria, column="{}", params=params)
        failing_before_window = {row[0] for row in sync_execute(clauses.apply(_FUNCTIONS_FAILING_BEFORE_QUERY), params)}

    failures_by_function: dict[str, list[_Failure]] = {}
    for failure in failures:
        failures_by_function.setdefault(failure.function_id, []).append(failure)
    successes_by_function: dict[str, list[_Success]] = {}
    for success in successes:
        successes_by_function.setdefault(success.function_id, []).append(success)

    return [
        _plan_function(
            target,
            failures_by_function[target.function_id],
            successes_by_function.get(target.function_id, []),
            succeeded_since_window=target.function_id in succeeded_since_window,
            failing_before_window=target.function_id in failing_before_window,
            criteria=criteria,
        )
        for target in targets
        if target.function_id in failures_by_function
    ]


# Claims and state coordinate concurrent senders, so every read must see the latest write.
replay_cache = caches["cdp_invocation_replay"]


def _state_key(fingerprint: str) -> str:
    return f"cdp:invocation_replay:{fingerprint}"


def _claim_key(fingerprint: str) -> str:
    return f"cdp:invocation_replay:claim:{fingerprint}"


class ReplayOverlapError(Exception):
    """Another replay still holds some of the same destinations."""


def _function_reservation_key(function_id: str) -> str:
    return f"cdp:invocation_replay:function:{function_id}"


def _release_functions(fingerprint: str, function_ids: list[str]) -> None:
    for function_id in function_ids:
        if replay_cache.get(_function_reservation_key(function_id)) == fingerprint:
            replay_cache.delete(_function_reservation_key(function_id))


def claim_replay(plan: ReplayPlan, *, actor: str) -> str | None:
    """Reserve the plan for one send. Returns the claim token, or None when this exact plan was already claimed.

    Raises ReplayOverlapError when another recent plan reserved one of the same destinations.
    """
    fingerprint = plan.fingerprint
    claim = uuid.uuid4().hex
    if not replay_cache.add(_claim_key(fingerprint), claim, timeout=REPLAY_STATE_TTL_SECONDS):
        return None
    # Two plans from different filters can share runs. Their rerun jobs would then
    # queue those runs twice, because the rerun worker does not reserve a run before
    # it queues it. The reservation lasts until the send ends, and then for
    # FUNCTION_RESERVATION_SECONDS, which is long enough for lifecycle rows to show
    # a replayed run as no longer failed, so a later plan leaves it out. A request
    # that may have queued its runs keeps the reservation until staff release the plan.
    reserved: list[str] = []
    try:
        for function in plan.replayable_functions:
            if not replay_cache.add(
                _function_reservation_key(function.function_id), fingerprint, timeout=REPLAY_STATE_TTL_SECONDS
            ):
                raise ReplayOverlapError(
                    f"Another replay still holds {function.function_id}. "
                    "Wait for its runs to finish, or release it on its status page, then preview again."
                )
            reserved.append(function.function_id)
        replay_cache.set(
            _state_key(fingerprint),
            {
                "status": "queued",
                "actor": actor,
                "updated_at": datetime.now(UTC).isoformat(),
                "invocation_count": plan.invocation_count,
                "request_count": plan.request_count,
                "function_ids": reserved,
                "results": [],
            },
            timeout=REPLAY_STATE_TTL_SECONDS,
        )
    except BaseException:
        # Without a state record staff cannot release these keys, so a failed claim must not keep them.
        _release_functions(fingerprint, reserved)
        _release_claim(fingerprint)
        raise
    return claim


def start_claimed_send(fingerprint: str, claim: str) -> bool:
    """True once per claim, and only while the claim still holds the plan.

    A task can start after staff released its plan as stalled and sent it again.
    That task holds the old claim and must send nothing, or the runs go out twice.
    """
    if replay_cache.get(_claim_key(fingerprint)) != claim:
        return False
    if not replay_cache.add(f"{_claim_key(fingerprint)}:started:{claim}", 1, timeout=REPLAY_STATE_TTL_SECONDS):
        return False
    # Planning again can take a minute. A queued state with an old timestamp would offer staff the stalled release meanwhile.
    _save_state(fingerprint, status="running")
    return True


def _release_claim(fingerprint: str) -> None:
    # Only for a send that queued nothing. The same plan is then still the right
    # plan, and the operator must be able to send it again.
    replay_cache.delete(_claim_key(fingerprint))


def is_replay_claimed(fingerprint: str) -> bool:
    return replay_cache.get(_claim_key(fingerprint)) is not None


def can_release_replay(fingerprint: str) -> bool:
    """True when the plan is claimed and no sender still works on it.

    A sender records progress at least once per request timeout, so a queued or
    running replay without an update for longer than STALLED_AFTER lost its worker.
    """
    state = get_replay_state(fingerprint)
    if state is None or not is_replay_claimed(fingerprint):
        return False
    if state["status"] in ("done", "failed"):
        return True
    updated_at = datetime.fromisoformat(state.get("updated_at") or datetime.now(UTC).isoformat())
    return datetime.now(UTC) - updated_at > STALLED_AFTER


def release_replay_claim(fingerprint: str, *, actor: str) -> bool:
    """Let staff send a plan again after they checked that its earlier send queued nothing."""
    if not can_release_replay(fingerprint):
        return False
    logger.warning("invocation_replay_claim_released", actor=actor, fingerprint=fingerprint)
    state = get_replay_state(fingerprint) or {}
    _save_state(fingerprint, status="failed", detail=f"Released for resending by {actor}.")
    _release_functions(fingerprint, state.get("function_ids", []))
    _release_claim(fingerprint)
    return True


def _never_reached_cdp(error: Exception) -> bool:
    # A request that never opened a connection queued nothing. Any other error,
    # for example a read timeout, can come after the CDP API queued the rerun.
    if isinstance(error, ConnectTimeout):
        return True
    if isinstance(error, RequestsConnectionError) and error.args:
        return isinstance(getattr(error.args[0], "reason", None), NewConnectionError)
    return False


def get_replay_state(fingerprint: str) -> dict[str, Any] | None:
    return replay_cache.get(_state_key(fingerprint))


def _save_state(fingerprint: str, **changes: Any) -> None:
    state = get_replay_state(fingerprint) or {}
    state = {**state, **changes, "updated_at": datetime.now(UTC).isoformat()}
    replay_cache.set(_state_key(fingerprint), state, timeout=REPLAY_STATE_TTL_SECONDS)


def _release_everything(fingerprint: str) -> None:
    _release_functions(fingerprint, (get_replay_state(fingerprint) or {}).get("function_ids", []))
    _release_claim(fingerprint)


def mark_replay_refused(fingerprint: str, reason: str) -> None:
    _save_state(fingerprint, status="refused", detail=reason)
    _release_everything(fingerprint)


def mark_replay_failed(fingerprint: str, reason: str) -> None:
    _save_state(fingerprint, status="failed", detail=reason)
    _release_everything(fingerprint)


def mark_replay_dispatch_unknown(fingerprint: str) -> None:
    """The task may have been queued although queueing raised, so the plan stays blocked until staff release it."""
    _save_state(fingerprint, status="failed", detail=_DISPATCH_UNKNOWN_DETAIL)


_DISPATCH_UNKNOWN_DETAIL = (
    "Queueing the replay task failed, but the task may still run, so this plan stays blocked. "
    "Check the runs on the destinations first. Then allow a resend if nothing was queued."
)

_UNCERTAIN_DETAIL = (
    "Some requests ended without a clear answer and may still have queued their runs, so this plan stays blocked. "
    "Check the runs on the destinations first. Then allow a resend if nothing was queued."
)


def execute_replay(plan: ReplayPlan, *, actor: str) -> list[FunctionReplayResult]:
    """Send a claimed plan, one rerun request per chunk, and record progress under its fingerprint."""
    fingerprint = plan.fingerprint
    logger.info(
        "invocation_replay_started",
        actor=actor,
        fingerprint=fingerprint,
        function_count=len(plan.replayable_functions),
        invocation_count=plan.invocation_count,
    )
    _save_state(fingerprint, status="running")
    criteria = plan.criteria
    results: list[FunctionReplayResult] = []
    # Requests that may have queued a rerun although they did not return 200.
    uncertain_requests = 0
    # Destinations whose runs a request may have queued. The others are released
    # at the end, so a new plan can send their runs without waiting.
    possibly_queued: set[str] = set()
    uncertain_functions: set[str] = set()
    in_flight = False
    try:
        for function in plan.replayable_functions:
            for offset in range(0, len(function.invocation_ids), HOG_INVOCATION_RERUN_MAX_COUNT):
                chunk = list(function.invocation_ids[offset : offset + HOG_INVOCATION_RERUN_MAX_COUNT])
                in_flight = True
                uncertain = False
                try:
                    response = rerun_hog_invocations(
                        team_id=function.team_id,
                        function_kind=function.function_kind,
                        function_id=function.function_id,
                        payload={
                            "filter": {
                                "window_start": criteria.window_start.isoformat(),
                                "window_end": criteria.window_end.isoformat(),
                                "status": ["failed"],
                                "invocation_ids": chunk,
                                "max_count": len(chunk),
                            }
                        },
                    )
                    status_code, detail = response.status_code, response.text[:500]
                    # A gateway in front of the CDP API can answer 502 or 504 after the API queued the rerun.
                    uncertain = status_code >= 500
                except Exception as error:
                    # One unreachable request must not stop the rest of the plan. The
                    # result records it, so the operator can preview again and send
                    # only what is still failed.
                    status_code, detail = 0, repr(error)[:500]
                    uncertain = not _never_reached_cdp(error)
                in_flight = False
                uncertain_requests += uncertain
                if uncertain:
                    uncertain_functions.add(function.function_id)
                if status_code == 200 or uncertain:
                    possibly_queued.add(function.function_id)
                result = FunctionReplayResult(
                    team_id=function.team_id,
                    function_kind=function.function_kind,
                    function_id=function.function_id,
                    invocation_count=len(chunk),
                    status_code=status_code,
                    detail=detail,
                )
                results.append(result)
                _save_state(
                    fingerprint,
                    results=[
                        {
                            "team_id": r.team_id,
                            "function_kind": r.function_kind,
                            "function_id": r.function_id,
                            "invocation_count": r.invocation_count,
                            "status_code": r.status_code,
                            "detail": r.detail,
                        }
                        for r in results
                    ],
                )
    except BaseException:
        queued_nothing = not in_flight and not uncertain_requests and not any(r.status_code == 200 for r in results)
        if queued_nothing:
            mark_replay_failed(fingerprint, "The send stopped before any request was sent.")
        else:
            _save_state(fingerprint, status="failed", detail=_UNCERTAIN_DETAIL)
        raise
    failed_requests = sum(1 for r in results if r.status_code != 200)
    _save_state(
        fingerprint,
        status="done",
        failed_requests=failed_requests,
        detail=_UNCERTAIN_DETAIL if uncertain_requests else "",
    )
    if results and failed_requests == len(results) and not uncertain_requests:
        _release_everything(fingerprint)
    else:
        queued_nothing_for = [f.function_id for f in plan.replayable_functions if f.function_id not in possibly_queued]
        _release_functions(fingerprint, queued_nothing_for)
        for function_id in possibly_queued - uncertain_functions:
            replay_cache.touch(_function_reservation_key(function_id), timeout=FUNCTION_RESERVATION_SECONDS)
    logger.info("invocation_replay_finished", actor=actor, fingerprint=fingerprint, failed_requests=failed_requests)
    return results
