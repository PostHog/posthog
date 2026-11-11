from collections.abc import Sequence

from products.ai_observability.backend.models.evaluation_configs import CategoricalOutputConfig, NumericOutputConfig
from products.ai_observability.backend.models.evaluation_outcomes import get_outcome_definition
from products.ai_observability.backend.models.evaluations import Evaluation, EvaluationStatus

from ...facade import contracts
from .overview import CategoryOption, EvaluationMeta, SummaryKind


def load_evaluation_metas(team_id: int, evaluation_ids: Sequence[str]) -> list[EvaluationMeta]:
    """Newest first. Deleted evaluations and ids outside the team are left out."""
    evaluations = (
        Evaluation.objects.filter(team_id=team_id, id__in=evaluation_ids, deleted=False)
        .select_related("directory", "created_by")
        .order_by("-created_at", "id")
    )
    return [_evaluation_meta(evaluation) for evaluation in evaluations]


def load_evaluation_meta(team_id: int, evaluation_id: str) -> EvaluationMeta:
    return _evaluation_meta(
        Evaluation.objects.select_related("directory", "created_by").get(
            team_id=team_id, id=evaluation_id, deleted=False
        )
    )


def _evaluation_meta(evaluation: Evaluation) -> EvaluationMeta:
    config = evaluation.output_config or {}
    try:
        has_pass_rule = get_outcome_definition(
            evaluation.output_type, true_is_failure=config.get("true_is_failure") is True, output_config=config
        ).has_pass_rule
    except ValueError:
        has_pass_rule = False
    kind: SummaryKind
    if evaluation.output_type == "sentiment":
        kind = "sentiment"
    elif has_pass_rule:
        kind = "pass_rate"
    elif evaluation.output_type == "numeric":
        kind = "score"
    else:
        kind = "categories"
    scale = None
    score_step = None
    categories: tuple[CategoryOption, ...] = ()
    multiple = False
    # A config that no longer validates still shows its counts, without the bounds or labels it would carry.
    try:
        if evaluation.output_type == "numeric":
            numeric = NumericOutputConfig.model_validate(config)
            score_step = numeric.step
            if numeric.min is not None and numeric.max is not None:
                scale = contracts.ScoreScale(min=numeric.min, max=numeric.max)
        elif evaluation.output_type == "categorical":
            categorical = CategoricalOutputConfig.model_validate(config)
            categories = tuple(CategoryOption(key=option.key, label=option.label) for option in categorical.options)
            multiple = categorical.selection_mode == "multiple"
    except ValueError:
        pass
    creator = evaluation.created_by
    return EvaluationMeta(
        id=str(evaluation.id),
        name=evaluation.name,
        directory_name=evaluation.directory.name if evaluation.directory else None,
        evaluation_type=evaluation.evaluation_type,
        output_type=evaluation.output_type,
        enabled=evaluation.enabled,
        errored=evaluation.status == EvaluationStatus.ERROR,
        status_reason=evaluation.status_reason if evaluation.status == EvaluationStatus.ERROR else None,
        created_by=(" ".join(filter(None, [creator.first_name, creator.last_name])) or creator.email)
        if creator
        else None,
        kind=kind,
        scale=scale,
        score_step=score_step,
        categories=categories,
        multiple=multiple,
    )
