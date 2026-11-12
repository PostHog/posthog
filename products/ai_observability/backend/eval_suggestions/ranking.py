"""Stage 6: validate every candidate in its exact configuration, score it, and pick at most three.

A check that fails more than MAX_FAILURE_RATE of traces does not fit the app and is dropped. Among the
rest, a rare severe failure can win and a common harmless one can lose, because the score weighs credible
weekly failures by severity, uncovered scope and running cost.
"""

import math
import hashlib
from collections import Counter
from collections.abc import Sequence
from typing import Any

from posthog.dataclasses import frozen
from posthog.temporal.ai_observability.run_session_evaluation import JUDGE_SESSION_MAX_CHARS
from posthog.temporal.ai_observability.run_trace_evaluation import JUDGE_TRACE_MAX_CHARS

from products.ai_observability.backend.llm import DEFAULT_MODEL_BY_PROVIDER
from products.ai_observability.backend.models.eval_suggestions import EvalSuggestionKind
from products.ai_observability.backend.models.evaluations import Evaluation

from . import cards, catalog
from .adapters import AdaptedCheck
from .coverage import EvalFix, fix_dedupe_key
from .measure import Measurement, Outcome, SampledTrace, TraceSample
from .profile import StructuredGap, TeamProfile, normalize_segment_value
from .stats import wilson_interval

# Roughly how many characters one input token covers, to turn the judge's transcript caps into tokens.
CHARS_PER_TOKEN = 4

MAX_SUGGESTIONS = 3
MAX_PER_KIND = 2
# A check that fails more than this share of traces does not fit the app, whatever it found.
MAX_FAILURE_RATE = 0.25
MIN_FAILURES = 2
# Filter rule: the segment holds a real share of the failures, enough of them to trust, and beats the rest.
MIN_FILTER_FAILURE_SHARE = 0.3
MIN_FILTER_FAILURES = 20
EVIDENCE_LIMIT = 5
# Judges run on a rollout that keeps them near this many runs a week, so a large team does not pay
# for every trace while it decides whether the check is useful.
WEEKLY_JUDGE_RUNS = 1000
JUDGE_COST_FACTOR = 0.8
SIMILAR_FACTOR = 0.5
# Decision-model screening flags many traces that a person would not; only part of them count.
SCREENING_PRECISION = 0.25
MIN_SCREENED_FLAGS = 3

# Hog checks carry their own severity; these weigh the judges.
SEVERITY: dict[str, float] = {
    "prompt_injection": 0.9,
    "user_correction": 0.7,
    "sentiment": 0.4,
    "structured_output_gap": 0.8,
}
FIX_SEVERITY = 1.0


@frozen
class ModelPrice:
    input_per_token: float
    output_per_token: float


# ponytail: list prices of each provider's default model, read for estimates only. Model prices live in the
# Node ingestion package, which the Python image does not ship; move this to a shared file when a caller
# outside eval suggestions needs prices. A test keeps every provider default priced here.
MODEL_PRICES: dict[str, ModelPrice] = {
    "gpt-5-mini": ModelPrice(input_per_token=0.25e-6, output_per_token=2e-6),
    "claude-haiku-4-5": ModelPrice(input_per_token=1e-6, output_per_token=5e-6),
    "gemini-2.5-flash": ModelPrice(input_per_token=0.3e-6, output_per_token=2.5e-6),
}
# What a judge runs on when the team has no provider key yet: the evaluator's OpenAI default.
DEFAULT_JUDGE_MODEL = DEFAULT_MODEL_BY_PROVIDER["openai"]


@frozen
class Evidence:
    trace_id: str
    reason: str


@frozen
class Proposal:
    kind: str
    template_key: str
    dedupe_key: str
    headline: str
    outcome: str
    reason: str
    draft: dict[str, Any]
    filters: list[dict[str, Any]]
    rollout_percentage: float
    measured_failure_rate: float | None
    sample_size: int | None
    evidence: list[Evidence]
    score: float
    estimated_weekly_runs: int | None = None
    estimated_weekly_cost_usd: float | None = None
    mean_input_tokens: int | None = None
    # The model the weekly cost assumes, for LLM judges.
    judge_model: str = ""
    target_evaluation_id: str | None = None
    similar_evaluation_id: str | None = None


@frozen
class JudgeCost:
    rollout_percentage: float
    weekly_runs: int
    weekly_cost_usd: float | None


def judge_input_price(model: str) -> float | None:
    price = MODEL_PRICES.get(model)
    return price.input_per_token if price else None


