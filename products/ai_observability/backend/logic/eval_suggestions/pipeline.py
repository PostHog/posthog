"""One team's run, as four stages that each run in their own Temporal activity:

1. measure: coverage, profile, the trace sample, the free checks and the gap judges.
2. screen: the decision model screens traces for the judges and matches hand-written evaluations. Paid.
3. draft: a model reviews a sample of the team's calls and drafts at most two judges from what it finds, and each
   judge is kept only when the model it will run on reproduces the review's labels. Paid.
4. publish: dedupe, pick at most three, and publish them in one transaction.

Stages hand over through `EvalSuggestionRun.handoff`: trace ids and candidate cards, never trace content. A stage
that needs traces hydrates them again from their ids, so a retry redoes one stage and a timeout stops that stage.
"""

import time
from collections.abc import Sequence
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

import structlog
from anthropic import Anthropic

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import GatewayNotConfiguredError
from posthog.llm.system_one import SystemOneNotConfigured, SystemOneRequestFailed
from posthog.models.team import Team

from products.access_control.backend.facade.api import team_has_property_access_rules
from products.ai_observability.backend.llm import DEFAULT_MODEL_BY_PROVIDER
from products.ai_observability.backend.logic.eval_suggestions.profile_queries import ProfileWindow
from products.ai_observability.backend.models.eval_suggestions import (
    EvalSuggestionKind,
    EvalSuggestionRun,
    EvalSuggestionRunStatus,
)
from products.ai_observability.backend.models.evaluation_config import EvaluationConfig

from . import (
    call_review,
    catalog,
    coverage as coverage_stage,
    judge_calibration,
    ranking,
    runs,
    screening,
)
from .applicability import applicable, content_profile
from .call_review_queries import (
    CODE_CHECK_CALLS_PER_CALL_TYPE,
    CallTypeRow,
    ReviewCallRow,
    load_call_types,
    load_review_calls,
    snippet_matches,
)
from .config import REVIEW_WINDOW, WINDOW, SuggestionSettings, runs_for_organization
from .coverage import Coverage, dismissed_dedupe_keys, existing_evals
from .measure import discover_sample, hydrate_sample, measure, structured_outputs
from .profile import TeamProfile, fetch_profile, find_structured_gaps, gap_holds, sample_per_mille
from .queries import MAX_EXECUTION_TIME_SECONDS
from .ranking import Proposal
from .runs import Handoff

logger = structlog.get_logger(__name__)

# Traces younger than this may still be receiving events, so the window stops short of now.
SETTLE = timedelta(minutes=30)
MIN_CONTENT_SHARE = 0.25
# Dedupe asks the model about each hand-written evaluation, so a team with many pays for this many at most.
MAX_DEDUPED_EVALS = 50
PAID_STAGES = ("screening", "drafting")


def judge_model(team: Team) -> str | None:
    """The model a new judge would run on: the default for the team's active key, else the product default.

    None when the key's provider has no default model, since the evaluator refuses to run a judge without one.
    """
    config = EvaluationConfig.objects.filter(team_id=team.pk).select_related("active_provider_key").first()
    key = config.active_provider_key if config else None
    return DEFAULT_MODEL_BY_PROVIDER.get(key.provider) if key else ranking.DEFAULT_JUDGE_MODEL


class _Stages:
    def __init__(self) -> None:
        self.record: dict[str, dict[str, Any]] = {}

    def set(self, name: str, status: str, **details: Any) -> None:
        self.record[name] = {"status": status, **details}


def _matches(handoff: Handoff, evals: Sequence[coverage_stage.ExistingEval]) -> dict[str, list[tuple[Any, float]]]:
    """Matches against the team's evaluations as they are now. An evaluation deleted since matching drops out."""
    by_id = {e.id: e for e in evals}
    return {
        key: [(by_id[eval_id], confidence) for eval_id, confidence in pairs if eval_id in by_id]
        for key, pairs in handoff.matches.items()
    }


def _current_coverage(team: Team) -> Coverage:
    """Evaluations and dismissals read again, since the team can change both while the run works. Fixes were
    read by the measure stage and are already candidates."""
    return Coverage(evals=existing_evals(team), fixes=[], dismissed_dedupe_keys=dismissed_dedupe_keys(team))


