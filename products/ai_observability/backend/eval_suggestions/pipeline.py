"""One team's run, as four stages that each run in their own Temporal activity:

1. measure: coverage, profile, the trace sample, the free checks and the gap judges.
2. screen: the decision model screens traces for the judges and matches hand-written evaluations. Paid.
3. draft: one paid draft for the best uncovered gap.
4. publish: dedupe, pick at most three, and publish them in one transaction.

Stages hand over through `EvalSuggestionRun.handoff`: trace ids and candidate cards, never trace content. A stage
that needs traces hydrates them again from their ids, so a retry redoes one stage and a timeout stops that stage.
"""

import time
from collections.abc import Sequence
from dataclasses import field, replace
from datetime import datetime, timedelta
from typing import Any

from django.db import connection, transaction
from django.db.models import F, Sum
from django.utils import timezone

import structlog
from pydantic import TypeAdapter

from posthog.dataclasses import frozen
from posthog.llm.system_one import SystemOneNotConfigured, SystemOneRequestFailed
from posthog.models.team import Team

from products.ai_observability.backend.llm import DEFAULT_MODEL_BY_PROVIDER
from products.ai_observability.backend.models.eval_suggestions import (
    EvalSuggestion,
    EvalSuggestionKind,
    EvalSuggestionRun,
    EvalSuggestionRunStatus,
    EvalSuggestionStatus,
)
from products.ai_observability.backend.models.evaluation_config import EvaluationConfig

from ee.hogai.utils.feature_flags import is_privacy_mode_enabled

from . import (
    catalog,
    coverage as coverage_stage,
    drafting,
    ranking,
    screening,
)
from .adapters import AdaptedCheck, compile_check
from .applicability import applicable, content_profile
from .config import SuggestionSettings, is_enabled_for_organization
from .coverage import Coverage, dismissed_dedupe_keys, existing_evals
from .measure import (
    Measurement,
    Outcome,
    SampleRef,
    TraceSample,
    discover_sample,
    hydrate_sample,
    measure,
    run_check,
    structured_outputs,
)
from .profile import ProfileWindow, StructuredGap, TeamProfile, fetch_profile, find_structured_gaps, gap_holds
from .ranking import Proposal

logger = structlog.get_logger(__name__)

WINDOW = timedelta(days=7)
# Traces younger than this may still be receiving events, so the window stops short of now.
SETTLE = timedelta(minutes=30)
# A drafted body under the per-trace limit can still be slow on every trace, so measuring it has a total budget.
DRAFT_MEASURE_BUDGET_SECONDS = 120
DRAFT_ABORT_ERRORS = ("Execution timed out", "Memory limit exceeded")
# Dedupe asks the model about each hand-written evaluation, so a team with many pays for this many at most.
MAX_DEDUPED_EVALS = 50
JUDGE_KINDS = frozenset({EvalSuggestionKind.NEW_LLM_JUDGE})
PAID_STAGES = ("screening", "drafting")
STAGE_ORDER = ("measure", "screening", "drafting")


def judge_model(team: Team) -> str | None:
    """The model a new judge would run on: the default for the team's active key, else the product default.

    None when the key's provider has no default model, since the evaluator refuses to run a judge without one.
    """
    config = EvaluationConfig.objects.filter(team_id=team.pk).select_related("active_provider_key").first()
    key = config.active_provider_key if config else None
    return DEFAULT_MODEL_BY_PROVIDER.get(key.provider) if key else ranking.DEFAULT_JUDGE_MODEL


@frozen
class GapCandidate:
    gap: StructuredGap
    # The templated judge for the gap, which a draft replaces.
    proposal: Proposal


