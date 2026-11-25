from collections.abc import Mapping, Sequence
from math import fsum
from typing import Any
from uuid import UUID

from products.ai_observability.backend.composite_formula import CompositeFormula, CompositeFormulaError, FormulaValue
from products.ai_observability.backend.models.score_definitions import ScoreDefinitionVersion
from products.ai_observability.backend.offline_evaluation_read_types import (
    ExperimentScore,
    ExperimentScoreInput,
    ExperimentScoreSource,
    OfflineScorerSummary,
)
from products.ai_observability.backend.score_validation import validate_score_value


def _statistic(summary: OfflineScorerSummary, statistic: str, category: str | None) -> tuple[bool, float | None]:
    match statistic:
        case "category_rate":
            for option in summary.categories:
                if option.key == category:
                    return True, option.rate
            return False, None
        case "mean":
            return summary.scorer.kind == "numeric", summary.mean
        case "true_rate":
            return summary.scorer.kind == "boolean", summary.true_rate
        case "pass_rate":
            return summary.pass_count is not None, summary.pass_rate
        case _:
            return False, None


def _resolve_input(
    spec: dict[str, Any], summaries: Sequence[OfflineScorerSummary], overlap: bool
) -> ExperimentScoreInput:
    policy = spec.get("version_policy", "run")
    matched = [row for row in summaries if policy != "exact" or str(row.scorer.id) == spec["scorer_version_id"]]
    sources = []
    available = True
    for row in sorted(matched, key=lambda summary: summary.scorer.version):
        supported, value = _statistic(row, spec["statistic"], spec.get("category"))
        available &= supported
        sources.append(
            ExperimentScoreSource(
                version_id=row.scorer.id, version=row.scorer.version, successful_items=row.status_counts.ok, value=value
            )
        )
    count = sum(source.successful_items for source in sources)
    value = None
    if not matched:
        status = "missing_input"
    elif policy == "run" and len(matched) > 1:
        status = "mixed_versions"
    elif policy == "combine" and overlap:
        status = "overlapping_items"
    elif not available:
        status = "unavailable_statistic"
    elif not count:
        status = "no_successful_items"
    else:
        status = "ok"
        value = fsum(source.value * (source.successful_items / count) for source in sources if source.value is not None)
    return ExperimentScoreInput(
        alias=spec["alias"],
        statistic=spec["statistic"],
        version_policy=policy,
        status=status,
        value=value,
        sources=sources,
    )


def calculate_experiment_score(
    version: ScoreDefinitionVersion,
    definitions_by_anchor: Mapping[str, UUID],
    summaries: Mapping[UUID, Sequence[OfflineScorerSummary]],
    overlaps: set[UUID],
    *,
    complete: bool,
) -> ExperimentScore:
    composition = version.composition
    assert composition is not None
    inputs = []
    value = None
    status = "pending"
    if complete:
        for spec in composition["inputs"]:
            definition_id = definitions_by_anchor[spec["scorer_version_id"]]
            inputs.append(_resolve_input(spec, summaries.get(definition_id, []), definition_id in overlaps))
        status = next((entry.status for entry in inputs if entry.status != "ok"), "ok")
        if status == "ok":
            try:
                formula = CompositeFormula.parse(
                    composition["expression"], {entry.alias: "numeric" for entry in inputs}, version.definition.kind
                )
                values: dict[str, FormulaValue] = {
                    entry.alias: entry.value for entry in inputs if entry.value is not None
                }
                computed = formula.evaluate(values)
                if isinstance(computed, str):
                    computed = [computed]
                errors = validate_score_value(
                    version.definition.kind,
                    version.config,
                    numeric_value=computed if isinstance(computed, float) else None,
                    boolean_value=computed if isinstance(computed, bool) else None,
                    categorical_values=computed if isinstance(computed, list) else None,
                )
                if errors:
                    status = "formula_error"
                else:
                    value = computed
            except CompositeFormulaError:
                status = "formula_error"
    return ExperimentScore(
        definition_id=version.definition_id,
        kind=version.definition.kind,
        config=version.config,
        scorer_version_id=version.id,
        version=version.version,
        name=version.definition.name,
        status=status,
        value=value,
        inputs=inputs,
    )