def paid_call(
    run: EvalSuggestionRun, client: Anthropic, request: call_review.ModelRequest, budget: float
) -> call_review.ModelCall | None:
    """One model call charged to the run, or None when the budget cannot cover the most it could cost.

    The run's spend holds that maximum while the call is in flight and keeps it when the call raises,
    since the provider may have billed. A call that returns settles to the cost it reports.
    """
    reserved = call_review.max_cost_usd(request)
    if not runs.reserve_spend(run, reserved, budget):
        return None
    result = call_review.call(client, request)
    runs.settle_spend(run, reserved, result.cost_usd)
    return result


def dedupe(
    proposals: Sequence[Proposal],
    coverage: Coverage,
    jeeves_matches: dict[str, list[tuple[coverage_stage.ExistingEval, float]]],
    sources: dict[str, str],
) -> list[Proposal]:
    """Drop proposals the team dismissed or an evaluation already covers, and label near misses.

    An evaluation covers a proposal only when it runs the same check wherever the proposal would run.
    One that runs it elsewhere, or that the decision model matched without enough confidence, leaves the
    proposal in place, labelled as similar.
    """
    kept = []
    for proposal in proposals:
        if proposal.dedupe_key in coverage.dismissed_dedupe_keys:
            continue
        if proposal.kind != EvalSuggestionKind.FIX_EVAL:
            target = str(proposal.draft.get("target", "generation"))
            implementations = coverage_stage.implementations(
                coverage.evals,
                dedupe_key=proposal.dedupe_key,
                template_key=proposal.template_key,
                source=sources.get(proposal.template_key),
                prompt=proposal.draft.get("evaluation_config", {}).get("prompt"),
            )
            # Every confident match counts, since a less confident one may be the evaluation that covers this scope.
            matches = jeeves_matches.get(proposal.dedupe_key, [])
            implementations += [
                existing for existing, confidence in matches if confidence >= screening.DEDUPE_CONFIDENCE
            ]
            if any(coverage_stage.covers(existing, target, proposal.filters) for existing in implementations):
                continue
            similar = implementations[0] if implementations else (matches[0][0] if matches else None)
            if similar is not None:
                proposal = replace(
                    proposal, similar_evaluation_id=similar.id, score=proposal.score * ranking.SIMILAR_FACTOR
                )
        kept.append(proposal)
    return kept


def _time_left(deadline: float | None) -> float:
    return float("inf") if deadline is None else deadline - time.monotonic()


@frozen
class _Calibrated:
    kept: list[tuple[call_review.ReviewCard, judge_calibration.Calibration]]
    # What the run records: why calibration was skipped, or each card's counts.
    record: dict[str, Any]
    cost_usd: float


def _calibrate(
    team: Team,
    run: EvalSuggestionRun,
    cards: Sequence[call_review.ReviewCard],
    rendering: call_review.Rendering,
    judge_model: str,
    budget: float,
    deadline: float | None,
) -> _Calibrated:
    """Run each card's judge on the review's labelled calls, on the model the accepted judge will run on, and keep
    the cards it agrees with. Every request's most is reserved from the run's budget first."""
    if not cards:
        return _Calibrated(kept=[], record={"status": "skipped", "detail": "no cards"}, cost_usd=0.0)
    numbers = [judge_calibration.calibration_calls(card) for card in cards]
    requests = [
        judge_calibration.judge_request(card, rendering, number, judge_model)
        for card, card_numbers in zip(cards, numbers)
        for number in card_numbers
    ]
    if _time_left(deadline) < call_review.max_seconds(judge_calibration.TIMEOUT_SECONDS):
        return _Calibrated(kept=[], record={"status": "skipped", "detail": "not enough time left"}, cost_usd=0.0)
    client = judge_calibration.build_client(team.pk, str(run.id), judge_model, run.trigger)
    reserved = judge_calibration.max_cost_usd(requests)
    if not runs.reserve_spend(run, reserved, budget):
        return _Calibrated(kept=[], record={"status": "skipped", "detail": "budget used up"}, cost_usd=0.0)
    calls = judge_calibration.judge_all(client, requests, deadline)
    cost = sum(call.cost_usd for call in calls if call is not None)
    runs.settle_spend(run, reserved, cost)
    verdicts = iter([call.verdict if call is not None else None for call in calls])
    calibrations = [
        judge_calibration.calibrate(card, card_numbers, [next(verdicts) for _ in card_numbers])
        for card, card_numbers in zip(cards, numbers)
    ]
    return _Calibrated(
        kept=[(card, c) for card, c in zip(cards, calibrations) if judge_calibration.keeps(card, c)],
        record={
            "status": "ok",
            "model": judge_model,
            "cards": [
                {"title": card.title, **asdict(c), "kept": judge_calibration.keeps(card, c)}
                for card, c in zip(cards, calibrations)
            ],
        },
        cost_usd=cost,
    )