@frozen
class Handoff:
    window: ProfileWindow
    profile: TeamProfile
    # The traces the measure stage read, which later stages hydrate again.
    sample: list[SampleRef]
    # Candidates from every stage so far.
    proposals: list[Proposal]
    gaps: list[GapCandidate]
    screened_judges: list[str]
    judge_target: str
    judge_model: str | None
    # Check key -> Hog source, so dedupe can match an evaluation running the same code.
    sources: dict[str, str]
    # Dedupe key -> what the candidate checks, for matching against hand-written evaluations.
    candidate_options: dict[str, str]
    # Dedupe key -> (evaluation id, confidence) from that matching.
    matches: dict[str, list[tuple[str, float]]] = field(default_factory=dict)
    # The last stage that wrote this handoff.
    written_by: str = "measure"


_HANDOFF = TypeAdapter(Handoff)


class _Stages:
    def __init__(self) -> None:
        self.record: dict[str, dict[str, Any]] = {}

    def set(self, name: str, status: str, **details: Any) -> None:
        self.record[name] = {"status": status, **details}


def _running_run(team_id: int, run_id: str) -> EvalSuggestionRun | None:
    """The run while it still works. A run another attempt published or gave up on is left alone."""
    run = EvalSuggestionRun.objects.for_team(team_id).select_related("team").get(id=run_id)
    return run if run.status == EvalSuggestionRunStatus.RUNNING else None


def _load(run: EvalSuggestionRun) -> Handoff:
    return _HANDOFF.validate_python(run.handoff)


def _save(run: EvalSuggestionRun, handoff: Handoff, stages: _Stages, stage: str) -> None:
    """Store a stage's result while the run still works.

    A timed-out attempt keeps running in its thread and can finish after its retry and the stages after it. Its write
    is dropped when the run is no longer running, or when a later stage already wrote the handoff.
    """
    with transaction.atomic():
        locked = EvalSuggestionRun.objects.for_team(run.team_id).select_for_update().get(id=run.id)
        if locked.status != EvalSuggestionRunStatus.RUNNING:
            return
        written_by = (locked.handoff or {}).get("written_by")
        if written_by in STAGE_ORDER and STAGE_ORDER.index(written_by) > STAGE_ORDER.index(stage):
            return
        locked.handoff = _HANDOFF.dump_python(replace(handoff, written_by=stage), mode="json")
        locked.stages = {**locked.stages, **stages.record}
        locked.save(update_fields=["handoff", "stages"])


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


def _reserve(run: EvalSuggestionRun, amount: float, budget: float) -> bool:
    """Add `amount` to the run's spend if its coordinator run stays within `budget`. A run without a
    coordinator has a budget of its own."""
    runs = EvalSuggestionRun.objects.unscoped()
    with transaction.atomic():
        # Teams of one coordinator run draft concurrently, so the sum and the write share a lock.
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                [f"llma-eval-suggestions-budget:{run.batch_id or run.id}"],
            )
        charged = runs.filter(batch_id=run.batch_id) if run.batch_id else runs.filter(id=run.id)
        spent = charged.aggregate(total=Sum("cost_usd"))["total"] or 0.0
        if spent + amount > budget:
            return False
        runs.filter(id=run.id).update(cost_usd=F("cost_usd") + amount)
    return True


def paid_draft(team: Team, run: EvalSuggestionRun, brief: str, budget: float) -> drafting.DraftCall | None:
    """One draft call charged to the run, or None when the budget cannot cover the most it could cost.

    The run's spend holds that maximum while the call is in flight and keeps it when the call raises,
    since the provider may have billed. A call that returns settles to the cost it reports.
    """
    reserved = drafting.max_cost_usd(brief)
    if not _reserve(run, reserved, budget):
        return None
    # The brief carries segment values and tool names, so an organization in privacy mode keeps it out of analytics.
    call = drafting.draft_check(team.pk, brief, privacy_mode=is_privacy_mode_enabled(team))
    EvalSuggestionRun.objects.for_team(team.pk).filter(id=run.id).update(
        cost_usd=F("cost_usd") - reserved + call.cost_usd
    )
    return call


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


