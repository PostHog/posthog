"""One team's run: stages 1 to 7, then an atomic publish of at most three suggestions.

Trace content stays inside this process. Temporal activities call it with ids and get counts back.
"""

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from django.db import connection, transaction
from django.db.models import F, Sum
from django.utils import timezone

import structlog

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

from . import (
    catalog,
    coverage as coverage_stage,
    drafting,
    ranking,
    screening,
)
from .adapters import AdaptedCheck, compile_check
from .applicability import applicable, content_profile
from .config import SuggestionSettings
from .coverage import Coverage
from .measure import Measurement, Outcome, TraceSample, fetch_sample, measure, run_check, structured_outputs
from .profile import ProfileWindow, StructuredGap, TeamProfile, fetch_profile, find_structured_gaps, gap_holds
from .ranking import Proposal

logger = structlog.get_logger(__name__)

WINDOW = timedelta(days=7)
# Traces younger than this may still be receiving events, so the window stops short of now.
SETTLE = timedelta(minutes=30)
DRAFT_ABORT_ERRORS = ("Execution timed out", "Memory limit exceeded")
# Dedupe asks the model about each hand-written evaluation, so a team with many pays for this many at most.
MAX_DEDUPED_EVALS = 50


def judge_model(team: Team) -> str:
    """The model a new judge would run on: the default for the team's active key, else the product default."""
    config = EvaluationConfig.objects.filter(team_id=team.pk).select_related("active_provider_key").first()
    key = config.active_provider_key if config else None
    return (
        DEFAULT_MODEL_BY_PROVIDER.get(key.provider, ranking.DEFAULT_JUDGE_MODEL) if key else ranking.DEFAULT_JUDGE_MODEL
    )


class _Stages:
    def __init__(self) -> None:
        self.record: dict[str, dict[str, Any]] = {}

    def set(self, name: str, status: str, **details: Any) -> None:
        self.record[name] = {"status": status, **details}


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
    call = drafting.draft_check(team.pk, brief)
    EvalSuggestionRun.objects.unscoped().filter(id=run.id).update(cost_usd=F("cost_usd") - reserved + call.cost_usd)
    return call