def judge_cost(weekly_units: float, mean_input_tokens: float | None, model: str) -> JudgeCost:
    # The scheduler samples in 0.01% steps, so the largest teams still land near WEEKLY_JUDGE_RUNS.
    rollout = (
        100.0 if weekly_units <= WEEKLY_JUDGE_RUNS else max(0.01, round(100 * WEEKLY_JUDGE_RUNS / weekly_units, 2))
    )
    weekly_runs = round(weekly_units * rollout / 100)
    price = judge_input_price(model)
    cost = weekly_runs * mean_input_tokens * price if mean_input_tokens and price else None
    return JudgeCost(rollout_percentage=rollout, weekly_runs=weekly_runs, weekly_cost_usd=cost)


def mean_unit_tokens(target: str, profile: TeamProfile, sample: TraceSample) -> float | None:
    """Input tokens one judge run reads: a generation's own, or a trace's or conversation's transcript.

    Summed input tokens count history once per step, and the judge reads a transcript cut to a fixed length, so
    a trace or session reads at most that transcript.
    """
    if target == "generation":
        return profile.mean_input_tokens
    totals = [s.input_tokens for s in sample.traces if s.input_tokens > 0]
    if not totals:
        return None
    per_trace = min(sum(totals) / len(totals), JUDGE_TRACE_MAX_CHARS / CHARS_PER_TOKEN)
    if target == "session":
        # Traces without a session never reach a session judge, so they must not change its price.
        traces_per_session = profile.session_traces / profile.sessions if profile.sessions else 1.0
        return min(per_trace * traces_per_session, JUDGE_SESSION_MAX_CHARS / CHARS_PER_TOKEN)
    return per_trace


def _score(severity: float, credible_weekly_failures: float, *, judge: bool, similar: bool) -> float:
    return (
        severity
        * math.log10(1 + max(credible_weekly_failures, 0))
        * (JUDGE_COST_FACTOR if judge else 1.0)
        * (SIMILAR_FACTOR if similar else 1.0)
    )


def check_dedupe_key(check_key: str) -> str:
    return f"check:{check_key}"


def judge_dedupe_key(template_key: str) -> str:
    return f"judge:{template_key}"


@frozen
class Counts:
    failed: int
    applicable: int


def _counts(outcomes: Sequence[Outcome]) -> Counts:
    applicable = [outcome for outcome in outcomes if outcome.failed is not None]
    return Counts(failed=sum(1 for outcome in applicable if outcome.failed), applicable=len(applicable))


def _validated(main: Sequence[Outcome], held_out: Sequence[Outcome]) -> Counts | None:
    """Counts on the main sample when the outcomes pass every check, else None."""
    counts = _counts(main)
    held = _counts(held_out)
    if counts.applicable == 0 or counts.failed == 0 or counts.failed / counts.applicable > MAX_FAILURE_RATE:
        return None
    if counts.failed + held.failed < MIN_FAILURES or not held_out_agrees(counts, held):
        return None
    return counts


def held_out_agrees(main: Counts, held_out: Counts) -> bool:
    """The held-out day must not contradict the measurement: its interval stays above the fit limit only when
    it surely fails too often, and it reaches the main interval. Interval bounds keep a day with a handful of
    traces from deciding alone. A day with no failures passes for a rare failure, not a common one."""
    if held_out.applicable == 0:
        return True
    if wilson_interval(held_out.failed, held_out.applicable).low > MAX_FAILURE_RATE:
        return False
    return (
        wilson_interval(held_out.failed, held_out.applicable).high >= wilson_interval(main.failed, main.applicable).low
    )


