"""Accepting a suggestion: create the evaluation from its draft, enabled, then run it on recent data.

The run is an ordinary backfill over a window shrunk with the backfill estimate, so it evaluates at most
500 units for a Hog check and 50 for a judge, which runs on the team's own provider key.
"""

import time
import uuid
from datetime import datetime, timedelta
from typing import Any, cast

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

import structlog
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request

from posthog.dataclasses import frozen
from posthog.exceptions import Conflict
from posthog.models.team import Team
from posthog.models.user import User

from products.ai_observability.backend.api.evaluation_backfills import (
    BackfillWindow,
    clamp_backfill_window,
    start_backfill,
)
from products.ai_observability.backend.api.evaluations import EvaluationSerializer, create_evaluation, update_evaluation
from products.ai_observability.backend.backfill_candidates import count_backfill_candidates
from products.ai_observability.backend.llm import DEFAULT_MODEL_BY_PROVIDER
from products.ai_observability.backend.logic.eval_suggestions.ranking import judge_input_price
from products.ai_observability.backend.logic.evaluations.settle import settle_horizon
from products.ai_observability.backend.models.eval_suggestions import (
    EvalSuggestion,
    EvalSuggestionKind,
    EvalSuggestionStatus,
)
from products.ai_observability.backend.models.evaluation_backfill import EvaluationBackfill
from products.ai_observability.backend.models.evaluation_config import EvaluationConfig
from products.ai_observability.backend.models.evaluations import Evaluation
from products.ai_observability.backend.models.provider_keys import LLMProviderKey

logger = structlog.get_logger(__name__)

CODE_CHECK_BACKFILL_UNITS = 500
JUDGE_BACKFILL_UNITS = 50
BACKFILL_LOOKBACK = timedelta(days=7)
# Each shrink assumes units arrive evenly, so it aims a little under the cap to absorb bursts.
SHRINK_MARGIN = 0.9
MAX_SHRINKS = 4
# The estimate and accept requests wait for every count, so shrinking stops once they have waited this long.
PLAN_BUDGET_SECONDS = 10

NO_KEY_MESSAGE = (
    "LLM judges run on your own AI provider API key, and this project doesn't have a working one yet. "
    "A project admin can add one in Settings > AI observability > Bring your own key (BYOK), then add this evaluation."
)
CLOSED_MESSAGE = "This suggestion is no longer open. Refresh the page to see the current suggestions."
TARGET_CHANGED_MESSAGE = (
    "This evaluation changed after the suggestion was made, and applying the fix would undo those changes. "
    "Open the evaluation to update its filters."
)


@frozen
class BackfillPlan:
    window: BackfillWindow
    units: int


@frozen
class AcceptEstimate:
    target: str
    units: int
    window_start: datetime | None
    window_end: datetime | None
    judge_model: str | None
    estimated_cost_usd: float | None


@frozen
class AcceptResult:
    suggestion: EvalSuggestion
    evaluation: Evaluation
    backfill: EvaluationBackfill | None


def unit_cap(suggestion: EvalSuggestion) -> int:
    return CODE_CHECK_BACKFILL_UNITS if suggestion.kind == EvalSuggestionKind.NEW_HOG else JUDGE_BACKFILL_UNITS


def conditions_for(suggestion: EvalSuggestion) -> list[dict[str, Any]]:
    return [
        {"id": str(uuid.uuid4()), "rollout_percentage": suggestion.rollout_percentage, "properties": suggestion.filters}
    ]


def plan_backfill(
    team: Team,
    *,
    evaluation_id: str,
    target: str,
    target_config: dict[str, Any],
    conditions: list[dict[str, Any]],
    cap: int,
) -> BackfillPlan | None:
    """The most recent window that holds at most `cap` units, or None when recent data holds none.

    Shrinking assumes even traffic, so a burst can leave a shrunk window empty or still too full. Then the last
    window with traffic runs, and the backfill's `max_units` stops it at `cap`. The same holds when the counts
    use up `PLAN_BUDGET_SECONDS`.
    """
    now = timezone.now()
    window = clamp_backfill_window(team, target, target_config, now - BACKFILL_LOOKBACK, now)
    last_with_traffic: BackfillWindow | None = None
    started = time.monotonic()
    for _ in range(MAX_SHRINKS):
        if last_with_traffic and time.monotonic() - started > PLAN_BUDGET_SECONDS:
            break
        scope = count_backfill_candidates(
            team=team,
            evaluation_id=evaluation_id,
            target=target,
            settle_horizon=settle_horizon(target, target_config),
            conditions=conditions,
            window_start=window.start,
            window_end=window.end,
            rerun_existing=True,
        )
        if scope.to_evaluate == 0:
            return BackfillPlan(window=last_with_traffic, units=cap) if last_with_traffic else None
        if scope.to_evaluate <= cap:
            return BackfillPlan(window=window, units=scope.to_evaluate)
        last_with_traffic = window
        span = (window.end - window.start) * cap / scope.to_evaluate * SHRINK_MARGIN
        window = BackfillWindow(start=window.end - span, end=window.end)
    return BackfillPlan(window=last_with_traffic, units=cap) if last_with_traffic else None