def _drafted_proposals(
    team: Team,
    run: EvalSuggestionRun,
    gap_proposals: Sequence[tuple[StructuredGap, Proposal]],
    sample: TraceSample,
    profile: TeamProfile,
    settings: SuggestionSettings,
    stages: _Stages,
) -> list[Proposal]:
    if not gap_proposals:
        stages.set("drafting", "skipped", detail="no uncovered finding")
        return []
    gap, templated = max(gap_proposals, key=lambda pair: pair[1].score)
    call = paid_draft(team, run, drafting.gap_brief(gap, profile), settings.llm_budget_usd_per_run)
    if call is None:
        stages.set("drafting", "skipped", detail="budget used up")
        return []
    draft = call.draft
    if draft is None:
        stages.set("drafting", "failed", detail="no usable draft", cost_usd=round(call.cost_usd, 4))
        return []
    stages.set("drafting", "ok", evaluation_type=draft.evaluation_type, cost_usd=round(call.cost_usd, 4))
    if draft.evaluation_type == "llm_judge":
        drafted_judge = {
            **templated.draft,
            "name": draft.name,
            "description": draft.description,
            "evaluation_config": {"prompt": draft.body},
        }
        return [replace(templated, draft=drafted_judge)]
    check = AdaptedCheck(
        # The dedupe key names the gap. This key only has to fit template_key, so it stays fixed.
        key="drafted_gap",
        name=draft.name,
        description=draft.description,
        source=draft.body,
        template_key="",
        severity=ranking.SEVERITY["structured_output_gap"],
    )
    try:
        bytecode = compile_check(check)
    except Exception:
        stages.set("drafting", "failed", detail="drafted Hog does not compile")
        return []
    # A drafted body can loop until the 10s Hog limit on some inputs and not others, so the first trace that
    # times out or runs out of memory stops the whole measurement.
    outcomes: dict[bool, list[Outcome]] = {False: [], True: []}
    stop_at = time.monotonic() + DRAFT_MEASURE_BUDGET_SECONDS
    for sampled in sample.traces:
        [outcome] = run_check(bytecode, [sampled])
        too_slow = time.monotonic() > stop_at
        if too_slow or (outcome.failed is None and outcome.reasoning.startswith(DRAFT_ABORT_ERRORS)):
            stages.set("drafting", "failed", detail="drafted Hog runs too long")
            return []
        outcomes[sampled.held_out].append(outcome)
    measured = [Measurement(check=check, main=outcomes[False], held_out=outcomes[True])]
    proposal = ranking.code_check_proposal(measured[0], sample, profile, similar_evaluation_id=None)
    # The draft replaces the templated card for the same gap, so it shares its key and dismissals.
    return [replace(proposal, dedupe_key=templated.dedupe_key)] if proposal else []


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
    run = _running_run(team_id, run_id)
    if run is None:
        return 0
    team = run.team
    # The weekly plan can be days old, so an organization taken off the rollout since then gets nothing new.
    if not is_enabled_for_organization(str(team.organization_id)):
        fail_run(team_id, run_id, "The organization is no longer in the eval suggestions rollout")
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
        _save(
            run,
            Handoff(
                window=window,
                profile=profile,
                sample=[],
                proposals=fixes,
                gaps=[],
                screened_judges=[],
                judge_target="trace",
                judge_model=model,
                sources={},
                candidate_options={},
            ),
            stages,
            "measure",
        )
        return len(fixes)

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
        spanning_days_share=round(content.spanning_days_share, 3),
    )

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
    # Without a judge model a gap still gets a drafted Hog check, priced as if it ran on the product default.
    gap_candidates = [
        GapCandidate(
            gap=gap,
            proposal=ranking.gap_proposal(
                gap, sample, profile, judge_model=model or ranking.DEFAULT_JUDGE_MODEL, similar_evaluation_id=None
            ),
        )
        for gap in gaps
    ]
    proposals: list[Proposal] = list(fixes)
    proposals += [
        p for m in measurements if (p := ranking.code_check_proposal(m, sample, profile, similar_evaluation_id=None))
    ]
    if model is not None:
        proposals += [candidate.proposal for candidate in gap_candidates]
    _save(
        run,
        Handoff(
            window=window,
            profile=profile,
            sample=[ref for ref in refs if ref.trace_id in hydrated],
            proposals=proposals,
            gaps=gap_candidates,
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
                | {c.proposal.dedupe_key: c.proposal.draft["description"] for c in gap_candidates}
            ),
        ),
        stages,
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
    run = _running_run(team_id, run_id)
    if run is None:
        return 0
    team = run.team
    handoff = _load(run)
    stages = _Stages()
    skip = _paid_skip(team, include_paid, settings.jeeves)
    if skip is None and not handoff.sample:
        skip = "no traces to screen"
    if skip is not None:
        stages.set("screening", "skipped", detail=skip)
        _save(run, handoff, stages, "screening")
        return 0
    try:
        client = screening.build_client(team)
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
        _save(run, handoff, stages, "screening")
        return 0
    except SystemOneRequestFailed as error:
        stages.set("screening", "failed", detail=str(error))
        _save(run, handoff, stages, "screening")
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
    _save(
        run,
        replace(
            handoff,
            proposals=[*handoff.proposals, *proposals],
            matches={key: [(e.id, confidence) for e, confidence in pairs] for key, pairs in matches.items()},
        ),
        stages,
        "screening",
    )
    return len(proposals)


