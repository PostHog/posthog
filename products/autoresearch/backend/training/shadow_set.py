"""The shadow set: the models of a pipeline that are worth scoring side by side.

The set is computed from the model rows, never stored. Realized results can only compare
models that score the same people on the same days, so a challenger needs a fitted
``model.pkl`` before it can enter.
"""

from collections.abc import Iterable
from datetime import datetime, timedelta
from uuid import UUID

from django.db.models import F
from django.utils import timezone as django_timezone

from products.autoresearch.backend.inference.failures import models_failing_repeatably_in_shadow
from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline

SHADOW_CHALLENGER_LIMIT = 3
# A challenger stays in the set until this many prediction dates have matured past its
# horizon, so a long-horizon model collects realized evidence before a newer one displaces it.
SHADOW_MIN_MATURED_DATES = 7
# Set in a model's metrics when its model.pkl is fitted. A challenger without it has no
# artifact that scoring could load.
FITTED_METRIC_KEY = "model_fitted"
# Set in an archived champion's metrics when promotion replaced it because it could not score.
ARCHIVED_REASON_METRIC_KEY = "archived_reason"
ARCHIVED_UNSCORABLE = "unscorable"


def shadow_set(
    pipeline: AutoresearchPipeline, *, now: datetime | None = None, pending_fit: UUID | None = None
) -> list[AutoresearchModel]:
    """
    Return the champion, the previous champion, and up to ``SHADOW_CHALLENGER_LIMIT``
    challengers, newest first. No two members share a ``recipe_hash``.

    Only a bundle-backed model with a fitted ``model.pkl`` qualifies as a challenger. A model
    that cannot score (archived as unscorable, or a streak of repeatable failures) is skipped,
    and the next eligible model takes its place.
    ``pending_fit`` names a challenger whose fit is not scheduled yet, so completion can ask
    whether the fit would put it in the set.
    """
    now = now or django_timezone.now()
    models = AutoresearchModel.objects.for_team(pipeline.team_id).filter(pipeline=pipeline)

    members: list[AutoresearchModel] = []
    champion = models.filter(role=AutoresearchModel.Role.CHAMPION).first()
    if champion is not None:
        members.append(champion)
    former_champions = [
        model
        for model in models.filter(role=AutoresearchModel.Role.ARCHIVED, promoted_at__isnull=False)
        .exclude(artifact_prefix="")
        .order_by(F("archived_at").desc(nulls_last=True), "-promoted_at")
        if (model.metrics or {}).get(ARCHIVED_REASON_METRIC_KEY) != ARCHIVED_UNSCORABLE
    ]
    challengers = [
        model
        for model in models.filter(role=AutoresearchModel.Role.CHALLENGER)
        .exclude(artifact_prefix="")
        .order_by("-created_at")
        if model.pk == pending_fit or (model.metrics or {}).get(FITTED_METRIC_KEY)
    ]
    unscorable = models_failing_repeatably_in_shadow(pipeline, (m.pk for m in [*former_champions, *challengers]))

    previous = next((model for model in former_champions if model.pk not in unscorable), None)
    if previous is not None and previous.recipe_hash not in {m.recipe_hash for m in members}:
        members.append(previous)

    challengers = [model for model in challengers if model.pk not in unscorable]
    members.extend(_select_challengers(challengers, pipeline=pipeline, now=now, taken={m.recipe_hash for m in members}))
    return members


def _select_challengers(
    newest_first: list[AutoresearchModel], *, pipeline: AutoresearchPipeline, now: datetime, taken: set[str]
) -> list[AutoresearchModel]:
    """
    A challenger younger than its minimum shadow age keeps its place, so these fill the set
    first, in the order they entered. Older challengers fill what is left, newest first, so a
    new challenger displaces a matured one.
    """
    entry_cutoff = now - timedelta(days=pipeline.horizon_days + SHADOW_MIN_MATURED_DATES)
    protected = [model for model in reversed(newest_first) if model.created_at > entry_cutoff]
    matured = [model for model in newest_first if model.created_at <= entry_cutoff]

    chosen: list[AutoresearchModel] = []
    seen = set(taken)
    for model in [*protected, *matured]:
        if len(chosen) == SHADOW_CHALLENGER_LIMIT:
            break
        if model.recipe_hash in seen:
            continue
        seen.add(model.recipe_hash)
        chosen.append(model)
    return sorted(chosen, key=lambda model: model.created_at, reverse=True)


def shadow_set_ids(team_id: int, pipeline_ids: Iterable[UUID]) -> set[UUID]:
    pipelines = AutoresearchPipeline.objects.for_team(team_id).filter(pk__in=set(pipeline_ids))
    return {model.pk for pipeline in pipelines for model in shadow_set(pipeline)}
