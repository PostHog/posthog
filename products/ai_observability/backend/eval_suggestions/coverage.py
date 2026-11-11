"""Stage 1: what the team's evaluations already cover, and which of them cover nothing.

An enabled evaluation that matched no events in 30 days counts as no coverage and becomes a "fix this
evaluation" card. One that returns the same outcome almost every time is only suspicious, so it becomes a
card only when its reasoning also shows it is broken.
"""

import copy
import difflib
import hashlib
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, Literal

from django.utils import timezone

from posthog.hogql import ast

from posthog.dataclasses import frozen
from posthog.models.team import Team

from products.ai_observability.backend.evaluation_conditions import build_condition_filter, runs_on_traffic
from products.ai_observability.backend.models.eval_suggestions import EvalSuggestion, EvalSuggestionStatus
from products.ai_observability.backend.models.evaluation_outcomes import APPLICABLE_PREDICATE, NOT_SKIPPED_PREDICATE
from products.ai_observability.backend.models.evaluations import Evaluation

from . import catalog
from .queries import run_query

DEAD_LOOKBACK = timedelta(days=30)
MAX_SILENT_EVALUATIONS = 10
# A young evaluation, or one edited in the last days, has not had the chance to match anything yet.
MIN_EVALUATION_AGE = timedelta(days=7)
MIN_QUIET_AFTER_EDIT = timedelta(days=2)
SUSPICIOUS_SHARE = 0.95
SUSPICIOUS_MIN_RUNS = 200
# Share of runs whose reasoning text also appears on the opposite outcome before a one-outcome
# evaluation reads as broken rather than as a healthy check on healthy traffic.
SHARED_REASONING_SHARE = 0.1
DISMISSAL_MEMORY = timedelta(days=90)
MIN_REPLACEMENT_SIMILARITY = 0.6
# A live value that contains the stale one, or sits inside it, qualifies however different its length, and edges out
# an equally similar value. It never beats a closer one.
CONTAINMENT_BOOST = 0.05
# Similarity between a few characters means nothing: `3` and `13` share a digit, not a meaning.
MIN_REPLACEMENT_LENGTH = 3

FixProblem = Literal["no_runs", "one_outcome"]


@frozen
class ExistingEval:
    id: str
    name: str
    evaluation_type: str
    enabled: bool
    target: str
    conditions: list[dict[str, Any]]
    # The catalog template this evaluation provably implements, when one does.
    template_key: str | None
    # The dedupe key of the accepted suggestion that created this evaluation, when one did.
    dedupe_key: str | None
    source_hash: str | None
    prompt: str | None
    created_at: datetime
    updated_at: datetime

    @property
    def definition_text(self) -> str:
        body = self.prompt or ""
        return f"{self.name}. {body}"


@frozen
class FilterChange:
    key: str
    old_value: str
    new_value: str


@frozen
class EvalFix:
    evaluation_id: str
    evaluation_name: str
    evaluation_type: str
    problem: FixProblem
    # PATCH body for the evaluation, when the fix is a filter value that matches traffic again.
    patch: dict[str, Any] | None
    weekly_units: int
    # Days of traffic the filters were matched against.
    window_days: int
    # The filter value the patch replaces, when there is a patch.
    filter_change: FilterChange | None = None
    # False for an enabled evaluation saved without condition sets, which the scheduler never runs.
    has_conditions: bool = True
    # For a one-outcome evaluation: the answer it keeps giving, on what share of how many graded runs.
    dominant_outcome: str = ""
    dominant_share: float = 0.0
    graded_runs: int = 0


@frozen
class Coverage:
    evals: list[ExistingEval]
    fixes: list[EvalFix]
    dismissed_dedupe_keys: frozenset[str]


def source_hash(source: str) -> str:
    return hashlib.sha256(source.strip().encode()).hexdigest()