def draft_stage(
    team_id: int, run_id: str, *, include_paid: bool, settings: SuggestionSettings, deadline: float | None = None
) -> int:
    """Stage 3: one paid draft for the best uncovered gap. Returns the number of drafted candidates."""
    run = _running_run(team_id, run_id)
    if run is None:
        return 0
    team = run.team
    handoff = _load(run)
    stages = _Stages()
    skip = _paid_skip(team, include_paid, settings.llm_drafting)
    coverage = _current_coverage(team)
    matches = _matches(handoff, coverage.evals)
    # Paying for a draft of a finding the team dismissed or already covers would be wasted.
    draftable = [(c.gap, c.proposal) for c in handoff.gaps if dedupe([c.proposal], coverage, matches, {})]
    if skip is None and not draftable:
        skip = "no uncovered finding"
    sample = (
        hydrate_sample(team, handoff.window, list(handoff.profile.segments), handoff.sample) if skip is None else None
    )
    # Checked after hydration, which can take minutes: a draft that starts too late to finish would be paid for and
    # then lost with the timed-out attempt.
    if (
        skip is None
        and deadline is not None
        and deadline - time.monotonic() < drafting.max_draft_seconds() + DRAFT_MEASURE_BUDGET_SECONDS
    ):
        skip = "not enough time left"
    if skip is not None or sample is None:
        stages.set("drafting", "skipped", detail=skip)
        _save(run, handoff, stages, "drafting")
        return 0
    try:
        drafted = _drafted_proposals(team, run, draftable, sample, handoff.profile, settings, stages)
    except Exception as error:
        logger.warning("eval_suggestions_drafting_failed", team_id=team.pk, error=str(error))
        stages.set("drafting", "failed", detail=type(error).__name__)
        drafted = []
    if handoff.judge_model is None:
        drafted = [p for p in drafted if p.kind not in JUDGE_KINDS]
    _save(run, replace(handoff, proposals=[*handoff.proposals, *drafted]), stages, "drafting")
    return len(drafted)


def publish_stage(team_id: int, run_id: str) -> int:
    """Stage 4: dedupe against the team's evaluations as they are now, pick at most three, and publish."""
    run = EvalSuggestionRun.objects.for_team(team_id).select_related("team").get(id=run_id)
    if run.status == EvalSuggestionRunStatus.COMPLETED:
        # Temporal retries an attempt whose result it lost after the run had published.
        return EvalSuggestion.objects.for_team(team_id).filter(run=run).count()
    if run.status == EvalSuggestionRunStatus.FAILED:
        return 0
    handoff = _load(run)
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
    return len(publish(run, picked, {**run.stages, **stages.record}))