def _reviewed_proposals(
    team: Team,
    run: EvalSuggestionRun,
    handoff: Handoff,
    judge_model: str,
    budget: float,
    review_calls: int,
    stages: _Stages,
    deadline: float | None,
) -> list[Proposal]:
    """Triage the busiest call types, review a sample of the picked ones, and turn the review's cards into
    calibrated candidates. Each paid call reserves its most from the run's budget first."""
    day = ProfileWindow(start=handoff.window.end - REVIEW_WINDOW, end=handoff.window.end)
    per_mille = sample_per_mille(handoff.profile.generations_by_days_ago.get(0, 0))
    call_types = load_call_types(team, day, per_mille)
    if not call_types:
        stages.set("drafting", "skipped", detail="no generations with a model and an input in the last day")
        return []
    client = call_review.build_client(team.pk, str(run.id), run.trigger)
    triage_call = paid_call(run, client, call_review.triage_request(call_types), budget)
    if triage_call is None:
        stages.set("drafting", "skipped", detail="budget used up")
        return []
    spent = triage_call.cost_usd
    triage = call_review.parse_triage(triage_call.answer, call_types)
    if triage is None:
        stages.set("drafting", "failed", detail="unreadable triage answer", cost_usd=round(spent, 4))
        return []
    if triage.excluded or not triage.picked:
        detail = "content the review does not read" if triage.excluded else "no call type worth reviewing"
        stages.set("drafting", "skipped", detail=detail, cost_usd=round(spent, 4))
        return []
    calls = call_review.select_calls(load_review_calls(team, day, per_mille, triage.picked), limit=review_calls)
    if len(calls) < call_review.MIN_CARD_FAILURES:
        stages.set("drafting", "skipped", detail="too few calls with a text answer", cost_usd=round(spent, 4))
        return []
    rendering = call_review.render(triage.picked, calls, review_calls, coverage_stage.earlier_review_cards(team))
    request = call_review.review_request(rendering)
    # A review that starts too late to finish would be paid for and then lost with the timed-out attempt.
    if _time_left(deadline) < call_review.max_seconds(request.timeout):
        stages.set("drafting", "skipped", detail="not enough time left", cost_usd=round(spent, 4))
        return []
    review_call = paid_call(run, client, request, budget)
    if review_call is None:
        stages.set("drafting", "skipped", detail="budget used up", cost_usd=round(spent, 4))
        return []
    cards = call_review.parse_cards(review_call.answer, rendering)
    spent += review_call.cost_usd
    # A rule broken in most calls needs a prompt change, so its card skips the judge and its calibration cost.
    prompt_bugs = [card for card in cards if ranking.is_prompt_bug(card)]
    # The code stops in time for the judge calibration that a card falls back to.
    code_deadline = None if deadline is None else deadline - call_review.max_seconds(judge_calibration.TIMEOUT_SECONDS)
    checked = [
        (card, judge_calibration.check_code(card, rendering, code_deadline))
        for card in cards
        if card.code_check and card not in prompt_bugs
    ]
    kept_code = [
        (card, code) for card, code in checked if code is not None and judge_calibration.keeps(card, code.calibration)
    ]
    # Every card is settled on the calls the review labelled before the time left goes to counting more calls.
    day_calls = _code_check_calls(team, day, per_mille, [card for card, _ in kept_code], code_deadline)
    widened = [
        (card, judge_calibration.counted_on_day(card, code, rendering, day_calls, code_deadline))
        for card, code in kept_code
    ]
    coded = [(card, code) for card, code in widened if code is not None]
    coded_cards = [card for card, _ in coded]
    judged = [card for card in cards if card not in prompt_bugs and card not in coded_cards]
    calibrated = _calibrate(team, run, judged, rendering, judge_model, budget, deadline)
    snippets = _prompt_snippets(
        team, day, per_mille, call_types, [*coded_cards, *(card for card, _ in calibrated.kept)], deadline
    )
    proposals = [
        ranking.review_proposal(
            judge_calibration.measured(card, calibration),
            handoff.profile,
            snippets=snippets,
            judge_model=judge_model,
            calibration=calibration,
        )
        for card, calibration in calibrated.kept
    ] + [ranking.review_code_proposal(card, handoff.profile, snippets=snippets, code=code) for card, code in coded]
    scoped = [proposal for proposal in proposals if proposal is not None]
    stages.set(
        "drafting",
        "ok",
        call_types=len(call_types),
        picked=len(triage.picked),
        reviewed=len(calls),
        cards=len(cards),
        calibration=calibrated.record,
        prompt_bugs=len(prompt_bugs),
        # Where the review saw the team's prompt and its judge disagree, for staff to read before trusting a card.
        conflicts=[{"title": card.title, "conflict": card.conflict} for card in cards if card.conflict],
        code_checks=len(coded),
        code_calibration=[
            {
                "title": card.title,
                "compiles": code is not None,
                **({**asdict(code.calibration), "errors": code.errors} if code is not None else {}),
                "kept": card in coded_cards,
            }
            for card, code in checked
        ],
        # Kept cards whose generations no filter selects, which the run leaves out.
        unscoped=len(proposals) - len(scoped),
        cost_usd=round(spent + calibrated.cost_usd, 4),
    )
    named = {c.name for card in prompt_bugs for c in card.call_types if c.source == "prompt_name"}
    managed = coverage_stage.managed_prompt_names(team, named) if named else frozenset()
    return [*scoped, *(ranking.prompt_fix_proposal(card, managed) for card in prompt_bugs)]