def _catalog_key(evaluation: Evaluation) -> str | None:
    config = evaluation.evaluation_config or {}
    for template in catalog.templates().values():
        if template.evaluation_type != evaluation.evaluation_type:
            continue
        # A built-in type such as sentiment has no prompt or source, so its type alone identifies it.
        if template.prompt is None and template.source is None:
            return template.key
        if template.prompt is not None and template.prompt.strip() == str(config.get("prompt", "")).strip():
            return template.key
        if template.source is not None and template.source.strip() == str(config.get("source", "")).strip():
            return template.key
    return None


def existing_evals(team: Team) -> list[ExistingEval]:
    suggested = dict(
        EvalSuggestion.objects.for_team(team.pk)
        .filter(status=EvalSuggestionStatus.ACCEPTED, created_evaluation__isnull=False)
        .values_list("created_evaluation_id", "dedupe_key")
    )
    evals = []
    for evaluation in Evaluation.objects.filter(team_id=team.pk, deleted=False).order_by("created_at"):
        config = evaluation.evaluation_config or {}
        source = config.get("source") if evaluation.evaluation_type == "hog" else None
        evals.append(
            ExistingEval(
                id=str(evaluation.id),
                name=evaluation.name,
                evaluation_type=evaluation.evaluation_type,
                enabled=evaluation.enabled,
                target=evaluation.target,
                conditions=list(evaluation.conditions or []),
                template_key=_catalog_key(evaluation),
                dedupe_key=suggested.get(evaluation.id),
                source_hash=source_hash(source) if isinstance(source, str) and source else None,
                prompt=config.get("prompt") if evaluation.evaluation_type == "llm_judge" else None,
                created_at=evaluation.created_at,
                updated_at=evaluation.updated_at,
            )
        )
    return evals


def implementations(
    evals: Sequence[ExistingEval], *, dedupe_key: str, template_key: str, source: str | None, prompt: str | None
) -> list[ExistingEval]:
    """Evaluations that run a candidate's check: created from the same suggestion, or with the same catalog
    template, Hog source or judge prompt.

    The suggestion's dedupe key, not its template key, is the identity, because several candidates can share
    a template: every structured-output gap becomes its own judge.
    """
    candidate_hash = source_hash(source) if source else None
    return [
        existing
        for existing in evals
        if existing.dedupe_key == dedupe_key
        or (existing.template_key is not None and existing.template_key == template_key)
        or (candidate_hash is not None and existing.source_hash == candidate_hash)
        or (prompt is not None and existing.prompt is not None and existing.prompt.strip() == prompt.strip())
    ]


@frozen
class PropertyShape:
    key: Any
    type: str
    operator: str


def _shape(prop: Mapping[str, Any]) -> PropertyShape:
    return PropertyShape(
        key=prop.get("key"), type=prop.get("type") or "event", operator=prop.get("operator") or "exact"
    )


def _values(prop: Mapping[str, Any]) -> frozenset[str]:
    value = prop.get("value")
    return frozenset(str(item) for item in (value if isinstance(value, list) else [value]))


def _same_or_wider(existing: Mapping[str, Any], candidate: Mapping[str, Any]) -> bool:
    """Whether an existing property filter lets through every event the candidate's filter lets through."""
    if _shape(existing) != _shape(candidate):
        return False
    if _shape(existing).operator == "exact":
        return _values(candidate) <= _values(existing)
    return _values(candidate) == _values(existing)


def covers(existing: ExistingEval, target: str, filters: Sequence[Mapping[str, Any]]) -> bool:
    """Whether an evaluation already runs wherever a candidate with `filters` on `target` would run.

    It must be enabled, grade the same unit, and have a condition set whose every filter is one of the
    candidate's or wider. Sampling counts as coverage: a rollout below 100% is the team's choice of cost.
    An evaluation with no condition sets matches nothing, as the scheduler reads it.
    """
    if not existing.enabled or existing.target != target:
        return False
    # A condition set at 0% rollout matches but never runs, so it covers nothing.
    return any(
        runs_on_traffic(condition)
        and all(
            any(_same_or_wider(prop, candidate) for candidate in filters) for prop in condition.get("properties") or []
        )
        for condition in existing.conditions
    )