def filter_for(
    failing_ids: set[str],
    outcomes_by_trace: dict[str, bool],
    traces: Sequence[SampledTrace],
    held_out: Sequence[tuple[SampledTrace, bool]],
) -> list[dict[str, Any]]:
    """Property filters that scope a check to the segment holding its failures, or [] for all traffic.

    The segment must hold MIN_FILTER_FAILURE_SHARE of the failures and MIN_FILTER_FAILURES of them, its
    failure interval must sit above the rest's, and it must still fail more than the rest on the held-out day.
    """
    total_failures = len(failing_ids)
    best: tuple[float, str, str] | None = None
    # The scheduler runs a trace evaluation when any generation matches, so a trace belongs to every value it sent.
    keys = {key for sampled in traces for key in sampled.segment_values}
    for key in sorted(keys):
        values = {value for sampled in traces for value in sampled.segment_values.get(key, ())}
        for value in sorted(values):
            inside = [s for s in traces if _sent(s, key, value) and s.trace.id in outcomes_by_trace]
            outside = [s for s in traces if not _sent(s, key, value) and s.trace.id in outcomes_by_trace]
            failed_in = sum(1 for s in inside if s.trace.id in failing_ids)
            failed_out = sum(1 for s in outside if s.trace.id in failing_ids)
            if failed_in < max(MIN_FILTER_FAILURES, MIN_FILTER_FAILURE_SHARE * total_failures) or not outside:
                continue
            low_in = wilson_interval(failed_in, len(inside)).low
            if low_in <= wilson_interval(failed_out, len(outside)).high:
                continue
            held_in = [failed for s, failed in held_out if _sent(s, key, value)]
            held_rest = [failed for s, failed in held_out if not _sent(s, key, value)]
            if not held_in or not held_rest or sum(held_in) / len(held_in) <= sum(held_rest) / len(held_rest):
                continue
            if best is None or low_in > best[0]:
                best = (low_in, key, value)
    if best is None:
        return []
    _, key, value = best
    return [segment_filter(key, value, traces)]


def segment_filter(key: str, value: str, traces: Sequence[SampledTrace]) -> dict[str, Any]:
    """An exact filter on every value, as sent, that normalizes to `value`."""
    raw_values = sorted(
        {raw for s in traces for raw in s.raw_segment_values.get(key, ()) if normalize_segment_value(raw) == value}
    )
    return {"key": key, "value": raw_values or [value], "operator": "exact", "type": "event"}


def _sent(sampled: SampledTrace, key: str, value: str) -> bool:
    return value in sampled.segment_values.get(key, ())


def _in_scope(filters: list[dict[str, Any]], sampled: SampledTrace) -> bool:
    """Whether the live evaluation would run on this trace: some generation matches every filter."""
    return all(bool(sampled.raw_segment_values.get(prop["key"], frozenset()) & set(prop["value"])) for prop in filters)


def _scope_share(filters: list[dict[str, Any]], traces: Sequence[SampledTrace]) -> float:
    if not filters or not traces:
        return 1.0
    return sum(1 for s in traces if _in_scope(filters, s)) / len(traces)


def code_check_proposal(
    measurement: Measurement, sample: TraceSample, profile: TeamProfile, *, similar_evaluation_id: str | None
) -> Proposal | None:
    check: AdaptedCheck = measurement.check
    main = measurement.main
    counts = _validated(main, measurement.held_out)
    if counts is None:
        return None

    outcomes_by_trace = {o.trace_id: bool(o.failed) for o in main if o.failed is not None}
    held_by_trace = {o.trace_id: bool(o.failed) for o in measurement.held_out if o.failed is not None}
    filters = filter_for(
        {o.trace_id for o in main if o.failed},
        outcomes_by_trace,
        sample.main,
        [(s, held_by_trace[s.trace.id]) for s in sample.held_out if s.trace.id in held_by_trace],
    )
    if filters:
        # The card's rate, sample and examples describe the traces the evaluation will run on, so a filtered
        # check is validated again on its segment. One that fails there runs on all traffic instead.
        in_scope = {s.trace.id for s in sample.traces if _in_scope(filters, s)}
        scoped_main = [o for o in main if o.trace_id in in_scope]
        scoped_counts = _validated(scoped_main, [o for o in measurement.held_out if o.trace_id in in_scope])
        if scoped_counts is None:
            filters = []
        else:
            main, counts = scoped_main, scoped_counts
    failed, applicable = counts.failed, counts.applicable
    failing = [outcome for outcome in main if outcome.failed]
    weekly_units = profile.traces * applicable / max(len(sample.main), 1)
    segment = normalize_segment_value(filters[0]["value"][0]) if filters else None
    text = cards.code_check_text(check, failed / applicable, segment)
    return Proposal(
        kind=EvalSuggestionKind.NEW_HOG,
        template_key=check.key,
        dedupe_key=check_dedupe_key(check.key),
        headline=text.headline,
        outcome=text.outcome,
        reason=text.reason,
        draft={
            "name": check.name,
            "description": check.description,
            "evaluation_type": "hog",
            "evaluation_config": {"source": check.source},
            "output_type": "boolean",
            "output_config": {"allows_na": True},
            "target": "trace",
        },
        filters=filters,
        rollout_percentage=100.0,
        measured_failure_rate=failed / applicable,
        sample_size=applicable,
        evidence=[Evidence(trace_id=o.trace_id, reason=o.reasoning[:160]) for o in failing[:EVIDENCE_LIMIT]],
        score=_score(
            check.severity,
            wilson_interval(failed, applicable).low * weekly_units,
            judge=False,
            similar=similar_evaluation_id is not None,
        ),
        estimated_weekly_runs=round(profile.traces * _scope_share(filters, sample.main)),
        similar_evaluation_id=similar_evaluation_id,
    )


