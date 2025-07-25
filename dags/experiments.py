"""
EXPERIMENTS DAGSTER ASSETS

This module creates Dagster assets for experiment analysis. The core concept is:
- Each experiment-metric combination becomes its own Dagster asset
- Assets can be computed independently or together as a job
- Only experiments with certain criteria are included

Files:
- experiments.py: Defines individual assets and jobs
- locations/experiments.py: Bundles everything for Dagster
"""

import dagster
from typing import Any
from posthog.models.experiment import Experiment
from dags.common import JobOwners
from datetime import datetime, UTC

# =============================================================================
# Assets
# =============================================================================


def _get_experiment_metrics() -> list[tuple[int, int, dict[str, Any]]]:
    """
    Discover all experiment-metric combinations that need Dagster assets

    This function queries the database for experiments and extracts their metrics,
    creating a flat list of (experiment_id, metric_index, metric_data) tuples.

    Returns:
        List of tuples: [(experiment_id, metric_index, metric), ...]
        Example: [(123, 0, {...}), (123, 1, {...}), (456, 0, {...})]
    """
    experiment_metrics = []

    # Query experiments that are eligible
    experiments = Experiment.objects.filter(
        deleted=False,  # Exclude soft-deleted experiments
        metrics__isnull=False,  # Must have metrics defined
        stats_config__timeseries="true",  # Must be configured for timeseries analysis
    ).exclude(metrics=[])  # Exclude experiments with empty metrics list

    for experiment in experiments:
        metrics = experiment.metrics or []

        for metric_index, metric in enumerate(metrics):
            experiment_metrics.append((experiment.id, metric_index, metric))

    return experiment_metrics


def _create_experiment_asset(experiment_id: int, metric_index: int, metric: dict[str, Any]) -> dagster.AssetsDefinition:
    """
    Create a single Dagster asset for an experiment-metric combination.
    """
    asset_name = f"experiment_{experiment_id}_{metric_index}"

    @dagster.asset(
        name=asset_name,
        group_name="experiments",
        metadata={
            "experiment_id": experiment_id,
            "metric_index": metric_index,
            "metric_type": metric.get("kind"),
            "metric_name": metric.get("name", f"Metric {metric_index}"),
        },
        tags={"owner": JobOwners.TEAM_EXPERIMENTS.value},
    )
    def experiment_metric_asset(context: dagster.AssetExecutionContext) -> dict[str, Any]:
        """
        Compute timeseries results for this experiment-metric combination.
        """
        context.log.info(f"Computing results for experiment {experiment_id}, metric {metric_index}")

        # TODO: Replace this placeholder with actual experiment analysis logic
        return {
            "experiment_id": experiment_id,
            "metric_index": metric_index,
            "metric_definition": metric,
            "results": {
                "placeholder": True,
                "message": "Calculation logic to be implemented",
                "metric_name": metric.get("name", f"Metric {metric_index}"),
            },
            "computed_at": datetime.now(UTC).isoformat(),
        }

    return experiment_metric_asset


_experiment_metrics = _get_experiment_metrics()

experiment_assets = [
    _create_experiment_asset(exp_id, metric_idx, metric) for exp_id, metric_idx, metric in _experiment_metrics
]

# =============================================================================
# Jobs and schedules
# =============================================================================

if experiment_assets:
    experiment_computation_job = dagster.define_asset_job(
        name="experiment_computation_job",
        selection=dagster.AssetSelection.groups("experiments"),
        tags={"owner": JobOwners.TEAM_EXPERIMENTS.value},
    )

    @dagster.schedule(
        job=experiment_computation_job,
        cron_schedule="0 2 * * *",  # Daily at 2 AM UTC
        execution_timezone="UTC",
        tags={"owner": JobOwners.TEAM_EXPERIMENTS.value},
    )
    def daily_experiment_computation_schedule():
        """
        Trigger scheduled computation of experiment assets.
        """
        return dagster.RunRequest()

else:
    # Create placeholder job when no experiments exist to avoid import errors
    @dagster.job(tags={"owner": JobOwners.TEAM_EXPERIMENTS.value})
    def experiment_computation_job():
        """Placeholder job when no experiments are available for asset generation."""
        pass

    daily_experiment_computation_schedule = None