def _prompt_snippets(
    team: Team,
    window: ProfileWindow,
    per_mille: int,
    call_types: Sequence[CallTypeRow],
    cards: Sequence[call_review.ReviewCard],
    deadline: float | None,
) -> dict[str, str]:
    """The snippet that selects each input-named call type on the cards, keyed by call type. Each candidate is
    counted on the day's generations, and a call type whose candidates all match other generations gets none.
    Without time left for the count, or when the count fails, no call type gets one, and the run leaves their cards
    out while it keeps the cards that a prompt or span name scopes."""
    # A snippet is prompt text, and an accepted card copies it into evaluation conditions that every member who reads
    # evaluations sees. A team with property access rules can have members who may not read $ai_input.
    if team_has_property_access_rules(team_id=team.pk):
        return {}
    unnamed = {c.name: c for card in cards for c in card.call_types if c.source == "input"}
    candidates = {
        name: ranking.prompt_snippets(call_type, [c for c in call_types if c.key != call_type.key])
        for name, call_type in unnamed.items()
    }
    candidates = {name: texts for name, texts in candidates.items() if texts}
    if not candidates or _time_left(deadline) < MAX_EXECUTION_TIME_SECONDS:
        return {}
    try:
        matches = snippet_matches(team, window, per_mille, candidates)
    except Exception as error:
        logger.warning("eval_suggestions_snippet_count_failed", team_id=team.pk, error=str(error))
        return {}
    chosen = {unnamed[name].key: ranking.choose_snippet(texts, matches[name]) for name, texts in candidates.items()}
    return {key: snippet for key, snippet in chosen.items() if snippet is not None}