# What a gap judge checks depends on what the field means: a severity can be overstated, a status or a label wrong.
GAP_PROMPTS: dict[str, str] = {
    "urgency": """The output lists {items}, and each has a `{field}` field. Decide whether every item marked {values} deserves that level.

- Return false if any item marked {values} describes a problem that is minor, speculative, or needs unusual conditions to happen
- Return false if any item marked {values} does not match how that level is defined in the instructions
- Return true if every item marked {values} is justified, or if no item has that level""",
    "status": """The output lists {items}, and each has a `{field}` field. Decide whether every item marked {values} really is in that state.

- Return false if the rest of the output or the conversation shows that an item marked {values} is in a different state
- Return false if any item marked {values} does not match how that state is defined in the instructions
- Return true if every item marked {values} is in that state, or if no item has it""",
    "label": """The output lists {items}, and each has a `{field}` field. Decide whether every item labelled {values} fits that label.

- Return false if any item labelled {values} fits another label better, given the rest of the output and the instructions
- Return true if every item labelled {values} fits it, or if no item has that label""",
}
# EvalSuggestion.dedupe_key holds 255 characters, and gap keys carry customer property names.
MAX_DEDUPE_KEY = 255


def bounded_key(key: str) -> str:
    """The key itself when it fits, else its start plus a hash of the whole, so it stays stable across runs."""
    if len(key) <= MAX_DEDUPE_KEY:
        return key
    return f"{key[:200]}#{hashlib.sha256(key.encode()).hexdigest()[:32]}"


def gap_proposal(
    gap: StructuredGap,
    sample: TraceSample,
    profile: TeamProfile,
    *,
    judge_model: str,
    similar_evaluation_id: str | None,
) -> Proposal:
    items, field = gap.items, gap.field_name
    values_text = " or ".join(gap.values)
    eval_text = cards.gap_eval_text(gap)
    # The urgency prompt asks whether a level is overstated, which only fits the top of a scale. A segment that
    # overuses "low" gets the label prompt instead.
    meaning = gap.meaning if gap.meaning != "urgency" or cards.is_urgent(gap) else "label"
    prompt = GAP_PROMPTS[meaning].format(items=items, field=field, values=values_text)
    filters = [segment_filter(gap.segment_key, gap.segment_value, sample.traces)]
    weekly_units = profile.traces * _scope_share(filters, sample.traces)
    unit_tokens = mean_unit_tokens("trace", profile, sample)
    cost = judge_cost(weekly_units, unit_tokens, judge_model)
    # Gaps are counted on the main sample only, like code checks, so both weigh the same week of traffic.
    excess_per_week = (
        (gap.segment_rate - gap.other_rate) * gap.segment_items * profile.traces / max(len(sample.main), 1)
    )
    text = cards.gap_text(gap, cards.cost_clause(cost.weekly_cost_usd, free=False))
    return Proposal(
        kind=EvalSuggestionKind.NEW_LLM_JUDGE,
        template_key="structured_output_gap",
        dedupe_key=bounded_key(f"gap:{gap.segment_key}={gap.segment_value}:{gap.field}"),
        headline=text.headline,
        outcome=text.outcome,
        reason=text.reason,
        draft={
            # A field path comes from the customer's output and has no length bound of its own.
            "name": eval_text.name[: Evaluation._meta.get_field("name").max_length],
            "description": eval_text.description,
            "evaluation_type": "llm_judge",
            "evaluation_config": {"prompt": prompt},
            "output_type": "boolean",
            "output_config": {},
            "target": "trace",
        },
        filters=filters,
        rollout_percentage=cost.rollout_percentage,
        measured_failure_rate=None,
        sample_size=None,
        evidence=[
            Evidence(
                trace_id=example.trace_id,
                reason=f"{example.matching} of {example.total} {items} marked {values_text}",
            )
            for example in gap.examples[:EVIDENCE_LIMIT]
        ],
        score=_score(
            SEVERITY["structured_output_gap"], excess_per_week, judge=True, similar=similar_evaluation_id is not None
        ),
        estimated_weekly_runs=cost.weekly_runs,
        estimated_weekly_cost_usd=cost.weekly_cost_usd,
        mean_input_tokens=round(unit_tokens) if unit_tokens else None,
        judge_model=judge_model,
        similar_evaluation_id=similar_evaluation_id,
    )


