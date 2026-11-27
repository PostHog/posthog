from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db import models
from django.db.models import Exists, OuterRef, QuerySet

from rest_framework import serializers

from products.ai_observability.backend.composite_formula import (
    MAX_COMPOSITE_INPUTS,
    MAX_FORMULA_LENGTH,
    CompositeFormula,
    CompositeFormulaError,
)
from products.ai_observability.backend.models.score_definitions import (
    ScoreDefinition,
    ScoreDefinitionInput,
    ScoreDefinitionVersion,
)

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl


class ExperimentScoreStatus(models.TextChoices):
    OK = "ok"
    MIXED_VERSIONS = "mixed_versions"
    MISSING_INPUT = "missing_input"
    NO_SUCCESSFUL_ITEMS = "no_successful_items"
    UNAVAILABLE_STATISTIC = "unavailable_statistic"
    OVERLAPPING_ITEMS = "overlapping_items"
    FORMULA_ERROR = "formula_error"
    PENDING = "pending"
    FAILED = "failed"


class ExperimentScoreStatistic(models.TextChoices):
    PASS_RATE = "pass_rate", "pass_rate"
    MEAN = "mean", "mean"
    TRUE_RATE = "true_rate", "true_rate"
    CATEGORY_RATE = "category_rate", "category_rate"


class ExperimentScoreVersionPolicy(models.TextChoices):
    RUN = "run", "run"
    EXACT = "exact", "exact"
    COMBINE = "combine", "combine"


class CompositeInputSerializer(serializers.Serializer):
    alias = serializers.RegexField(
        r"^[a-z][a-z0-9_]{0,31}$",
        max_length=32,
        help_text="Input name used in the formula. Start with a lowercase letter; use letters, digits, and underscores.",
    )
    scorer_version_id = serializers.UUIDField(
        help_text="Version of the input item scorer. Experiment formulas use its definition to find the run's results unless the version policy is exact."
    )
    statistic = serializers.ChoiceField(choices=ExperimentScoreStatistic.choices, required=False)
    version_policy = serializers.ChoiceField(choices=ExperimentScoreVersionPolicy.choices, required=False)
    category = serializers.CharField(max_length=128, required=False)

    def validate_alias(self, value: str) -> str:
        if value in {
            "number",
            "min",
            "max",
            "abs",
            "and",
            "or",
            "not",
            "if",
            "else",
            "in",
            "is",
            "lambda",
            "for",
            "await",
        }:
            raise serializers.ValidationError("Choose an input name that is not a formula keyword or function.")
        return value

    def validate_scorer_version_id(self, value: object) -> str:
        return str(value)


class CompositeConfigSerializer(serializers.Serializer):
    expression = serializers.CharField(
        max_length=MAX_FORMULA_LENGTH,
        help_text=(
            "Formula using the declared input aliases. Supports +, -, *, /, comparisons, and/or/not, "
            "conditional expressions, and number(), min(), max(), abs(). Boolean inputs are raw values: "
            "number(True) is 1 and number(False) is 0, regardless of passing rules. Categorical inputs are "
            'lists of keys: use "good" in relevance. Examples: (2 * precision + recall) / 3; safe and correct; '
            '"good" if correct else "bad". Every input alias must appear. Line breaks are allowed. '
            "Arithmetic results use 12 significant digits. Up to 1,024 characters and 16 input scorers."
        ),
    )
    inputs: serializers.ListSerializer = serializers.ListSerializer(
        child=CompositeInputSerializer(),
        min_length=1,
        max_length=MAX_COMPOSITE_INPUTS,
        help_text="Named inputs. Item formulas use reported results from exact versions. Experiment formulas use statistics from item scorers.",
    )

    def validate_inputs(self, value: list[dict[str, str]]) -> list[dict[str, str]]:
        if len({item["alias"] for item in value}) != len(value):
            raise serializers.ValidationError("Give each input a unique name.")
        return sorted(value, key=lambda item: item["alias"])


