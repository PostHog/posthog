"""The suggestions a project's page reads: the latest run's open cards, and only those a user may see."""

import uuid
from datetime import timedelta

from django.db.models import F, Q, QuerySet
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.models.team import Team

from products.access_control.backend.facade.api import (
    get_restricted_properties_with_group_type_index_for_team,
    split_restricted_property_names,
)
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.ai_observability.backend.models.eval_suggestions import (
    EvalSuggestion,
    EvalSuggestionKind,
    EvalSuggestionRun,
    EvalSuggestionRunStatus,
    EvalSuggestionStatus,
)
from products.ai_observability.backend.models.evaluations import Evaluation

from .config import is_enabled_for_organization
from .eligibility import (
    StartRun,
    TemporalUnreachable,
    claim_first_visit_run,
    queue_first_visit_run,
    record_visit,
    release_first_visit_run,
)

logger = structlog.get_logger(__name__)

# A fix whose evaluation changed after the run read it, or that is gone, no longer applies. Saving the evaluation
# by hand is how a person acts on a fix with no patch, so the card leaves the list once they do.
STALE_FIX = Q(kind=EvalSuggestionKind.FIX_EVAL) & (
    Q(target_evaluation__isnull=True)
    | Q(target_evaluation__deleted=True)
    | Q(target_evaluation__updated_at__gt=F("run__created_at"))
)


@frozen
class LatestSuggestions:
    run: EvalSuggestionRun | None
    pending: bool
    suggestions: list[EvalSuggestion]


def applies(suggestion: EvalSuggestion) -> bool:
    if suggestion.kind != EvalSuggestionKind.FIX_EVAL:
        return True
    target = suggestion.target_evaluation
    # The same rule as STALE_FIX, which hides these from the list.
    return target is not None and not target.deleted and target.updated_at <= suggestion.run.created_at


def visible_suggestions(team: Team, access: UserAccessControl | None) -> QuerySet[EvalSuggestion]:
    """The team's suggestions, without those that name an evaluation the user cannot read.

    `access` is None for service credentials, which see every suggestion of an organization in the rollout.
    """
    team_id = team.pk
    suggestions = EvalSuggestion.objects.for_team(team_id)
    # A shadow organization's runs publish cards that staff review, and nobody in the organization reads them.
    if not is_enabled_for_organization(str(team.organization_id)):
        return suggestions.none()
    if access is None:
        return suggestions
    # Runs read every event property as the project, and a card's filters, headline and evidence can carry
    # any of them, so a member with a hidden event property sees no suggestions rather than a masked one.
    restrictions = get_restricted_properties_with_group_type_index_for_team(user=access.user, team_id=team_id)
    if split_restricted_property_names(restrictions).event:
        return suggestions.none()
    visible = access.filter_queryset_by_access_level(Evaluation.objects.filter(team_id=team_id)).values("id")
    return suggestions.filter(
        Q(target_evaluation__isnull=True) | Q(target_evaluation_id__in=visible),
        Q(similar_evaluation__isnull=True) | Q(similar_evaluation_id__in=visible),
        Q(created_evaluation__isnull=True) | Q(created_evaluation_id__in=visible),
    )


def find_suggestion(team: Team, access: UserAccessControl | None, suggestion_id: uuid.UUID) -> EvalSuggestion | None:
    return (
        visible_suggestions(team, access)
        .select_related("run", "target_evaluation", "similar_evaluation")
        .filter(id=suggestion_id)
        .first()
    )


def latest_suggestions(
    team: Team, access: UserAccessControl | None, *, start_run: StartRun, pending_window: timedelta
) -> LatestSuggestions:
    """The latest suggestions. Loading them records the visit, and the first visit starts a run.

    A running run counts as pending for `pending_window`, the longest its workflow can take.
    """
    if not is_enabled_for_organization(str(team.organization_id)):
        return LatestSuggestions(run=None, pending=False, suggestions=[])
    record_visit(team)
    runs = EvalSuggestionRun.objects.for_team(team.pk)
    latest = runs.filter(status=EvalSuggestionRunStatus.COMPLETED).order_by("-completed_at").first()
    pending = runs.filter(
        status=EvalSuggestionRunStatus.RUNNING, created_at__gte=timezone.now() - pending_window
    ).exists()
    if latest is None and not pending and claim_first_visit_run(team):
        try:
            queue_first_visit_run(team, start_run)
            pending = True
        except TemporalUnreachable:
            release_first_visit_run(team)
            logger.warning("llma.eval_suggestions_first_visit_temporal_unreachable", team_id=team.pk)
        except Exception:
            # The list still answers. The claim holds for the day, so the next day's visit tries again.
            logger.exception("llma.eval_suggestions_first_visit_start_failed", team_id=team.pk)
    results = (
        visible_suggestions(team, access)
        .filter(run=latest, status=EvalSuggestionStatus.PROPOSED)
        .exclude(STALE_FIX)
        .select_related("run", "target_evaluation", "similar_evaluation")
        .order_by("-score")
        if latest
        else EvalSuggestion.objects.unscoped().none()
    )
    return LatestSuggestions(run=latest, pending=pending, suggestions=list(results))
