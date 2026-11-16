"""The eval suggestion cards the suggestions page reads and acts on.

Apart from `api.py` because accepting a suggestion goes through the evaluations API, which imports `api.py`.
"""

from typing import Any
from uuid import UUID

from posthog.models import Team

from products.access_control.backend.facade.contracts import ObjectAccessRef
from products.access_control.backend.facade.user_access_control import UserAccessControl

from ..logic.eval_suggestions import (
    accept as eval_suggestion_accept,
    suggestions as eval_suggestions,
)
from ..models.eval_suggestions import (
    EvalSuggestion as EvalSuggestionModel,
    EvalSuggestionRun as EvalSuggestionRunModel,
)
from ..temporal.eval_suggestions_client import TEAM_TIMEOUT, start_first_visit_run
from . import contracts


def list_eval_suggestions(team: Team, access: UserAccessControl | None) -> contracts.EvalSuggestionList:
    """`access` is None for service credentials, which see every suggestion."""
    latest = eval_suggestions.latest_suggestions(
        team, access, start_run=start_first_visit_run, pending_window=TEAM_TIMEOUT
    )
    return contracts.EvalSuggestionList(
        run=_to_eval_suggestion_run(latest.run) if latest.run else None,
        pending=latest.pending,
        results=[_to_eval_suggestion(suggestion) for suggestion in latest.suggestions],
    )


def get_eval_suggestion(team: Team, access: UserAccessControl | None, suggestion_id: UUID) -> contracts.EvalSuggestion:
    return _to_eval_suggestion(_find_eval_suggestion(team, access, suggestion_id))


def estimate_eval_suggestion_accept(
    team: Team, access: UserAccessControl | None, suggestion_id: UUID
) -> contracts.EvalSuggestionAcceptEstimate:
    estimate = eval_suggestion_accept.estimate(_find_eval_suggestion(team, access, suggestion_id), team)
    return contracts.EvalSuggestionAcceptEstimate(
        target=estimate.target,
        units=estimate.units,
        window_start=estimate.window_start,
        window_end=estimate.window_end,
        judge_model=estimate.judge_model,
        estimated_cost_usd=estimate.estimated_cost_usd,
    )


def accept_eval_suggestion(
    team: Team, access: UserAccessControl | None, suggestion_id: UUID, serializer_context: dict[str, Any]
) -> contracts.EvalSuggestionAccepted:
    _find_eval_suggestion(team, access, suggestion_id)
    result = eval_suggestion_accept.accept(
        str(suggestion_id), team=team, request=serializer_context["request"], serializer_context=serializer_context
    )
    return contracts.EvalSuggestionAccepted(
        suggestion=_to_eval_suggestion(result.suggestion),
        evaluation_id=result.evaluation.id,
        backfill_id=result.backfill.id if result.backfill else None,
        backfill_units=result.backfill.total_count if result.backfill else None,
        evaluation_access=ObjectAccessRef(
            resource="evaluation",
            id=str(result.evaluation.id),
            team_id=team.pk,
            created_by_id=result.evaluation.created_by_id,
        ),
    )


def dismiss_eval_suggestion(
    team: Team, access: UserAccessControl | None, suggestion_id: UUID, reason: str | None
) -> contracts.EvalSuggestion:
    _find_eval_suggestion(team, access, suggestion_id)
    dismissed = eval_suggestion_accept.dismiss(
        str(suggestion_id), reason=reason, visible=eval_suggestions.visible_suggestions(team, access)
    )
    return _to_eval_suggestion(dismissed)


def eval_suggestion_fix_target(
    team: Team, access: UserAccessControl | None, suggestion_id: UUID
) -> ObjectAccessRef | None:
    """The evaluation a fix_eval suggestion changes, for the caller's object access check."""
    target = _find_eval_suggestion(team, access, suggestion_id).target_evaluation
    if target is None:
        return None
    return ObjectAccessRef(
        resource="evaluation", id=str(target.id), team_id=team.pk, created_by_id=target.created_by_id
    )


def apply_eval_suggestion_fix(
    team: Team, access: UserAccessControl | None, suggestion_id: UUID, serializer_context: dict[str, Any]
) -> contracts.EvalSuggestion:
    suggestion = eval_suggestion_accept.apply_fix(str(suggestion_id), team=team, serializer_context=serializer_context)
    return _to_eval_suggestion(_find_eval_suggestion(team, access, suggestion.id))


def _find_eval_suggestion(team: Team, access: UserAccessControl | None, suggestion_id: UUID) -> EvalSuggestionModel:
    suggestion = eval_suggestions.find_suggestion(team, access, suggestion_id)
    if suggestion is None:
        raise contracts.EvalSuggestionNotFoundError
    return suggestion


def _to_eval_suggestion_run(run: EvalSuggestionRunModel) -> contracts.EvalSuggestionRun:
    return contracts.EvalSuggestionRun(
        id=run.id, trigger=run.trigger, created_at=run.created_at, completed_at=run.completed_at
    )


def _to_eval_suggestion(suggestion: EvalSuggestionModel) -> contracts.EvalSuggestion:
    target = suggestion.target_evaluation
    similar = suggestion.similar_evaluation
    return contracts.EvalSuggestion(
        id=suggestion.id,
        kind=suggestion.kind,
        status=suggestion.status,
        applies=eval_suggestions.applies(suggestion),
        template_key=suggestion.template_key,
        headline=suggestion.headline,
        outcome=suggestion.outcome,
        reason=suggestion.reason,
        draft=suggestion.draft,
        filters=suggestion.filters,
        rollout_percentage=suggestion.rollout_percentage,
        measured_failure_rate=suggestion.measured_failure_rate,
        sample_size=suggestion.sample_size,
        evidence=suggestion.evidence,
        estimated_weekly_runs=suggestion.estimated_weekly_runs,
        estimated_weekly_cost_usd=suggestion.estimated_weekly_cost_usd,
        judge_model=suggestion.judge_model,
        created_evaluation=suggestion.created_evaluation_id,
        target_evaluation=suggestion.target_evaluation_id,
        target_evaluation_name=target.name if target else None,
        similar_evaluation=suggestion.similar_evaluation_id,
        similar_evaluation_name=similar.name if similar else None,
        dismiss_reason=suggestion.dismiss_reason,
        created_at=suggestion.created_at,
    )