_EVAL_RUNS_SQL = (
    """
SELECT
    toString(properties.$ai_evaluation_id) AS evaluation_id,
    count() AS runs,
    countIf(toString(properties.$ai_evaluation_result) = 'true') AS true_runs,
    countIf(toString(properties.$ai_evaluation_result) = 'false') AS false_runs
FROM events
WHERE event = '$ai_evaluation'
  AND timestamp >= {start}
  AND toString(properties.$ai_evaluation_id) IN {evaluation_ids}
  AND """
    + NOT_SKIPPED_PREDICATE
    + " AND "
    + APPLICABLE_PREDICATE
    + """
GROUP BY evaluation_id
LIMIT 10000
"""
)

# Runs whose reasoning text, word for word, also explains the opposite outcome somewhere else.
_SHARED_REASONING_SQL = """
SELECT evaluation_id, sum(true_runs + false_runs) AS shared_runs
FROM (
    SELECT
        toString(properties.$ai_evaluation_id) AS evaluation_id,
        cityHash64(toString(properties.$ai_evaluation_reasoning)) AS reasoning,
        countIf(toString(properties.$ai_evaluation_result) = 'true') AS true_runs,
        countIf(toString(properties.$ai_evaluation_result) = 'false') AS false_runs
    FROM events
    WHERE event = '$ai_evaluation'
      AND timestamp >= {start}
      AND toString(properties.$ai_evaluation_id) IN {evaluation_ids}
      AND length(toString(properties.$ai_evaluation_reasoning)) > 20
    GROUP BY evaluation_id, reasoning
)
WHERE true_runs > 0 AND false_runs > 0
GROUP BY evaluation_id
LIMIT 10000
"""

_MATCHING_GENERATIONS_SQL = """
SELECT count()
FROM events
WHERE event = '$ai_generation' AND timestamp >= {start} AND timestamp < {end} AND {condition}
"""

_PROPERTY_VALUES_SQL = """
SELECT toString({property}) AS value, count() AS generations
FROM events
WHERE event = '$ai_generation' AND timestamp >= {start} AND timestamp < {end} AND notEmpty(toString({property}))
GROUP BY value
ORDER BY generations DESC
LIMIT 50
"""


def best_replacement(old: str, values: Mapping[str, int]) -> str | None:
    """The live value a stale filter value most likely became, such as `signals` -> `signals_scout`.

    The most similar value wins and traffic only breaks ties, so `checkout_v2` becomes `checkout_v3`, not the
    busier `checkout`, which would point the evaluation at a wider segment.
    """
    lowered = old.lower()
    if len(lowered) < MIN_REPLACEMENT_LENGTH:
        return None

    scored = []
    for value in values:
        other = value.lower()
        if other == lowered or len(other) < MIN_REPLACEMENT_LENGTH:
            continue
        ratio = difflib.SequenceMatcher(None, lowered, other).ratio()
        contains = lowered in other or other in lowered
        if contains or ratio >= MIN_REPLACEMENT_SIMILARITY:
            scored.append((ratio + (CONTAINMENT_BOOST if contains else 0.0), values[value], value))
    return max(scored)[2] if scored else None


def _exact_values(prop: Mapping[str, Any]) -> list[str]:
    if prop.get("type", "event") != "event" or prop.get("operator", "exact") not in ("exact", None):
        return []
    value = prop.get("value")
    values = value if isinstance(value, list) else [value]
    return [str(item) for item in values if isinstance(item, str | int) and str(item)]


