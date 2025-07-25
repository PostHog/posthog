"""
EXPERIMENTS DAGSTER ASSETS

This module creates Dagster assets for experiment analysis. The core concept is:
- Each experiment-metric combination becomes its own Dagster asset
- Assets can be computed independently or together as a job
- Only experiments with certain criteria are included (see filtering rules below)

Architecture:
- experiments.py: Defines individual assets and jobs
- locations/experiments.py: Bundles everything for Dagster
- Dagster: Orchestrates computation and provides UI/scheduling
"""

import dagster
from typing import Dict, Any, List

from posthog.models import Experiment
from dags.common import JobOwners


def _get_experiment_metrics() -> List[tuple[int, int, Dict[str, Any]]]:
    """
    Discover all experiment-metric combinations that need Dagster assets.
    
    This function queries the database for experiments and extracts their metrics,
    creating a flat list of (experiment_id, metric_index, metric_data) tuples.
    
    Filtering criteria:
    1. deleted=False (exclude soft-deleted experiments)
    2. metrics field is not null/empty (experiment must have metrics defined)
    3. stats_config.timeseries="true" (experiment must be configured for timeseries analysis)
    
    Returns:
        List of tuples: [(experiment_id, metric_index, metric_definition), ...]
        Example: [(123, 0, {...}), (123, 1, {...}), (456, 0, {...})]
    """
    experiment_metrics = []
    
    # Query experiments that meet our criteria
    experiments = Experiment.objects.filter(
        deleted=False,                      # Exclude soft-deleted experiments
        metrics__isnull=False,              # Must have metrics defined
        stats_config__timeseries="true"     # Must be configured for timeseries analysis
    ).exclude(metrics=[])                   # Exclude experiments with empty metrics list
    
    # Extract individual metrics from each qualifying experiment
    for experiment in experiments:
        metrics = experiment.metrics or []
        
        # Create a separate asset for each metric in the experiment
        for metric_index, metric in enumerate(metrics):
            experiment_metrics.append((experiment.id, metric_index, metric))
    
    return experiment_metrics


def _create_experiment_asset(experiment_id: int, metric_index: int, metric_data: Dict[str, Any]) -> dagster.AssetsDefinition:
    """
    Create a single Dagster asset for an experiment-metric combination.
    
    This function dynamically creates a Dagster asset that can compute results
    for a specific experiment and metric. Each asset is independent and can be
    materialized separately.
    
    Args:
        experiment_id: Database ID of the experiment
        metric_index: Index of the metric within the experiment's metrics list
        metric_data: The metric definition from the experiment.metrics field
    
    Returns:
        A Dagster AssetsDefinition that can compute results for this experiment-metric pair
    """
    asset_name = f"experiment_{experiment_id}_{metric_index}"
    
    @dagster.asset(
        name=asset_name,
        group_name="experiments",           # Group all experiment assets together
        metadata={
            "experiment_id": experiment_id,
            "metric_index": metric_index,
            "metric_type": metric_data.get("kind", "unknown"),
            "metric_name": metric_data.get("name", f"Metric {metric_index}"),
        },
        tags={"owner": JobOwners.TEAM_EXPERIMENTS.value},
    )
    def experiment_metric_asset(context: dagster.AssetExecutionContext) -> Dict[str, Any]:
        """
        Compute analysis results for this experiment-metric combination.
        
        Currently returns placeholder data. In the future, this function will:
        1. Fetch experiment data from the database
        2. Apply the metric definition to filter/transform the data
        3. Run statistical analysis
        4. Return computed results
        
        Args:
            context: Dagster execution context with logging, metadata, etc.
        
        Returns:
            Dictionary containing computed results and metadata
        """
        context.log.info(f"Computing results for experiment {experiment_id}, metric {metric_index}")
        
        # TODO: Replace this placeholder with actual experiment analysis logic
        return {
            "experiment_id": experiment_id,
            "metric_index": metric_index,
            "metric_definition": metric_data,
            "results": {
                "placeholder": True,
                "message": "Computation logic to be implemented",
                "experiment_name": _get_experiment_name(experiment_id),
                "metric_name": metric_data.get("name", f"Metric {metric_index}")
            },
            "computed_at": context.instance.get_current_timestamp()
        }
    
    return experiment_metric_asset


def _get_experiment_name(experiment_id: int) -> str:
    """
    Helper function to safely get an experiment's name by ID.
    
    Args:
        experiment_id: Database ID of the experiment
    
    Returns:
        Human-readable experiment name, or fallback string if not found
    """
    try:
        experiment = Experiment.objects.get(id=experiment_id)
        return experiment.name or f"Experiment {experiment_id}"
    except Experiment.DoesNotExist:
        return f"Experiment {experiment_id} (not found)"


# =============================================================================
# Module-level asset generation
# =============================================================================

# This code runs when the module is imported, generating all assets at startup
print("🔍 Discovering experiment-metric combinations...")
_experiment_metrics = _get_experiment_metrics()
print(f"📊 Found {len(_experiment_metrics)} experiment-metric combinations")

# Create one Dagster asset for each experiment-metric combination
experiment_assets = [
    _create_experiment_asset(exp_id, metric_idx, metric_data)
    for exp_id, metric_idx, metric_data in _experiment_metrics
]

print(f"⚡ Created {len(experiment_assets)} Dagster assets")


# =============================================================================
# Jobs and schedules
# =============================================================================

# Jobs group related assets and allow them to be run together
if experiment_assets:
    print("📋 Creating experiment computation job...")
    
    experiment_computation_job = dagster.define_asset_job(
        name="experiment_computation_job",
        selection=dagster.AssetSelection.groups("experiments"),  # Run all assets in experiments group
        tags={"owner": JobOwners.TEAM_EXPERIMENTS.value},
    )
    
    # Schedule to automatically run the job daily
    @dagster.schedule(
        job=experiment_computation_job,
        cron_schedule="0 2 * * *",        # Daily at 2 AM UTC
        execution_timezone="UTC",
        tags={"owner": JobOwners.TEAM_EXPERIMENTS.value},
    )
    def daily_experiment_computation_schedule():
        """
        Schedule to run all experiment analysis daily at 2 AM UTC.
        
        Returns:
            RunRequest to trigger the experiment computation job
        """
        return dagster.RunRequest()
    
    print("⏰ Created daily schedule for 2 AM UTC")

else:
    # Create placeholder job when no experiments exist to avoid import errors
    print("⚠️  No experiments found, creating placeholder job...")
    
    @dagster.job(tags={"owner": JobOwners.TEAM_EXPERIMENTS.value})
    def experiment_computation_job():
        """Placeholder job when no experiments are available for asset generation."""
        pass
    
    daily_experiment_computation_schedule = None


print("✅ Experiment assets setup complete!")

# =============================================================================
# Summary
# =============================================================================
#
# This module creates:
# 1. experiment_assets: List of Dagster assets, one per experiment-metric combination
#    - Only includes experiments with: not deleted, has metrics, timeseries enabled
#    - Asset names: experiment_{id}_{metric_index}
#
# 2. experiment_computation_job: Job to run all experiment assets together
#
# 3. daily_experiment_computation_schedule: Automatic daily execution at 2 AM UTC
#
# These are consumed by locations/experiments.py to create the full Dagster definitions.