def judge_model_configuration(team: Team) -> dict[str, Any]:
    """The team's active key with its provider's default model. Raises when the team has no working key."""
    config = EvaluationConfig.objects.filter(team_id=team.pk).select_related("active_provider_key").first()
    key = config.active_provider_key if config else None
    if key is None or key.state != LLMProviderKey.State.OK or key.provider not in DEFAULT_MODEL_BY_PROVIDER:
        raise ValidationError(NO_KEY_MESSAGE)
    return {"provider": key.provider, "model": DEFAULT_MODEL_BY_PROVIDER[key.provider], "provider_key_id": str(key.id)}


def estimate(suggestion: EvalSuggestion, team: Team) -> AcceptEstimate:
    target = str(suggestion.draft.get("target", "generation"))
    target_config = suggestion.draft.get("target_config") or {}
    plan = plan_backfill(
        team,
        evaluation_id=str(uuid.uuid4()),
        target=target,
        target_config=target_config,
        conditions=conditions_for(suggestion),
        cap=unit_cap(suggestion),
    )
    units = plan.units if plan else 0
    model = None
    cost: float | None = 0.0
    if suggestion.draft.get("evaluation_type") == "llm_judge":
        # The same key and model accept uses. Without a working key, accept refuses, so nothing is priced.
        try:
            model = judge_model_configuration(team)["model"]
        except ValidationError:
            model = None
        # The suggestion stores the tokens one run reads, a whole transcript for trace and session judges.
        price = judge_input_price(model) if model else None
        cost = units * suggestion.mean_input_tokens * price if price and suggestion.mean_input_tokens else None
    return AcceptEstimate(
        target=target,
        units=units,
        window_start=plan.window.start if plan else None,
        window_end=plan.window.end if plan else None,
        judge_model=model,
        estimated_cost_usd=cost,
    )


def _start_recent_backfill(team: Team, evaluation: Evaluation, cap: int, user: User) -> EvaluationBackfill | None:
    conditions = [
        {"properties": condition.get("properties", []), "rollout_percentage": condition.get("rollout_percentage", 100)}
        for condition in evaluation.conditions
    ]
    try:
        plan = plan_backfill(
            team,
            evaluation_id=str(evaluation.id),
            target=evaluation.target,
            target_config=evaluation.target_config,
            conditions=conditions,
            cap=cap,
        )
        if plan is None:
            return None
        return start_backfill(
            team=team,
            evaluation=evaluation,
            window=plan.window,
            conditions=conditions,
            rerun_existing=False,
            total_count=plan.units,
            max_units=plan.units,
            user=user,
        )
    except Exception:
        # The evaluation exists and runs on new traffic either way, so a backfill that cannot start, for any
        # reason, costs the user the preview, not the evaluation.
        logger.warning("llma.eval_suggestion_backfill_not_started", evaluation_id=str(evaluation.id), exc_info=True)
        return None


