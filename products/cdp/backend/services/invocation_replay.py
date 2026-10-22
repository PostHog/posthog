"""Plan and run a replay of destination invocations that failed during an incident.

The rerun endpoint replays whatever matches a filter. That is too blunt after an
incident, because some failed invocations must not be sent again:

- A destination that syncs person state (a CRM contact upsert) needs only the
  latest failed run per person. A run that a later successful run superseded
  would overwrite newer data with the old payload.
- An event that a later run already delivered would be delivered twice.
- A function whose integration still fails would only fail again.

So a replay is computed up front as an explicit list of invocation IDs, shown to
an operator, and sent by ID. The rerun worker re-checks each invocation's latest
status before it enqueues it, so sending the same plan twice does not send an
invocation twice.
"""

import hashlib
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import structlog

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.plugins.plugin_server_api import rerun_hog_invocations

from products.cdp.backend.models.hog_functions.hog_function import TYPES_THAT_CAN_RERUN, HogFunction
from products.cdp.backend.presentation.hog_invocations.rerun import (
    HOG_INVOCATION_RERUN_MAX_COUNT,
    RERUN_MAX_WINDOW_DAYS,
)

logger = structlog.get_logger(__name__)

# Templates whose runs write the current state of a person (or of the person's
# company) to the destination, so one successful run makes every earlier failed
# run for that person redundant.
DEFAULT_LATEST_PER_PERSON_TEMPLATE_IDS = ("template-hubspot", "template-hubspot-company")

SkipReason = Literal[
    "function_not_replayable",
    "already_rerun",
    "already_delivered",
    "superseded_by_later_success",
    "older_run_for_same_person",
    "no_success_since_window",
]

SKIP_REASON_LABELS: dict[SkipReason, str] = {
    "function_not_replayable": "Function is disabled, deleted, or of a type that cannot be re-run",
    "already_rerun": "Already re-run once",
    "already_delivered": "The same event was delivered by a later run",
    "superseded_by_later_success": "A later run for the same person succeeded",
    "older_run_for_same_person": "Not the latest failed run for this person",
    "no_success_since_window": "Function has not succeeded since the window ended",
}

# Candidate functions: any function with a failed lifecycle row in the window
# that matches the error filters. The row-level filter is a superset of the
# invocation-level check in _INVOCATIONS_QUERY, which is the one that decides.
_CANDIDATE_FUNCTIONS_QUERY = """
SELECT DISTINCT team_id, function_id
FROM hog_invocation_results
WHERE function_kind = 'hog_function'
    AND scheduled_at >= %(window_start)s
    AND scheduled_at < %(window_end)s
    AND status = 'failed'
    {team_clause}
    {error_kind_clause}
    {error_message_clause}
"""