def _code_check_calls(
    team: Team, window: ProfileWindow, per_mille: int, cards: Sequence[call_review.ReviewCard], deadline: float | None
) -> list[ReviewCallRow]:
    """More of the day's calls of the code cards' call types to count them on, or none, which leaves each code check
    counted on the calls the review read."""
    call_types = list({c.key: c for card in cards for c in card.call_types}.values())
    if not call_types or _time_left(deadline) < MAX_EXECUTION_TIME_SECONDS:
        return []
    try:
        return load_review_calls(team, window, per_mille, call_types, per_type=CODE_CHECK_CALLS_PER_CALL_TYPE)
    except Exception as error:
        logger.warning("eval_suggestions_code_check_calls_failed", team_id=team.pk, error=str(error))
        return []


def _publish_fixes_only(
    run: EvalSuggestionRun,
    stages: "_Stages",
    window: ProfileWindow,
    profile: TeamProfile,
    fixes: list[Proposal],
    model: str | None,
) -> int:
    """Hand only the fix cards on, which need no trace content, and skip measuring and screening."""
    runs.save_handoff(
        run,
        Handoff(
            window=window,
            profile=profile,
            sample=[],
            proposals=fixes,
            screened_judges=[],
            judge_target="trace",
            judge_model=model,
            sources={},
            candidate_options={},
        ),
        stages.record,
        "measure",
    )
    return len(fixes)


def measure_stage(
    team_id: int,
    run_id: str,
    *,
    settings: SuggestionSettings,
    now: datetime | None = None,
    deadline: float | None = None,
) -> int:
    """Stage 1: everything free. Returns the number of candidates handed on.

    `deadline` is a time.monotonic() value. A worker thread cannot be stopped from outside, so measuring stops at
    it and the stage raises rather than hand on checks measured on part of the sample.
    """
    run = runs.running_run(team_id, run_id)
    if run is None:
        return 0
    team = run.team
    # The weekly plan can be days old, so an organization taken off the rollout since then gets nothing new.
    if not runs_for_organization(str(team.organization_id)):
        runs.fail_run(team_id, run_id, "The organization is no longer in the eval suggestions rollout")
        return 0
    stages = _Stages()
    end = (now or timezone.now()) - SETTLE
    window = ProfileWindow(start=end - WINDOW, end=end)

    coverage = coverage_stage.fetch_coverage(team, window.start, window.end)
    stages.set(
        "coverage",
        "ok",
        evaluations=len(coverage.evals),
        fixes=len(coverage.fixes),
        dismissed=len(coverage.dismissed_dedupe_keys),
    )
    fixes = [ranking.fix_proposal(fix) for fix in coverage.fixes]
    model = judge_model(team)
    profile = fetch_profile(team, window)
    if profile.generations == 0:
        stages.set("profile", "skipped", detail="no generations in the last 7 days")
        return _publish_fixes_only(run, stages, window, profile, fixes, model)

    refs = discover_sample(team, window, profile)
    sample = hydrate_sample(team, window, list(profile.segments), refs)
    hydrated = {s.trace.id for s in sample.traces}
    content = content_profile(sample)
    stages.set(
        "profile",
        "ok",
        generations=profile.generations,
        traces=profile.traces,
        tool_call_share=round(profile.tool_call_share, 3),
        dispatcher_tools=sorted(set(profile.dispatcher_tools) | set(content.dispatcher_tools)),
        segments=sorted(profile.segments),
        sampled=len(sample.main),
        held_out=len(sample.held_out),
        multi_turn_share=round(content.multi_turn_share, 3),
        text_share=round(content.text_share, 3),
        output_share=round(content.output_share, 3),
        spanning_days_share=round(content.spanning_days_share, 3),
    )
    # Without the model's inputs and outputs, every suggestion would be a generic error count. The instrumentation
    # checklist already asks the team to capture them, so the run stops before any check or paid call.
    if content.output_share < MIN_CONTENT_SHARE:
        stages.set("applicability", "skipped", detail="too few traces carry the model's output")
        return _publish_fixes_only(run, stages, window, profile, fixes, model)

    applicability = applicable(profile, content)
    stages.set(
        "applicability", "ok", checks=[c.key for c in applicability.checks], judges=applicability.screened_judges
    )
    measurements = measure(applicability.checks, sample, deadline)
    _on_time(deadline)
    stages.set(
        "measure",
        "ok",
        checks={
            m.check.key: {
                "failed": sum(1 for o in m.main if o.failed),
                "applicable": sum(1 for o in m.main if o.failed is not None),
            }
            for m in measurements
        },
    )

    held_out_outputs = structured_outputs(sample.held_out)
    gaps = [
        gap
        for gap in find_structured_gaps(structured_outputs(sample.main))
        if gap_holds(gap, held_out_outputs) is not False
    ]
    gap_proposals = (
        [ranking.gap_proposal(gap, sample, profile, judge_model=model, similar_evaluation_id=None) for gap in gaps]
        if model is not None
        else []
    )
    proposals: list[Proposal] = list(fixes)
    proposals += [
        p for m in measurements if (p := ranking.code_check_proposal(m, sample, profile, similar_evaluation_id=None))
    ]
    proposals += gap_proposals
    runs.save_handoff(
        run,
        Handoff(
            window=window,
            profile=profile,
            sample=[ref for ref in refs if ref.trace_id in hydrated],
            proposals=proposals,
            screened_judges=list(applicability.screened_judges) if model is not None else [],
            judge_target=applicability.judge_target,
            judge_model=model,
            sources={m.check.key: m.check.source for m in measurements},
            candidate_options=(
                {ranking.check_dedupe_key(m.check.key): m.check.description for m in measurements}
                | {
                    ranking.judge_dedupe_key(key): catalog.template(key).description
                    for key in applicability.screened_judges
                }
                | {p.dedupe_key: p.draft["description"] for p in gap_proposals}
            ),
        ),
        stages.record,
        "measure",
    )
    return len(proposals)