def accept(suggestion_id: str, *, team: Team, request: Request, serializer_context: dict[str, Any]) -> AcceptResult:
    """Create the evaluation once. A second accept returns the evaluation the first one created."""
    user = cast(User, request.user)
    with transaction.atomic():
        suggestion = EvalSuggestion.objects.for_team(team.pk).select_for_update().get(id=suggestion_id)
        if suggestion.kind == EvalSuggestionKind.FIX_EVAL:
            raise ValidationError("Use apply_fix for a suggestion that fixes an existing evaluation.")
        created = suggestion.created_evaluation
        if suggestion.status == EvalSuggestionStatus.ACCEPTED and created is not None and not created.deleted:
            backfill = (
                EvaluationBackfill.objects.for_team(team.pk).filter(evaluation=created).order_by("-created_at").first()
            )
            return AcceptResult(suggestion=suggestion, evaluation=created, backfill=backfill)
        # An accepted suggestion whose evaluation was deleted stays closed, so a stale tab cannot bring it back.
        if suggestion.status != EvalSuggestionStatus.PROPOSED:
            raise ValidationError(CLOSED_MESSAGE)

        data: dict[str, Any] = {**suggestion.draft, "enabled": True, "conditions": conditions_for(suggestion)}
        if data.get("evaluation_type") == "llm_judge":
            data["model_configuration"] = judge_model_configuration(team)
        serializer = EvaluationSerializer(data=data, context=serializer_context)
        serializer.is_valid(raise_exception=True)
        evaluation = create_evaluation(
            serializer,
            request=request,
            team=team,
            tracking_properties={
                "suggestion_id": str(suggestion.id),
                "suggestion_template_key": suggestion.template_key,
            },
        )
        suggestion.status = EvalSuggestionStatus.ACCEPTED
        suggestion.created_evaluation = evaluation
        suggestion.decided_at = timezone.now()
        suggestion.save(update_fields=["status", "created_evaluation", "decided_at", "updated_at"])
    # Outside the transaction: the walk reads the evaluation row, and a failed start must not undo the accept.
    backfill = _start_recent_backfill(team, evaluation, unit_cap(suggestion), user)
    return AcceptResult(suggestion=suggestion, evaluation=evaluation, backfill=backfill)


def dismiss(suggestion_id: str, *, reason: str | None, visible: QuerySet[EvalSuggestion]) -> EvalSuggestion:
    """`visible` is the caller's view of the team's suggestions; replacements outside it stay proposed."""
    with transaction.atomic():
        suggestion = visible.select_for_update().get(id=suggestion_id)
        if suggestion.status == EvalSuggestionStatus.ACCEPTED:
            raise ValidationError("This suggestion was already added. Disable the evaluation instead.")
        now = timezone.now()
        suggestion.status = EvalSuggestionStatus.DISMISSED
        suggestion.dismiss_reason = reason
        suggestion.decided_at = now
        suggestion.save(update_fields=["status", "dismiss_reason", "decided_at", "updated_at"])
        # A run can publish a replacement for this card while the lock above waits, so it goes too.
        visible.filter(dedupe_key=suggestion.dedupe_key, status=EvalSuggestionStatus.PROPOSED).update(
            status=EvalSuggestionStatus.DISMISSED, dismiss_reason=reason, decided_at=now, updated_at=now
        )
    return suggestion


def apply_fix(suggestion_id: str, *, team: Team, serializer_context: dict[str, Any]) -> EvalSuggestion:
    with transaction.atomic():
        suggestion = EvalSuggestion.objects.for_team(team.pk).select_for_update().get(id=suggestion_id)
        if suggestion.kind != EvalSuggestionKind.FIX_EVAL:
            raise ValidationError("Only a suggestion that fixes an existing evaluation can be applied.")
        if suggestion.status == EvalSuggestionStatus.ACCEPTED:
            return suggestion
        if suggestion.status != EvalSuggestionStatus.PROPOSED:
            raise ValidationError(CLOSED_MESSAGE)
        target_id = suggestion.target_evaluation_id
        target = (
            Evaluation.objects.select_for_update().filter(team_id=team.pk, id=target_id, deleted=False).first()
            if target_id is not None
            else None
        )
        if target is None:
            raise ValidationError("The evaluation this suggestion fixes no longer exists.")
        if not suggestion.draft:
            raise ValidationError("This evaluation needs a manual fix. Open it to change its filters.")
        # The draft holds the evaluation's whole condition list as the run read it, so applying it after any
        # later edit would put back the filters or rollout that edit replaced.
        if target.updated_at > suggestion.run.created_at:
            raise Conflict(TARGET_CHANGED_MESSAGE)
        serializer = EvaluationSerializer(target, data=suggestion.draft, partial=True, context=serializer_context)
        serializer.is_valid(raise_exception=True)
        update_evaluation(
            serializer,
            request=serializer_context["request"],
            team=team,
            tracking_properties={"suggestion_id": str(suggestion.id)},
        )
        suggestion.status = EvalSuggestionStatus.ACCEPTED
        suggestion.decided_at = timezone.now()
        suggestion.save(update_fields=["status", "decided_at", "updated_at"])
    return suggestion
