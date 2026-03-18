from posthog.schema import MaxExperimentMetricResult

from posthog.hogql_queries.experiments.utils import get_experiment_stats_method
from posthog.models import Experiment, Team
from posthog.sync import database_sync_to_async

from .prompts import (
    EXPERIMENT_CONCLUSION_COMMENT_TEMPLATE,
    EXPERIMENT_CONCLUSION_TEMPLATE,
    EXPERIMENT_CONTEXT_TEMPLATE,
    EXPERIMENT_DATES_TEMPLATE,
    EXPERIMENT_FEATURE_FLAG_VARIANTS_TEMPLATE,
    EXPERIMENT_NOT_FOUND_TEMPLATE,
    EXPERIMENT_VARIANTS_TEMPLATE,
)


class ExperimentContext:
    """
    Context class for experiments used across the assistant.

    Provides methods to fetch experiment data and format it for AI consumption.
    """

    def __init__(
        self,
        team: Team,
        experiment_id: int | None = None,
        feature_flag_key: str | None = None,
    ):
        self._team = team
        self._experiment_id = experiment_id
        self._feature_flag_key = feature_flag_key

    async def aget_experiment(self) -> Experiment | None:
        """Fetch the experiment from the database."""
        try:
            if self._experiment_id is not None:
                return await Experiment.objects.select_related("feature_flag").aget(
                    id=self._experiment_id, team=self._team, deleted=False
                )
            elif self._feature_flag_key is not None:
                return await Experiment.objects.select_related("feature_flag").aget(
                    feature_flag__key=self._feature_flag_key, team=self._team, deleted=False
                )
            return None
        except Experiment.DoesNotExist:
            return None

    def get_not_found_message(self) -> str:
        """Return a formatted not found message."""
        identifier = (
            f"id={self._experiment_id}" if self._experiment_id else f"feature_flag_key={self._feature_flag_key}"
        )
        return EXPERIMENT_NOT_FOUND_TEMPLATE.format(identifier=identifier)

    def _get_experiment_status(self, experiment: Experiment) -> str:
        """Determine the experiment status."""
        if experiment.is_draft:
            return "Draft"
        elif not experiment.end_date:
            return "Running"
        else:
            return "Completed"

    @database_sync_to_async
    def format_experiment(self, experiment: Experiment) -> str:
        """Format experiment data for AI consumption."""
        dates_section = ""
        if experiment.start_date or experiment.end_date:
            start_date = experiment.start_date.isoformat() if experiment.start_date else "Not started"
            end_date = experiment.end_date.isoformat() if experiment.end_date else "Ongoing"
            dates_section = EXPERIMENT_DATES_TEMPLATE.format(
                start_date=start_date,
                end_date=end_date,
            )

        conclusion_section = ""
        if experiment.conclusion:
            conclusion_comment_section = ""
            if experiment.conclusion_comment:
                conclusion_comment_section = EXPERIMENT_CONCLUSION_COMMENT_TEMPLATE.format(
                    conclusion_comment=experiment.conclusion_comment
                )
            conclusion_section = EXPERIMENT_CONCLUSION_TEMPLATE.format(
                conclusion=experiment.conclusion,
                conclusion_comment_section=conclusion_comment_section,
            )

        variants_section = ""
        if experiment.variants:
            variants_list = "\n".join(
                f"- {key}: {variant.get('name', key)}" for key, variant in experiment.variants.items()
            )
            variants_section = EXPERIMENT_VARIANTS_TEMPLATE.format(variants_list=variants_list)

        feature_flag_variants_section = ""
        if experiment.parameters:
            params = experiment.parameters
            if params.get("feature_flag_variants"):
                variants_list = "\n".join(
                    f"- {v.get('key', 'unknown')}: {v.get('rollout_percentage', 0)}%"
                    for v in params["feature_flag_variants"]
                )
                feature_flag_variants_section = EXPERIMENT_FEATURE_FLAG_VARIANTS_TEMPLATE.format(
                    variants_list=variants_list
                )

        return EXPERIMENT_CONTEXT_TEMPLATE.format(
            experiment_name=experiment.name,
            experiment_id=experiment.id,
            experiment_description=experiment.description or "No description",
            feature_flag_key=experiment.feature_flag.key,
            experiment_type=experiment.type or "product",
            experiment_status=self._get_experiment_status(experiment),
            dates_section=dates_section,
            conclusion_section=conclusion_section,
            variants_section=variants_section,
            feature_flag_variants_section=feature_flag_variants_section,
            experiment_created_at=experiment.created_at.isoformat() if experiment.created_at else "Unknown",
        ).strip()

    @database_sync_to_async
    def format_experiment_results_data(
        self,
        experiment: Experiment,
        exposures: dict[str, float] | None = None,
        primary_metrics_results: list[MaxExperimentMetricResult] | None = None,
        secondary_metrics_results: list[MaxExperimentMetricResult] | None = None,
    ) -> str:
        """Format experiment results data including metrics for AI analysis."""
        lines: list[str] = []

        stats_method = get_experiment_stats_method(experiment)

        multivariate = experiment.feature_flag.filters.get("multivariate", {})
        variants = [v.get("key") for v in multivariate.get("variants", []) if v.get("key")]

        lines.append(f"## Experiment: {experiment.name}")
        lines.append(f"**ID:** {experiment.id}")
        lines.append(f"**Statistical Method:** {stats_method.title()}")

        if experiment.description:
            lines.append(f"**Hypothesis:** {experiment.description}")

        if variants:
            lines.append(f"\n**Variants:** {', '.join(variants)}")

        if exposures:
            lines.append("\n### Exposures")
            total = sum(exposures.values())
            lines.append(f"**Total:** {int(total)}")

            for variant_key, count in exposures.items():
                if variant_key == "$multiple":
                    continue
                percentage = (count / total * 100) if total > 0 else 0
                lines.append(f"- {variant_key}: {int(count)} ({percentage:.1f}%)")

            if "$multiple" in exposures:
                multiple_count = exposures.get("$multiple", 0)
                multiple_pct = (multiple_count / total * 100) if total > 0 else 0
                lines.append(f"- $multiple: {int(multiple_count)} ({multiple_pct:.1f}%)")
                if multiple_pct > 0.5:
                    lines.append("**Warning:** Users exposed to multiple variants detected")

        if not primary_metrics_results and not secondary_metrics_results:
            lines.append("\n**No metrics results available yet.**")
            return "\n".join(lines)

        def format_metrics_section(metrics: list[MaxExperimentMetricResult], section_name: str) -> None:
            if not metrics:
                return

            lines.append(f"\n### {section_name}")
            for metric in metrics[:10]:
                lines.append(f"\n**Metric: {metric.name}**")
                if metric.goal and metric.goal.value:
                    lines.append(f"Goal: {metric.goal.value.title()}")

                if not metric.variant_results:
                    continue

                for variant in metric.variant_results:
                    lines.append(f"\n*{variant.key}:*")

                    if stats_method == "bayesian":
                        if hasattr(variant, "chance_to_win") and variant.chance_to_win is not None:
                            lines.append(f"  - Chance to win: {variant.chance_to_win:.1%}")

                        if hasattr(variant, "credible_interval") and variant.credible_interval:
                            ci_low, ci_high = variant.credible_interval[:2]
                            lines.append(f"  - 95% credible interval: {ci_low:.1%} - {ci_high:.1%}")

                        if hasattr(variant, "delta") and variant.delta is not None:
                            lines.append(f"  - Delta (effect size): {variant.delta:.1%}")

                        lines.append(f"  - Significant: {'Yes' if variant.significant else 'No'}")
                    else:
                        if hasattr(variant, "p_value") and variant.p_value is not None:
                            lines.append(f"  - P-value: {variant.p_value:.4f}")

                        if hasattr(variant, "confidence_interval") and variant.confidence_interval:
                            ci_low, ci_high = variant.confidence_interval[:2]
                            lines.append(f"  - 95% confidence interval: {ci_low:.1%} - {ci_high:.1%}")

                        if hasattr(variant, "delta") and variant.delta is not None:
                            lines.append(f"  - Delta (effect size): {variant.delta:.1%}")

                        lines.append(f"  - Significant: {'Yes' if variant.significant else 'No'}")

        format_metrics_section(primary_metrics_results or [], "Primary Metrics")
        format_metrics_section(secondary_metrics_results or [], "Secondary Metrics")

        return "\n".join(lines)

    async def execute_and_format(self) -> str:
        """
        Fetch and format the experiment for AI consumption.

        Returns a formatted string with all experiment context.
        """
        experiment = await self.aget_experiment()
        if experiment is None:
            return self.get_not_found_message()

        return await self.format_experiment(experiment)
