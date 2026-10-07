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

from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline

SHADOW_CHALLENGER_LIMIT = 3
# A challenger stays in the set until this many prediction dates have matured past its
# horizon, so a long-horizon model collects realized evidence before a newer one displaces it.
SHADOW_MIN_MATURED_DATES = 7
# Set in a model's metrics when its model.pkl is fitted. A challenger without it has no
# artifact that scoring could load.
FITTED_METRIC_KEY = "model_fitted"


def shadow_set(
    pipeline: AutoresearchPipeline, *, now: datetime | None = None, pending_fit: UUID | None = None
) -> list[AutoresearchModel]:
    """
    Return the champion, the previous champion, and up to ``SHADOW_CHALLENGER_LIMIT``
    challengers, newest first. No two members share a ``recipe_hash``.

    Only a bundle-backed model with a fitted ``model.pkl`` qualifies as a challenger.
    ``pending_fit`` names a challenger whose fit is not scheduled yet, so completion can ask
    whether the fit would put it in the set.
    """
    now = now or django_timezone.now()
    models = AutoresearchModel.objects.for_team(pipeline.team_id).filter(pipeline=pipeline)

    members: list[AutoresearchModel] = []
    champion = models.filter(role=AutoresearchModel.Role.CHAMPION).first()
    if champion is not None:
        members.append(champion)
    previous = (
        models.filter(role=AutoresearchModel.Role.ARCHIVED, promoted_at__isnull=False)
        .exclude(artifact_prefix="")
        .order_by(F("archived_at").desc(nulls_last=True), "-promoted_at")
        .first()
    )
    if previous is not None and previous.recipe_hash not in {m.recipe_hash for m in members}:
        members.append(previous)

    challengers = [
        model
        for model in models.filter(role=AutoresearchModel.Role.CHALLENGER)
        .exclude(artifact_prefix="")
        .order_by("-created_at")
        if model.pk == pending_fit or (model.metrics or {}).get(FITTED_METRIC_KEY)
    ]
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
