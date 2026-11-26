from collections.abc import Mapping, Sequence
from fractions import Fraction
from typing import Any
from uuid import UUID

from products.ai_observability.backend.composite_formula import CompositeFormula, CompositeFormulaError, FormulaValue
from products.ai_observability.backend.models.evaluation_configs import CategoricalPassingRule, NumericPassingRule
from products.ai_observability.backend.models.score_definitions import ScoreDefinitionVersion
from products.ai_observability.backend.offline_evaluation_read_types import (
    ExperimentScore,
    ExperimentScoreInput,
    ExperimentScoreSource,
    OfflineScorerSummary,
)
from products.ai_observability.backend.score_validation import validate_score_value


def _statistic_total(summary: OfflineScorerSummary, statistic: str, category: str | None) -> int | Fraction | None:
    match statistic:
        case "category_rate":
            for option in summary.categories:
                if option.key == category:
                    return option.count
            return None
        case "mean":
            return Fraction(summary.mean) * summary.status_counts.ok if summary.mean is not None else None
        case "true_rate":
            return summary.true_count
        case "pass_rate":
            return summary.pass_count
        case _:
            return None


def _resolve_input(
    spec: dict[str, Any], summaries: Sequence[OfflineScorerSummary], overlap: bool
) -> ExperimentScoreInput:
    policy = spec.get("version_policy", "run")
    matched = [row for row in summaries if policy != "exact" or str(row.scorer.id) == spec["scorer_version_id"]]
    sources = []
    totals = []
    for row in sorted(matched, key=lambda summary: summary.scorer.version):
        count = row.status_counts.ok
        total = _statistic_total(row, spec["statistic"], spec.get("category")) if count else None
        if total is not None:
            totals.append(total)
        sources.append(
            ExperimentScoreSource(
                version_id=row.scorer.id,
                version=row.scorer.version,
                successful_items=count,
                value=float(total / count) if total is not None else None,
            )
        )
    contributing = [source for source in sources if source.successful_items]
    value = None
    if not matched:
        status = "missing_input"
    elif not contributing:
        status = "no_successful_items"
    elif policy == "run" and len(contributing) > 1:
        status = "mixed_versions"
    elif policy == "combine" and overlap:
        status = "overlapping_items"
    elif len(totals) != len(contributing):
        status = "unavailable_statistic"
    else:
        status = "ok"
        value = float(sum(totals) / sum(source.successful_items for source in contributing))
    return ExperimentScoreInput(
        alias=spec["alias"],
        statistic=spec["statistic"],
        version_policy=policy,
        status=status,
        value=value,
        sources=sources,
    )


def _passes(value: FormulaValue | None, config: dict) -> bool | None:
    if isinstance(value, bool):
        return value != (config.get("true_is_failure") is True)
    rule = config.get("passing_rule")
    if rule is not None:
        if isinstance(value, float):
            return NumericPassingRule.model_validate(rule).passes(value)
        if isinstance(value, list):
            return CategoricalPassingRule.model_validate(rule).passes(value)
    return None


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
        passed=_passes(value, version.config),
        inputs=inputs,
    )