@frozen
class ScreeningResult:
    template_key: str
    screened: int
    # (trace id, one-line label), most likely first.
    flagged: list[tuple[str, str]]


def screened_proposal(
    result: ScreeningResult,
    profile: TeamProfile,
    sample: TraceSample,
    *,
    target: str,
    judge_model: str,
    similar_evaluation_id: str | None,
) -> Proposal | None:
    if len(result.flagged) < MIN_SCREENED_FLAGS or result.screened == 0:
        return None
    template = catalog.template(result.template_key)
    # Sentiment runs per generation, so it keeps the template's target whatever the traffic looks like.
    unit_target = template.target if template.evaluation_type == "sentiment" else target
    weekly_units = {"generation": profile.generations, "session": profile.sessions}.get(unit_target, profile.traces)
    unit_tokens = mean_unit_tokens(unit_target, profile, sample)
    cost = judge_cost(weekly_units, unit_tokens, judge_model)
    # Screening reads only traces with a final answer, so its rate holds for that share of traffic.
    readable = sum(1 for s in sample.main if s.final_text.strip()) / len(sample.main) if sample.main else 1.0
    credible = len(result.flagged) / result.screened * profile.traces * readable * SCREENING_PRECISION
    is_judge = template.evaluation_type == "llm_judge"
    text = cards.judge_text(template, unit_target, cards.cost_clause(cost.weekly_cost_usd, free=not is_judge))
    return Proposal(
        kind=EvalSuggestionKind.NEW_LLM_JUDGE,
        template_key=template.key,
        dedupe_key=judge_dedupe_key(template.key),
        headline=text.headline,
        outcome=text.outcome,
        reason=text.reason,
        draft={
            "name": template.name,
            "description": template.description,
            "evaluation_type": template.evaluation_type,
            "evaluation_config": template.evaluation_config(),
            "output_type": template.output_type,
            "output_config": template.output_config,
            "target": unit_target,
        },
        filters=[],
        rollout_percentage=cost.rollout_percentage,
        measured_failure_rate=None,
        sample_size=None,
        evidence=[Evidence(trace_id=trace_id, reason=label) for trace_id, label in result.flagged[:EVIDENCE_LIMIT]],
        score=_score(
            SEVERITY.get(template.key, 0.5),
            credible,
            judge=is_judge,
            similar=similar_evaluation_id is not None,
        ),
        estimated_weekly_runs=cost.weekly_runs,
        estimated_weekly_cost_usd=cost.weekly_cost_usd if is_judge else 0.0,
        mean_input_tokens=round(unit_tokens) if unit_tokens else None,
        judge_model=judge_model if is_judge else "",
        similar_evaluation_id=similar_evaluation_id,
    )


def fix_proposal(fix: EvalFix) -> Proposal:
    text = cards.fix_text(fix)
    return Proposal(
        kind=EvalSuggestionKind.FIX_EVAL,
        template_key="",
        dedupe_key=fix_dedupe_key(fix.evaluation_id, fix.problem),
        headline=text.headline,
        outcome=text.outcome,
        reason=text.reason,
        draft=fix.patch or {},
        filters=[],
        rollout_percentage=100.0,
        measured_failure_rate=None,
        sample_size=None,
        evidence=[],
        # An evaluation the team already chose that covers nothing is the cheapest coverage to win back.
        score=FIX_SEVERITY * math.log10(1 + max(fix.weekly_units, 10)),
        target_evaluation_id=fix.evaluation_id,
    )


def pick(proposals: Sequence[Proposal], limit: int = MAX_SUGGESTIONS) -> list[Proposal]:
    """The best proposals, at most MAX_PER_KIND of one kind so the cards stay diverse."""
    picked: list[Proposal] = []
    per_kind: Counter[str] = Counter()
    for proposal in sorted(proposals, key=lambda p: p.score, reverse=True):
        if len(picked) >= limit:
            break
        if proposal.score <= 0 or per_kind[proposal.kind] >= MAX_PER_KIND:
            continue
        picked.append(proposal)
        per_kind[proposal.kind] += 1
    return picked