def _clean_conditions(conditions: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """A copy without compiled bytecode, which the evaluation recompiles when the patch is saved."""
    return [
        {key: copy.deepcopy(value) for key, value in condition.items() if key not in ("bytecode", "bytecode_error")}
        for condition in conditions
    ]


def _count_matching(team: Team, conditions: list[dict[str, Any]], start: datetime, end: datetime) -> int:
    # A set paused at 0% matches events but grades none, so it never counts as matching traffic.
    condition = build_condition_filter([c for c in conditions if runs_on_traffic(c)], team)
    # The scheduler runs an evaluation with no condition sets on nothing.
    if condition is None:
        return 0
    rows = run_query(
        team,
        _MATCHING_GENERATIONS_SQL,
        {"start": ast.Constant(value=start), "end": ast.Constant(value=end), "condition": condition},
        "EvalSuggestionsConditionMatches",
    )
    return int(rows[0][0]) if rows else 0


@frozen
class FilterFix:
    patch: dict[str, Any]
    weekly_units: int
    change: FilterChange


def _filter_fix(
    team: Team,
    existing: ExistingEval,
    start: datetime,
    end: datetime,
    values_by_key: dict[str, dict[str, int]],
) -> FilterFix | None:
    """A patch that points a filter value nothing sends any more at the value traffic now carries.

    Only called for conditions that match nothing, and kept only when the patched conditions match traffic,
    so a value missing from the top values because it is rare never counts as gone.
    """
    conditions = _clean_conditions(existing.conditions)
    for condition in conditions:
        # A condition set at 0% rollout runs on nothing whatever its filter matches.
        if not runs_on_traffic(condition):
            continue
        for prop in condition.get("properties") or []:
            key = str(prop["key"])
            for old in _exact_values(prop):
                if key not in values_by_key:
                    rows = run_query(
                        team,
                        _PROPERTY_VALUES_SQL,
                        {
                            "property": ast.Field(chain=["properties", key]),
                            "start": ast.Constant(value=start),
                            "end": ast.Constant(value=end),
                        },
                        "EvalSuggestionsPropertyValues",
                    )
                    values_by_key[key] = {str(value): int(count) for value, count in rows}
                values = values_by_key[key]
                if old in values:
                    continue
                new = best_replacement(old, values)
                if new is None:
                    continue
                value = prop["value"]
                prop["value"] = (
                    [new if str(item) == old else item for item in value] if isinstance(value, list) else new
                )
                matching = _count_matching(team, conditions, start, end)
                if matching == 0:
                    # Another condition set may still hold the stale value, so undo this guess and keep looking.
                    prop["value"] = value
                    continue
                return FilterFix(
                    patch={"conditions": conditions},
                    weekly_units=matching,
                    change=FilterChange(key=key, old_value=old, new_value=new),
                )
    return None


def fix_dedupe_key(evaluation_id: str, problem: FixProblem) -> str:
    return f"fix:{evaluation_id}:{problem}"


def find_fixes(
    team: Team,
    evals: Sequence[ExistingEval],
    window_start: datetime,
    window_end: datetime,
    dismissed: frozenset[str] = frozenset(),
) -> list[EvalFix]:
    enabled = {existing.id: existing for existing in evals if existing.enabled}
    if not enabled:
        return []
    now = timezone.now()
    placeholders: dict[str, ast.Expr] = {
        "start": ast.Constant(value=now - DEAD_LOOKBACK),
        "evaluation_ids": ast.Constant(value=sorted(enabled)),
    }
    runs = {
        str(row[0]): (int(row[1]), int(row[2]), int(row[3]))
        for row in run_query(team, _EVAL_RUNS_SQL, placeholders, "EvalSuggestionsEvaluationRuns")
    }
    fixes: list[EvalFix] = []
    values_by_key: dict[str, dict[str, int]] = {}
    # Each candidate costs a count and possibly repair probes, so a team with many silent evaluations pays for
    # the most recently edited few. Dismissed ones and ones paused at 0% rollout leave room for the rest.
    silent = sorted(
        (
            (evaluation_id, existing)
            for evaluation_id, existing in enabled.items()
            if evaluation_id not in runs
            and fix_dedupe_key(evaluation_id, "no_runs") not in dismissed
            and (not existing.conditions or any(runs_on_traffic(condition) for condition in existing.conditions))
            and now - existing.created_at >= MIN_EVALUATION_AGE
            and now - existing.updated_at >= MIN_QUIET_AFTER_EDIT
        ),
        key=lambda item: item[1].updated_at,
        reverse=True,
    )[:MAX_SILENT_EVALUATIONS]
    window_days = max(round((window_end - window_start) / timedelta(days=1)), 1)
    for evaluation_id, existing in silent:
        if not existing.conditions:
            fixes.append(
                EvalFix(
                    evaluation_id=evaluation_id,
                    evaluation_name=existing.name,
                    evaluation_type=existing.evaluation_type,
                    problem="no_runs",
                    patch=None,
                    weekly_units=0,
                    window_days=window_days,
                    has_conditions=False,
                )
            )
            continue
        # Conditions that match traffic mean the evaluation stopped for another reason, such as its key.
        if _count_matching(team, _clean_conditions(existing.conditions), window_start, window_end) > 0:
            continue
        fix = _filter_fix(team, existing, window_start, window_end, values_by_key)
        fixes.append(
            EvalFix(
                evaluation_id=evaluation_id,
                evaluation_name=existing.name,
                evaluation_type=existing.evaluation_type,
                problem="no_runs",
                patch=fix.patch if fix else None,
                weekly_units=fix.weekly_units if fix else 0,
                window_days=window_days,
                filter_change=fix.change if fix else None,
            )
        )

    # Runs before an edit judged an older version, so an evaluation edited within the window waits for clean runs.
    suspicious = {
        evaluation_id: counts
        for evaluation_id, counts in runs.items()
        if counts[0] >= SUSPICIOUS_MIN_RUNS
        and max(counts[1], counts[2]) / counts[0] > SUSPICIOUS_SHARE
        and now - enabled[evaluation_id].updated_at >= DEAD_LOOKBACK
    }
    if suspicious:
        shared = {
            str(row[0]): int(row[1])
            for row in run_query(
                team,
                _SHARED_REASONING_SQL,
                {"start": placeholders["start"], "evaluation_ids": ast.Constant(value=sorted(suspicious))},
                "EvalSuggestionsSharedReasoning",
            )
        }
        for evaluation_id, (total, true_runs, false_runs) in suspicious.items():
            if shared.get(evaluation_id, 0) / total < SHARED_REASONING_SHARE:
                continue
            fixes.append(
                EvalFix(
                    evaluation_id=evaluation_id,
                    evaluation_name=enabled[evaluation_id].name,
                    evaluation_type=enabled[evaluation_id].evaluation_type,
                    problem="one_outcome",
                    patch=None,
                    weekly_units=round(total * 7 / DEAD_LOOKBACK.days),
                    window_days=window_days,
                    dominant_outcome="true" if true_runs >= false_runs else "false",
                    dominant_share=max(true_runs, false_runs) / total,
                    graded_runs=total,
                )
            )
    return fixes


def dismissed_dedupe_keys(team: Team) -> frozenset[str]:
    return frozenset(
        EvalSuggestion.objects.for_team(team.pk)
        .filter(status=EvalSuggestionStatus.DISMISSED, decided_at__gte=timezone.now() - DISMISSAL_MEMORY)
        .values_list("dedupe_key", flat=True)
    )


def fetch_coverage(team: Team, window_start: datetime, window_end: datetime) -> Coverage:
    evals = existing_evals(team)
    dismissed = dismissed_dedupe_keys(team)
    return Coverage(
        evals=evals,
        fixes=find_fixes(team, evals, window_start, window_end, dismissed),
        dismissed_dedupe_keys=dismissed,
    )