class CompositeScorers:
    @staticmethod
    def accessible_versions(
        definitions: QuerySet[ScoreDefinition], *, team_id: int
    ) -> QuerySet[ScoreDefinitionVersion]:
        denied_inputs = (
            ScoreDefinitionInput.objects.for_team(team_id, canonical=True)
            .filter(composite_version_id=OuterRef("pk"))
            .exclude(input_version__definition__in=definitions)
        )
        direct = ScoreDefinitionVersion.objects.filter(definition__in=definitions).exclude(Exists(denied_inputs))
        denied_composites = (
            ScoreDefinitionInput.objects.for_team(team_id, canonical=True)
            .filter(composite_version_id=OuterRef("pk"), input_version__definition__calculation="composite")
            .exclude(input_version__in=direct)
        )
        return direct.exclude(Exists(denied_composites))

    @staticmethod
    def validate(
        *,
        composition: dict[str, Any] | None,
        calculation: str,
        kind: str,
        config: dict[str, Any] | None = None,
        team_id: int,
        user_access_control: UserAccessControl | None,
        scope: str = "item",
    ) -> None:
        if calculation == ScoreDefinition.Calculation.REPORTED:
            if scope == "experiment":
                raise serializers.ValidationError({"calculation": "Choose a formula for an experiment scorer."})
            if composition is not None:
                raise serializers.ValidationError({"composition": "Only composite scorers accept a formula."})
            return
        if composition is None:
            raise serializers.ValidationError({"composition": "Provide a formula and its input scorer versions."})
        if kind == "numeric" and config is not None and config.get("step") is not None:
            raise serializers.ValidationError({"config": "Increments apply only to reported scorers."})
        definitions = ScoreDefinition.objects.filter(team_id=team_id)
        if user_access_control is not None:
            definitions = user_access_control.filter_queryset_by_access_level(
                definitions, include_all_if_admin=True, resource="llm_analytics"
            )
        ids = {item["scorer_version_id"] for item in composition["inputs"]}
        versions = {
            str(version.id): version
            # nosemgrep: idor-lookup-without-user -- Versions inherit team and caller access from their definitions.
            for version in CompositeScorers.accessible_versions(definitions, team_id=team_id)
            .filter(id__in=ids, definition__scope="item")
            .select_related("definition")
        }
        if versions.keys() != ids or (
            scope == "item" and any(version.definition.calculation != "reported" for version in versions.values())
        ):
            raise serializers.ValidationError(
                {
                    "composition": "Select accessible input scorers in this project. Item formulas require reported scorers."
                }
            )
        kinds = {}
        for item in composition["inputs"]:
            version = versions[item["scorer_version_id"]]
            input_kind = version.definition.kind
            if scope == "experiment":
                statistic = item.get("statistic")
                allowed = {
                    "mean": input_kind == "numeric",
                    "true_rate": input_kind == "boolean",
                    "pass_rate": input_kind == "boolean" or bool(version.config.get("passing_rule")),
                    "category_rate": input_kind == "categorical"
                    and item.get("category") in {option["key"] for option in version.config.get("options", [])},
                }
                if not allowed.get(statistic) or ("category" in item and statistic != "category_rate"):
                    raise serializers.ValidationError(
                        {"composition": f"Choose an available statistic for {item['alias']}."}
                    )
                kinds[item["alias"]] = "numeric"
            else:
                if {"statistic", "version_policy", "category"}.intersection(item):
                    raise serializers.ValidationError({"composition": "Statistics apply to experiment scorers."})
                kinds[item["alias"]] = input_kind
        try:
            formula = CompositeFormula.parse(
                composition["expression"],
                kinds,
                kind,
            )
            if config is not None:
                formula.validate_output(kind, config)
        except CompositeFormulaError as error:
            raise serializers.ValidationError({"composition": str(error)}) from error