def dedupe(
    proposals: Sequence[Proposal],
    coverage: Coverage,
    jeeves_matches: dict[str, tuple[coverage_stage.ExistingEval, float]],
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
            match = jeeves_matches.get(proposal.dedupe_key)
            if match is not None and match[1] >= screening.DEDUPE_CONFIDENCE:
                implementations.append(match[0])
            if any(coverage_stage.covers(existing, target, proposal.filters) for existing in implementations):
                continue
            similar = implementations[0] if implementations else (match[0] if match else None)
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
        key=f"drafted_{gap.segment_key}",
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
    for sampled in sample.traces:
        [outcome] = run_check(bytecode, [sampled])
        if outcome.failed is None and outcome.reasoning.startswith(DRAFT_ABORT_ERRORS):
            stages.set("drafting", "failed", detail="drafted Hog runs too long")
            return []
        outcomes[sampled.held_out].append(outcome)
    measured = [Measurement(check=check, main=outcomes[False], held_out=outcomes[True])]
    proposal = ranking.code_check_proposal(measured[0], sample, profile, similar_evaluation_id=None)
    # The draft replaces the templated card for the same gap, so it shares its key and dismissals.
    return [replace(proposal, dedupe_key=templated.dedupe_key)] if proposal else []


def run_pipeline(
    team: Team,
    run: EvalSuggestionRun,
    *,
    include_paid: bool,
    settings: SuggestionSettings,
    now: datetime | None = None,
) -> list[EvalSuggestion]:
    """Run every stage for one team and publish the result on `run`. Raises when a free stage fails, so
    the caller can mark the run failed and the team keeps its previous suggestions."""
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
    profile = fetch_profile(team, window)
    if profile.generations == 0:
        stages.set("profile", "skipped", detail="no generations in the last 7 days")
        return publish(run, ranking.pick(dedupe(fixes, coverage, {}, {})), stages.record)
    sample = fetch_sample(team, window, profile)
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

    measurements = measure(applicability.checks, sample)
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
    model = judge_model(team)
    gap_proposals = [
        (gap, ranking.gap_proposal(gap, sample, profile, judge_model=model, similar_evaluation_id=None)) for gap in gaps
    ]

    screened: list[ranking.ScreeningResult] = []
    jeeves_matches: dict[str, tuple[coverage_stage.ExistingEval, float]] = {}
    candidate_options = (
        {ranking.check_dedupe_key(m.check.key): m.check.description for m in measurements}
        | {ranking.judge_dedupe_key(key): catalog.template(key).description for key in applicability.screened_judges}
        | {proposal.dedupe_key: proposal.draft["description"] for _, proposal in gap_proposals}
    )
    if not include_paid or not settings.jeeves:
        stages.set("screening", "skipped", detail="free stages only" if not include_paid else "switched off")
    elif not screening.consented(team):
        stages.set("screening", "skipped", detail="AI data processing not approved")
    else:
        try:
            client = screening.build_client(team)
            unmapped = sorted(
                (e for e in coverage.evals if e.enabled and e.template_key is None and e.dedupe_key is None),
                key=lambda e: e.updated_at,
                reverse=True,
            )[:MAX_DEDUPED_EVALS]
            jeeves_matches = screening.dedupe(client, unmapped, candidate_options) if unmapped else {}
            screened = screening.screen(client, applicability.screened_judges, sample.main)
            stages.set(
                "screening",
                "ok",
                flagged={r.template_key: len(r.flagged) for r in screened},
                dedupe_matches=len(jeeves_matches),
            )
        except SystemOneNotConfigured:
            stages.set("screening", "skipped", detail="System One is not configured")
        except SystemOneRequestFailed as error:
            stages.set("screening", "failed", detail=str(error))

    proposals: list[Proposal] = list(fixes)
    proposals += [
        p for m in measurements if (p := ranking.code_check_proposal(m, sample, profile, similar_evaluation_id=None))
    ]
    proposals += [proposal for _, proposal in gap_proposals]
    proposals += [
        p
        for result in screened
        if (
            p := ranking.screened_proposal(
                result,
                profile,
                sample,
                target=applicability.judge_target,
                judge_model=model,
                similar_evaluation_id=None,
            )
        )
    ]

    if not include_paid or not settings.llm_drafting:
        stages.set("drafting", "skipped", detail="free stages only" if not include_paid else "switched off")
    elif not screening.consented(team):
        stages.set("drafting", "skipped", detail="AI data processing not approved")
    else:
        # Paying for a draft of a finding the team dismissed or already covers would be wasted.
        draftable = [(gap, p) for gap, p in gap_proposals if dedupe([p], coverage, jeeves_matches, {})]
        try:
            proposals += _drafted_proposals(team, run, draftable, sample, profile, settings, stages)
        except Exception as error:
            logger.warning("eval_suggestions_drafting_failed", team_id=team.pk, error=str(error))
            stages.set("drafting", "failed", detail=type(error).__name__)

    sources = {m.check.key: m.check.source for m in measurements}
    # A drafted judge comes after the templated one for the same gap and shares its dedupe key, so it replaces it.
    best = {proposal.dedupe_key: proposal for proposal in dedupe(proposals, coverage, jeeves_matches, sources)}
    picked = ranking.pick(list(best.values()))
    stages.set(
        "ranking", "ok", candidates=len(proposals), after_dedupe=len(best), picked=[p.dedupe_key for p in picked]
    )
    return publish(run, picked, stages.record)


def publish(run: EvalSuggestionRun, proposals: Sequence[Proposal], stages: dict[str, Any]) -> list[EvalSuggestion]:
    """Write the run's suggestions and complete it in one transaction, so the API never reads half a set.

    Two attempts of one run can both get here when Temporal retries an attempt that is still running.
    The first to lock the run publishes, and the other returns what it published.
    """
    with transaction.atomic():
        locked = EvalSuggestionRun.objects.unscoped().select_for_update().get(id=run.id)
        if locked.status == EvalSuggestionRunStatus.COMPLETED:
            return list(EvalSuggestion.objects.for_team(run.team_id).filter(run=run))
        rows = EvalSuggestion.objects.for_team(run.team_id).bulk_create(
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
            ]
        )
        EvalSuggestion.objects.for_team(run.team_id).filter(status=EvalSuggestionStatus.PROPOSED).exclude(
            run=run
        ).update(status=EvalSuggestionStatus.EXPIRED, updated_at=timezone.now())
        # cost_usd stays out of this save, because drafting updates it on the row and the value held here is stale.
        run.status = EvalSuggestionRunStatus.COMPLETED
        run.stages = stages
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "stages", "completed_at"])
    return rows


def create_run(team: Team, trigger: str, batch_id: str = "", run_id: str | None = None) -> EvalSuggestionRun:
    """A new run, or with `run_id` the run a retried start already created, so a retry never leaves one orphaned."""
    runs = EvalSuggestionRun.objects.for_team(team.pk)
    if run_id is None:
        return runs.create(team=team, trigger=trigger, batch_id=batch_id)
    run, _ = runs.get_or_create(id=run_id, defaults={"team": team, "trigger": trigger, "batch_id": batch_id})
    return run


def fail_run(run_id: str, error: str) -> None:
    """Mark a run failed when its attempts ran out outside the process, unless an attempt already published."""
    EvalSuggestionRun.objects.unscoped().filter(id=run_id).exclude(status=EvalSuggestionRunStatus.COMPLETED).update(
        status=EvalSuggestionRunStatus.FAILED, error=error[:2000], completed_at=timezone.now()
    )


def execute_run(run_id: str, *, include_paid: bool, settings: SuggestionSettings) -> int:
    """Run the pipeline for a stored run. A failure marks the run failed and re-raises, and the team keeps
    showing the suggestions of its last completed run."""
    run = EvalSuggestionRun.objects.unscoped().select_related("team").get(id=run_id)
    if run.status == EvalSuggestionRunStatus.COMPLETED:
        # Temporal retries an attempt whose result it lost after the run had published.
        return EvalSuggestion.objects.for_team(run.team_id).filter(run=run).count()
    try:
        return len(run_pipeline(run.team, run, include_paid=include_paid, settings=settings))
    except Exception as error:
        # An attempt that fails after another attempt published must not hide that attempt's suggestions.
        EvalSuggestionRun.objects.unscoped().filter(id=run.id).exclude(status=EvalSuggestionRunStatus.COMPLETED).update(
            status=EvalSuggestionRunStatus.FAILED,
            error=f"{type(error).__name__}: {error}"[:2000],
            completed_at=timezone.now(),
        )
        raise