def publish(run: EvalSuggestionRun, proposals: Sequence[Proposal], stages: dict[str, Any]) -> list[EvalSuggestion]:
    """Write the run's suggestions and complete it in one transaction, so the API never reads half a set.

    Two attempts of one run can both get here when Temporal retries an attempt that is still running.
    The first to lock the run publishes, and the other returns what it published.
    """
    with transaction.atomic():
        locked = EvalSuggestionRun.objects.for_team(run.team_id).select_for_update().get(id=run.id)
        if locked.status == EvalSuggestionRunStatus.COMPLETED:
            return list(EvalSuggestion.objects.for_team(run.team_id).filter(run=run))
        # The run was given up on while this attempt still ran, so its cards must not replace last week's.
        if locked.status == EvalSuggestionRunStatus.FAILED:
            return []
        suggestions = EvalSuggestion.objects.for_team(run.team_id)
        # Expiring first locks the open cards, so a dismissal in flight commits before the dismissed keys are read.
        suggestions.filter(status=EvalSuggestionStatus.PROPOSED).exclude(run=run).update(
            status=EvalSuggestionStatus.EXPIRED, updated_at=timezone.now()
        )
        # The team can dismiss or accept a card while the run works, after the stages read the dismissals and
        # evaluations. A card accepted during the run would come back as new, since its evaluation is that young.
        dismissed = dismissed_dedupe_keys(run.team) | set(
            suggestions.filter(status=EvalSuggestionStatus.ACCEPTED, decided_at__gte=run.created_at).values_list(
                "dedupe_key", flat=True
            )
        )
        rows = suggestions.bulk_create(
            [
                EvalSuggestion(
                    team_id=run.team_id,
                    run=run,
                    kind=p.kind,
                    template_key=p.template_key,
                    dedupe_key=p.dedupe_key,
                    headline=p.headline[:400],
                    outcome=p.outcome,
                    reason=p.reason,
                    draft=p.draft,
                    filters=p.filters,
                    rollout_percentage=p.rollout_percentage,
                    measured_failure_rate=p.measured_failure_rate,
                    sample_size=p.sample_size,
                    evidence=[{"trace_id": e.trace_id, "reason": e.reason} for e in p.evidence],
                    score=p.score,
                    estimated_weekly_runs=p.estimated_weekly_runs,
                    estimated_weekly_cost_usd=p.estimated_weekly_cost_usd,
                    mean_input_tokens=p.mean_input_tokens,
                    judge_model=p.judge_model,
                    target_evaluation_id=p.target_evaluation_id,
                    similar_evaluation_id=p.similar_evaluation_id,
                )
                for p in proposals
                if p.dedupe_key not in dismissed
            ]
        )
        # cost_usd stays out of this save, because drafting updates it on the row and the value held here is stale.
        run.status = EvalSuggestionRunStatus.COMPLETED
        run.stages = stages
        run.handoff = {}
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "stages", "handoff", "completed_at"])
    return rows


class RunDeadlinePassed(Exception):
    pass


def _on_time(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() >= deadline:
        raise RunDeadlinePassed("The attempt ran out of time before publishing")


def create_run(team: Team, trigger: str, batch_id: str = "", run_id: str | None = None) -> EvalSuggestionRun:
    """A new run, or with `run_id` the run a retried start already created, so a retry never leaves one orphaned."""
    runs = EvalSuggestionRun.objects.for_team(team.pk)
    if run_id is None:
        return runs.create(team=team, trigger=trigger, batch_id=batch_id)
    run, _ = runs.get_or_create(id=run_id, defaults={"team": team, "trigger": trigger, "batch_id": batch_id})
    return run


def fail_run(team_id: int, run_id: str, error: str) -> None:
    """Mark a run failed unless an attempt already published, so a late failure never hides published cards."""
    EvalSuggestionRun.objects.for_team(team_id).filter(id=run_id).exclude(
        status=EvalSuggestionRunStatus.COMPLETED
    ).update(status=EvalSuggestionRunStatus.FAILED, error=error[:2000], handoff={}, completed_at=timezone.now())