def _paid_skip(team: Team, include_paid: bool, enabled: bool) -> str | None:
    if not include_paid:
        return "free stages only"
    if not enabled:
        return "switched off"
    if not screening.consented(team):
        return "AI data processing not approved"
    return None


def screen_stage(
    team_id: int, run_id: str, *, include_paid: bool, settings: SuggestionSettings, deadline: float | None = None
) -> int:
    """Stage 2: screen traces for the judges and match hand-written evaluations. Both stop at `deadline` and keep
    what they finished. Returns the number of screened judge candidates."""
    run = runs.running_run(team_id, run_id)
    if run is None:
        return 0
    team = run.team
    handoff = runs.load_handoff(run)
    stages = _Stages()
    skip = _paid_skip(team, include_paid, settings.jeeves)
    if skip is None and not handoff.sample:
        skip = "no traces to screen"
    if skip is not None:
        stages.set("screening", "skipped", detail=skip)
        runs.save_handoff(run, handoff, stages.record, "screening")
        return 0
    try:
        client = screening.build_client(team, run.trigger)
        evals = existing_evals(team)
        unmapped = sorted(
            (e for e in evals if e.enabled and e.template_key is None and e.dedupe_key is None),
            key=lambda e: e.updated_at,
            reverse=True,
        )[:MAX_DEDUPED_EVALS]
        matches = screening.dedupe(client, unmapped, handoff.candidate_options, deadline) if unmapped else {}
        sample = hydrate_sample(team, handoff.window, list(handoff.profile.segments), handoff.sample)
        screened = screening.screen(client, handoff.screened_judges, sample.main, deadline)
    except SystemOneNotConfigured:
        stages.set("screening", "skipped", detail="System One is not configured")
        runs.save_handoff(run, handoff, stages.record, "screening")
        return 0
    except SystemOneRequestFailed as error:
        stages.set("screening", "failed", detail=str(error))
        runs.save_handoff(run, handoff, stages.record, "screening")
        return 0
    proposals = [
        p
        for result in screened
        if handoff.judge_model is not None
        and (
            p := ranking.screened_proposal(
                result,
                handoff.profile,
                sample,
                target=handoff.judge_target,
                judge_model=handoff.judge_model,
                similar_evaluation_id=None,
            )
        )
    ]
    stages.set(
        "screening", "ok", flagged={r.template_key: len(r.flagged) for r in screened}, dedupe_matches=len(matches)
    )
    runs.save_handoff(
        run,
        replace(
            handoff,
            proposals=[*handoff.proposals, *proposals],
            matches={key: [(e.id, confidence) for e, confidence in pairs] for key, pairs in matches.items()},
        ),
        stages.record,
        "screening",
    )
    return len(proposals)