# One row per invocation of the candidate functions since the window start.
# The scan has no upper bound on scheduled_at, because a later retry row
# (cyclotron rewrites scheduled_at on every attempt) or a later success must
# count when the latest status is resolved. Aliases differ from the column
# names, because the ClickHouse analyzer resolves a name in WHERE to a
# same-named SELECT alias.
_INVOCATIONS_QUERY = """
SELECT
    function_id,
    invocation_id,
    argMax(status, version) AS latest_status,
    argMax(error_kind, version) AS latest_error_kind,
    argMax(error_message, version) AS latest_error_message,
    argMax(person_id, version) AS latest_person_id,
    argMax(event_uuid, version) AS latest_event_uuid,
    argMax(scheduled_at, version) AS latest_scheduled_at,
    max(is_retry) AS was_rerun
FROM hog_invocation_results
WHERE function_kind = 'hog_function'
    AND team_id IN %(team_ids)s
    AND function_id IN %(function_ids)s
    AND scheduled_at >= %(window_start)s
GROUP BY function_id, invocation_id
HAVING argMax(is_deleted, version) = 0
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


@frozen
class FunctionReplay:
    team_id: int
    team_name: str
    organization_name: str
    function_id: str
    function_name: str
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
            counts[f.template_id] += len(f.invocation_ids)
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
        """Identifies the exact set of invocations, so a run can refuse a plan that changed after the preview."""
        digest = hashlib.sha256()
        for f in sorted(self.replayable_functions, key=lambda f: f.function_id):
            for invocation_id in sorted(f.invocation_ids):
                digest.update(f"{f.function_id}:{invocation_id}\n".encode())
        return digest.hexdigest()[:16]


@frozen
class FunctionReplayResult:
    team_id: int
    function_id: str
    invocation_count: int
    status_code: int
    detail: str


@frozen
class _Invocation:
    function_id: str
    invocation_id: str
    status: str
    error_kind: str
    error_message: str
    person_id: str
    event_uuid: str
    scheduled_at: datetime
    was_rerun: bool


def _as_utc(value: datetime) -> datetime:
    # The ClickHouse driver returns naive datetimes for DateTime64 columns.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _find_candidate_functions(criteria: ReplayCriteria) -> list[tuple[int, str]]:
    params: dict[str, Any] = {"window_start": criteria.window_start, "window_end": criteria.window_end}
    team_clause = error_kind_clause = error_message_clause = ""
    if criteria.team_ids:
        team_clause = "AND team_id IN %(team_ids)s"
        params["team_ids"] = list(criteria.team_ids)
    if criteria.error_kinds:
        error_kind_clause = "AND error_kind IN %(error_kinds)s"
        params["error_kinds"] = list(criteria.error_kinds)
    if criteria.error_message_contains:
        error_message_clause = "AND positionCaseInsensitive(error_message, %(error_message_contains)s) > 0"
        params["error_message_contains"] = criteria.error_message_contains
    rows = sync_execute(
        _CANDIDATE_FUNCTIONS_QUERY.format(
            team_clause=team_clause,
            error_kind_clause=error_kind_clause,
            error_message_clause=error_message_clause,
        ),
        params,
    )
    return [(int(row[0]), str(row[1])) for row in rows]


def _load_invocations(criteria: ReplayCriteria, functions: list[HogFunction]) -> list[_Invocation]:
    rows = sync_execute(
        _INVOCATIONS_QUERY,
        {
            "team_ids": sorted({f.team_id for f in functions}),
            "function_ids": [str(f.id) for f in functions],
            "window_start": criteria.window_start,
        },
    )
    return [
        _Invocation(
            function_id=row[0],
            invocation_id=row[1],
            status=row[2],
            error_kind=row[3],
            error_message=row[4],
            person_id=row[5],
            event_uuid=row[6],
            scheduled_at=_as_utc(row[7]),
            was_rerun=bool(row[8]),
        )
        for row in rows
    ]


def _is_target_failure(invocation: _Invocation, criteria: ReplayCriteria) -> bool:
    if invocation.status != "failed":
        return False
    # The rerun worker selects rows inside the window, so an invocation whose
    # latest row is outside it would not be found when the plan runs.
    if not (criteria.window_start <= invocation.scheduled_at < criteria.window_end):
        return False
    if criteria.error_kinds and invocation.error_kind not in criteria.error_kinds:
        return False
    if criteria.error_message_contains and criteria.error_message_contains.lower() not in (
        invocation.error_message.lower()
    ):
        return False
    return True


def _plan_function(
    function: HogFunction, invocations: list[_Invocation], criteria: ReplayCriteria
) -> FunctionReplay | None:
    failures = [i for i in invocations if _is_target_failure(i, criteria)]
    if not failures:
        return None

    successes = [i for i in invocations if i.status == "succeeded"]
    delivered_events = {i.event_uuid for i in successes if i.event_uuid}
    last_success_by_person: dict[str, datetime] = {}
    for success in successes:
        if success.person_id:
            previous = last_success_by_person.get(success.person_id)
            last_success_by_person[success.person_id] = max(previous or success.scheduled_at, success.scheduled_at)

    skipped: Counter[SkipReason] = Counter()

    def skip_all(reason: SkipReason) -> FunctionReplay:
        skipped[reason] += len(failures)
        return _function_replay(function, (), skipped)

    if not function.enabled or function.deleted or function.type not in TYPES_THAT_CAN_RERUN:
        return skip_all("function_not_replayable")
    if criteria.require_success_since_window and not any(s.scheduled_at >= criteria.window_end for s in successes):
        return skip_all("no_success_since_window")

    latest_per_person = (function.template_id or "") in criteria.latest_per_person_template_ids
    latest_failure_by_person: dict[str, str] = {}
    if latest_per_person:
        for failure in sorted(failures, key=lambda i: i.scheduled_at):
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

    return _function_replay(function, tuple(sorted(replay)), skipped)


def _function_replay(
    function: HogFunction, invocation_ids: tuple[str, ...], skipped: Counter[SkipReason]
) -> FunctionReplay:
    return FunctionReplay(
        team_id=function.team_id,
        team_name=function.team.name,
        organization_name=function.team.organization.name,
        function_id=str(function.id),
        function_name=function.name or "",
        template_id=function.template_id or "",
        invocation_ids=invocation_ids,
        skipped=dict(skipped),
    )


def plan_replay(criteria: ReplayCriteria) -> ReplayPlan:
    with tags_context(product=Product.PIPELINE_DESTINATIONS, feature=Feature.DEBUG_QUERY):
        return _plan_replay(criteria)


def _plan_replay(criteria: ReplayCriteria) -> ReplayPlan:
    candidates = _find_candidate_functions(criteria)
    if not candidates:
        return ReplayPlan(criteria=criteria, functions=())

    queryset = HogFunction.objects.select_related("team", "team__organization").filter(
        id__in=[function_id for _, function_id in candidates],
        team_id__in={team_id for team_id, _ in candidates},
    )
    if criteria.template_ids:
        queryset = queryset.filter(template_id__in=criteria.template_ids)
    if criteria.exclude_template_ids:
        queryset = queryset.exclude(template_id__in=criteria.exclude_template_ids)
    functions = list(queryset)
    if not functions:
        return ReplayPlan(criteria=criteria, functions=())

    invocations_by_function: dict[str, list[_Invocation]] = {}
    for invocation in _load_invocations(criteria, functions):
        invocations_by_function.setdefault(invocation.function_id, []).append(invocation)

    planned = [
        _plan_function(function, invocations_by_function.get(str(function.id), []), criteria) for function in functions
    ]
    replays = [p for p in planned if p is not None]
    replays.sort(key=lambda f: (-len(f.invocation_ids), f.team_id, f.function_id))
    return ReplayPlan(criteria=criteria, functions=tuple(replays))


def execute_replay(plan: ReplayPlan, *, actor: str) -> list[FunctionReplayResult]:
    logger.info(
        "invocation_replay_started",
        actor=actor,
        fingerprint=plan.fingerprint,
        function_count=len(plan.replayable_functions),
        invocation_count=plan.invocation_count,
    )
    criteria = plan.criteria
    results: list[FunctionReplayResult] = []
    for function in plan.replayable_functions:
        for offset in range(0, len(function.invocation_ids), HOG_INVOCATION_RERUN_MAX_COUNT):
            chunk = list(function.invocation_ids[offset : offset + HOG_INVOCATION_RERUN_MAX_COUNT])
            try:
                response = rerun_hog_invocations(
                    team_id=function.team_id,
                    function_kind="hog_function",
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
            except Exception as error:
                # One unreachable request must not stop the rest of the plan. The
                # result row records it, so the operator can run the plan again,
                # which skips what already went through.
                status_code, detail = 0, repr(error)[:500]
            results.append(
                FunctionReplayResult(
                    team_id=function.team_id,
                    function_id=function.function_id,
                    invocation_count=len(chunk),
                    status_code=status_code,
                    detail=detail,
                )
            )
    logger.info(
        "invocation_replay_finished",
        actor=actor,
        fingerprint=plan.fingerprint,
        failed_requests=sum(1 for r in results if r.status_code != 200),
    )
    return results
