"""Storing a run: its row, the handoff between stages, its spend, and the suggestions it publishes."""

from collections.abc import Sequence
from dataclasses import field, replace
from typing import Any

from django.db import connection, transaction
from django.db.models import F, Sum
from django.utils import timezone

from pydantic import TypeAdapter

from posthog.dataclasses import frozen
from posthog.models.team import Team

from products.ai_observability.backend.logic.eval_suggestions.profile_queries import ProfileWindow
from products.ai_observability.backend.models.eval_suggestions import (
    EvalSuggestion,
    EvalSuggestionRun,
    EvalSuggestionRunStatus,
    EvalSuggestionStatus,
)

from .coverage import dismissed_dedupe_keys
from .measure import SampleRef
from .profile import StructuredGap, TeamProfile
from .ranking import Proposal

STAGE_ORDER = ("measure", "screening", "drafting")


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


def get_run(team_id: int, run_id: str) -> EvalSuggestionRun:
    return EvalSuggestionRun.objects.for_team(team_id).select_related("team").get(id=run_id)


def running_run(team_id: int, run_id: str) -> EvalSuggestionRun | None:
    """The run while it still works. A run another attempt published or gave up on is left alone."""
    run = get_run(team_id, run_id)
    return run if run.status == EvalSuggestionRunStatus.RUNNING else None


def load_handoff(run: EvalSuggestionRun) -> Handoff:
    return _HANDOFF.validate_python(run.handoff)


def save_handoff(run: EvalSuggestionRun, handoff: Handoff, stages: dict[str, dict[str, Any]], stage: str) -> None:
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
        locked.stages = {**locked.stages, **stages}
        locked.save(update_fields=["handoff", "stages"])


def reserve_spend(run: EvalSuggestionRun, amount: float, budget: float) -> bool:
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


def settle_spend(run: EvalSuggestionRun, reserved: float, cost_usd: float) -> None:
    """Replace a reservation with the cost the call reported."""
    EvalSuggestionRun.objects.for_team(run.team_id).filter(id=run.id).update(
        cost_usd=F("cost_usd") - reserved + cost_usd
    )


def published_count(run: EvalSuggestionRun) -> int:
    return EvalSuggestion.objects.for_team(run.team_id).filter(run=run).count()


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