def draft_stage(
    team_id: int, run_id: str, *, include_paid: bool, settings: SuggestionSettings, deadline: float | None = None
) -> int:
    """Stage 3: review a sample of the team's calls and draft at most two judges. Returns the number of candidates."""
    run = runs.running_run(team_id, run_id)
    if run is None:
        return 0
    team = run.team
    handoff = runs.load_handoff(run)
    stages = _Stages()
    skip = _paid_skip(team, include_paid, settings.llm_drafting)
    # The measure stage hands on no sample when the team captures too little of the model's output to review.
    if skip is None and not handoff.sample:
        skip = "no traces with content"
    if skip is None and handoff.judge_model is None:
        skip = "no judge model for the team's provider key"
    # Its cards could not be calibrated, so the review would be paid for and dropped.
    if skip is None and judge_calibration.provider(handoff.judge_model) is None:
        skip = f"no gateway route to calibrate judges on {handoff.judge_model}"
    needed = (
        call_review.max_seconds(call_review.TRIAGE_TIMEOUT_SECONDS)
        + call_review.max_seconds(call_review.REVIEW_TIMEOUT_SECONDS)
        + call_review.max_seconds(judge_calibration.TIMEOUT_SECONDS)
    )
    if skip is None and _time_left(deadline) < needed:
        skip = "not enough time left"
    if skip is not None or handoff.judge_model is None:
        stages.set("drafting", "skipped", detail=skip)
        runs.save_handoff(run, handoff, stages.record, "drafting")
        return 0
    try:
        drafted = _reviewed_proposals(
            team,
            run,
            handoff,
            handoff.judge_model,
            settings.llm_budget_usd_per_run,
            settings.review_calls,
            stages,
            deadline,
        )
    except GatewayNotConfiguredError:
        stages.set("drafting", "skipped", detail="the AI gateway is not configured")
        drafted = []
    except Exception as error:
        logger.warning("eval_suggestions_review_failed", team_id=team.pk, error=str(error))
        stages.set("drafting", "failed", detail=type(error).__name__)
        drafted = []
    runs.save_handoff(run, replace(handoff, proposals=[*handoff.proposals, *drafted]), stages.record, "drafting")
    return len(drafted)


def publish_stage(team_id: int, run_id: str) -> int:
    """Stage 4: dedupe against the team's evaluations as they are now, pick at most three, and publish."""
    run = runs.get_run(team_id, run_id)
    if run.status == EvalSuggestionRunStatus.COMPLETED:
        # Temporal retries an attempt whose result it lost after the run had published.
        return runs.published_count(run)
    if run.status == EvalSuggestionRunStatus.FAILED:
        return 0
    handoff = runs.load_handoff(run)
    coverage = _current_coverage(run.team)
    stages = _Stages()
    for name in PAID_STAGES:
        # A paid stage that timed out or crashed recorded nothing, and the run publishes without it.
        if name not in run.stages:
            stages.set(name, "failed", detail="the stage did not finish")
    # A drafted card comes after the templated one for the same gap and shares its dedupe key, so it replaces it.
    best = {
        p.dedupe_key: p for p in dedupe(handoff.proposals, coverage, _matches(handoff, coverage.evals), handoff.sources)
    }
    picked = ranking.pick(list(best.values()))
    stages.set(
        "ranking",
        "ok",
        candidates=len(handoff.proposals),
        after_dedupe=len(best),
        picked=[p.dedupe_key for p in picked],
    )
    return len(runs.publish(run, picked, {**run.stages, **stages.record}))


class RunDeadlinePassed(Exception):
    pass


def _on_time(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() >= deadline:
        raise RunDeadlinePassed("The attempt ran out of time before publishing")
